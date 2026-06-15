import csv
import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

import pyodbc

# ======================================================
# CONFIGURATION
# ======================================================

SERVER = r"YS00583Q\SQLEXPRESS"
DATABASE = "Copy_RECT"

CSV_FILE = r"D:\Utility_Scripts\Sajida\TN_DOCUMENTS.csv"

CONNECTION_STRING = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={SERVER};"
    f"DATABASE={DATABASE};"
    "UID=sa;"
    "PWD=R7!vQ9#Zx@2L$A8K;"
    "TrustServerCertificate=yes;"
)

BATCH_SIZE = 5000
TEST_LIMIT = 561964

# ======================================================
# LOGGING
# ======================================================

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FOLDER = r"D:\Utility_Scripts\Sajida\logs"

os.makedirs(LOG_FOLDER, exist_ok=True)

log_file = os.path.join(
    LOG_FOLDER,
    f"update_log_{timestamp}.txt"
)

logger = logging.getLogger("DBUpdateLogger")
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s"
)

file_handler = RotatingFileHandler(
    log_file,
    maxBytes=10 * 1024 * 1024,
    backupCount=5
)

file_handler.setFormatter(formatter)

logger.addHandler(file_handler)

# ======================================================
# DATABASE CONNECTION
# ======================================================

def get_connection():

    logger.info("Connecting to database")

    conn = pyodbc.connect(CONNECTION_STRING)

    logger.info("Database connected")

    return conn

# ======================================================
# UPDATE FUNCTION
# ======================================================

def update_from_csv():

    conn = get_connection()

    cursor = conn.cursor()

    # Huge performance improvement
    cursor.fast_executemany = True

    update_query = """
    UPDATE dbo.TN_DOCUMENTS
    SET TDMX_SW_CONFIGURATION = ?
    WHERE OBJECT_ID = ?
    """

    batch = []

    total_updated = 0

    logger.info(f"Reading CSV: {CSV_FILE}")

    with open(
        CSV_FILE,
        mode="r",
        encoding="utf-8-sig"
    ) as file:

        reader = csv.DictReader(file)
        processed_count = 0
        for row in reader:
            processed_count += 1
            if processed_count > TEST_LIMIT:
                break

            object_id = row["OBJECT_ID"]

            sw_config = row["TDMX_SW_CONFIGURATION"]

            batch.append(
                (
                    sw_config,
                    object_id
                )
            )

            # Execute batch
            if len(batch) >= BATCH_SIZE:

                cursor.executemany(
                    update_query,
                    batch
                )

                conn.commit()

                total_updated += len(batch)

                logger.info(
                    f"Updated rows: {total_updated} | {object_id}"
                )

                print(f"Updated rows: {total_updated}")

                batch.clear()

        # Final remaining batch
        if batch:

            cursor.executemany(
                update_query,
                batch
            )

            conn.commit()

            total_updated += len(batch)

    logger.info(
        f"UPDATE COMPLETED | Total Rows Updated: {total_updated}"
    )

    print(f"TOTAL UPDATED: {total_updated}")

    conn.close()

# ======================================================
# ENTRY
# ======================================================

if __name__ == "__main__":

    try:

        update_from_csv()

    except Exception as e:

        logger.exception(
            f"FATAL ERROR | {str(e)}"
        )

        print(str(e))