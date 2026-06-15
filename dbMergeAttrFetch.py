
import csv
import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

import pyodbc

# ======================================================
# TEST CONFIG
# ======================================================

TEST_MODE = False
TEST_LIMIT = 10000

# =====================================================
# DEFINE LOOKUP TABLE
# =====================================================

def load_lookup_table(conn, table_name, key_col, value_col):

    query = f"""
    SELECT {key_col}, {value_col}
    FROM dbo.{table_name}
    """

    cursor = conn.cursor()
    cursor.execute(query)

    lookup = {}

    for row in cursor.fetchall():
        lookup[row[0]] = row[1]

    logger.info(
        f"Loaded lookup table: {table_name} | Rows: {len(lookup)}"
    )

    return lookup

# ======================================================
# LOOKUP MAPPING
# ======================================================
LOOKUP_CONFIG = {
    "CN_DOCUMENT_APPLICABILITY": {
        "table": "TN_DOCUMENT_APPLICABILITY",
        "key": "OBJECT_ID",
        "value": "TDM_NAME"
    },
    "CN_DOC_LIST_1":{
        "table": "TN_DOC_LIST_1",
        "key": "OBJECT_ID",
        "value": "TDM_NAME"
    }
}

# =========================================================
# CONFIGURATION
# =========================================================

print(pyodbc.drivers())
SERVER = r"YS00583Q\SQLEXPRESS"
DATABASE = "Copy_RECT"

# Windows Authentication
#CONNECTION_STRING = (
#    "DRIVER={ODBC Driver 17 for SQL Server};"
#    f"SERVER={SERVER};"
#    f"DATABASE={DATABASE};"
#    "Trusted_Connection=yes;"
#)

#OR SQL Authentication
CONNECTION_STRING = (
     "DRIVER={ODBC Driver 18 for SQL Server};"
     f"SERVER={SERVER};"
     f"DATABASE={DATABASE};"
     "UID=sa;"
     "PWD=R7!vQ9#Zx@2L$A8K;"
     #"Trusted_Connection=yes;"
     "TrustServerCertificate=yes;"
 )

EXPORT_FOLDER = r"D:\Utility_Scripts\Sajida"
LOG_FOLDER = r"D:\Utility_Scripts\Sajida\logs"

# Large data optimization
CHUNK_SIZE = 50000

# Tables and columns to export
TABLE_CONFIG = {
    "TN_DOCUMENTS": [
        "OBJECT_ID",
        "CLASS_ID",
        "TDMX_ID",
        "CN_DOCUMENT_APPLICABILITY",
        "CN_DOC_LIST_1",
        "TDMX_DETAILED_DESCRIPTION",
        "TDMX_COMMENTS",
        "TDMX_SW_CONFIGURATION"
        #"TDMX_SW_CONFIGURATION_UPDATE"
    ]
    # "Orders": [
    #     "ObjectID",
    #     "OrderNumber",
    #     "Amount",
    #     "Status",
    #     "CreatedDate"
    # ]
}

# ======================================================
# CREATE FOLDERS
# ======================================================

os.makedirs(EXPORT_FOLDER, exist_ok=True)
os.makedirs(LOG_FOLDER, exist_ok=True)

# ======================================================
# LOGGING
# ======================================================

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

log_file = os.path.join(
    LOG_FOLDER,
    f"export_log_{timestamp}.txt"
)

logger = logging.getLogger("ExportLogger")
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
# EXPORT FUNCTION
# ======================================================

def export_table(conn, table_name, columns, lookup_cache):

    logger.info(f"Starting export for {table_name}")

    try:

        csv_file = os.path.join(
            EXPORT_FOLDER,
            f"{table_name}_{timestamp}.csv"
        )

        column_string = ", ".join(columns)

        if TEST_MODE:
            print("inside test mode")
            query = f"""
            SELECT TOP {TEST_LIMIT} {column_string}
            FROM dbo.{table_name}
            """
        else:
            print("inside full db mode")
            query = f"""
            SELECT {column_string}
            FROM dbo.{table_name}
            """
        print(query)
        cursor = conn.cursor()

        logger.info(f"Executing query for {table_name}")

        cursor.execute(query)

        rows_exported = 0

        with open(
            csv_file,
            mode="w",
            newline="",
            encoding="utf-8-sig"
        ) as file:

            writer = csv.writer(file)

            # Write CSV header
            writer.writerow(columns)

            while True:

                rows = cursor.fetchmany(5000)

                if not rows:
                    break

                processed_rows = []

                for row in rows:

                    row = list(row)

                    for idx, column_name in enumerate(columns):

                        if column_name in LOOKUP_CONFIG:

                            lookup_value = lookup_cache[column_name].get(
                                row[idx]
                            )

                            row[idx] = lookup_value if lookup_value else ""

                    # ==================================================
                    # BUILD MERGED CONFIGURATION TEXT
                    # ==================================================

                    try:

                        applicability_idx = columns.index("CN_DOCUMENT_APPLICABILITY")
                        detailed_desc_idx = columns.index("TDMX_DETAILED_DESCRIPTION")
                        comments_idx = columns.index("TDMX_COMMENTS")
                        design_module_idx = columns.index("CN_DOC_LIST_1")
                       # sw_config_idx = columns.index("TDMX_SW_CONFIGURATION_UPDATE")
                        sw_config_idx = columns.index("TDMX_SW_CONFIGURATION")

                        applicability_value = row[applicability_idx] or ""
                        detailed_desc_value = row[detailed_desc_idx] or ""
                        comments_value = row[comments_idx] or ""
                        design_module_value = row[design_module_idx] or ""

                        merged_text = (
                            f"A/C Applicability: {applicability_value}\n"
                            f"Design Module: {design_module_value}\n"
                            f"Details: {detailed_desc_value}\n"
                            f"Comments: {comments_value}"
                        )

                        # Store merged value into TDMX_SW_CONFIGURATION
                        row[sw_config_idx] = merged_text

                    except Exception as merge_error:

                        logger.warning(
                            f"Merge failed for row: {str(merge_error)}"
                        )

                    processed_rows.append(row)

                writer.writerows(processed_rows)

                rows_exported += len(processed_rows)

                logger.info(
                    f"{table_name} | Exported rows: {rows_exported}"
                )

        logger.info(
            f"SUCCESS | {table_name} | "
            f"Total Rows: {rows_exported}"
        )

        print(f"CSV CREATED: {csv_file}")

    except Exception as e:

        logger.exception(
            f"FAILED | {table_name} | {str(e)}"
        )

# ======================================================
# MAIN
# ======================================================

def main():

    logger.info("===================================")
    logger.info("EXPORT PROCESS STARTED")
    logger.info("===================================")

    try:

        conn = get_connection()

        # =========================================
        # LOAD LOOKUP TABLES
        # =========================================

        lookup_cache = {}

        for column_name, config in LOOKUP_CONFIG.items():

            lookup_cache[column_name] = load_lookup_table(
                conn,
                config["table"],
                config["key"],
                config["value"]
            )
        
        # =========================================
        # EXPORT TABLES
        # =========================================
        for table_name, columns in TABLE_CONFIG.items():

            export_table(
                conn,
                table_name,
                columns,
                lookup_cache
            )

        conn.close()

        logger.info("Database connection closed")

    except Exception as e:

        logger.exception(f"FATAL ERROR | {str(e)}")

    logger.info("===================================")
    logger.info("EXPORT PROCESS COMPLETED")
    logger.info("===================================")

# ======================================================
# ENTRY
# ======================================================

if __name__ == "__main__":
    main()