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

CSV_FILE = r"D:\Utility_Scripts\Sajida\TN_DOCUMENTS_SELECTIVE_20260620_060153.csv"
#CSV_FILE = r"D:\Utility_Scripts\AttributeMerge\AttributeMergeInputFileForUpdate.csv"

CONNECTION_STRING = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={SERVER};"
    f"DATABASE={DATABASE};"
    "UID=sa;"
    "PWD=R7!vQ9#Zx@2L$A8K;"
    "TrustServerCertificate=yes;"
)

BATCH_SIZE = 49659
TEST_LIMIT = 49659

# ======================================================
# LOGGING
# ======================================================

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FOLDER = r"D:\Utility_Scripts\Sajida\logs"
#LOG_FOLDER = r"D:\Utility_Scripts\AttributeMerge"


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

# Console handler (UTF-8 safe) so progress + errors also show in terminal
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
console_handler = logging.StreamHandler(_sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
logger.propagate = False

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

def get_column_max_length(cursor, table, column, schema="dbo"):
    """
    Return the column's max character length from SQL Server metadata.
      - a positive int  -> fixed width (e.g. 1024)
      - -1              -> MAX (nvarchar(max)/varchar(max))  [we treat as unlimited]
      - None            -> column/info not found
    """
    cursor.execute(
        """
        SELECT CHARACTER_MAXIMUM_LENGTH
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? AND COLUMN_NAME = ?
        """,
        (schema, table, column),
    )
    r = cursor.fetchone()
    if r is None:
        return None
    return r[0]   # int, -1 for MAX, or None


def update_from_csv():

    conn = get_connection()

    cursor = conn.cursor()

    # ------------------------------------------------------
    # Detect target column width so we can size the parameter
    # buffer correctly (avoids fast_executemany's
    # "String data, right truncation" error, which happens when
    # pyodbc guesses the buffer from the first row).
    # ------------------------------------------------------
    col_len = get_column_max_length(cursor, "TN_DOCUMENTS", "TDMX_SW_CONFIGURATION")
    if col_len is None:
        logger.warning(
            "Could not read TDMX_SW_CONFIGURATION length from metadata; "
            "defaulting buffer to MAX."
        )
        col_len = -1
    logger.info(
        f"TDMX_SW_CONFIGURATION CHARACTER_MAXIMUM_LENGTH = {col_len} "
        f"({'MAX' if col_len == -1 else col_len})"
    )

    # Is the column fixed-width (so we may need to truncate) or MAX?
    is_max = (col_len == -1)
    max_chars = None if is_max else int(col_len)

    # Huge performance improvement
    cursor.fast_executemany = True

    # Tell pyodbc the real parameter sizes so the buffer is wide enough
    # for ANY row, not just the first one.
    #   param 1 = TDMX_SW_CONFIGURATION (nvarchar)
    #   param 2 = OBJECT_ID
    # For MAX columns we pass 0 with SQL_WVARCHAR, which pyodbc treats as
    # an unbounded (max) parameter.
    try:
        if is_max:
            cursor.setinputsizes([(pyodbc.SQL_WVARCHAR, 0, 0), None])
        else:
            cursor.setinputsizes([(pyodbc.SQL_WVARCHAR, max_chars, 0), None])
    except Exception as e:
        logger.warning(f"setinputsizes failed (continuing): {e}")

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

            # No truncation: if a value is longer than the column can hold,
            # STOP with a clear error rather than silently clipping data.
            if (not is_max) and sw_config is not None and len(sw_config) > max_chars:
                msg = (
                    f"Value too long for TDMX_SW_CONFIGURATION "
                    f"(column={max_chars}, value={len(sw_config)}) "
                    f"at OBJECT_ID={object_id}. "
                    f"Widen the column (e.g. ALTER TABLE dbo.TN_DOCUMENTS "
                    f"ALTER COLUMN TDMX_SW_CONFIGURATION NVARCHAR(2000);) "
                    f"and re-run. No rows from this batch were committed."
                )
                logger.error(msg)
                raise ValueError(msg)

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