
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
# SELECTIVE FETCH CONFIG
# ------------------------------------------------------
# Input is a CSV report listing the objects to fetch.
#   FileName -> TDMX_ID  (strip everything from the first "_",
#               e.g. "DOC-0012020_96" -> "DOC-0012020")
# ALL revisions of each TDMX_ID are fetched (revision is NOT filtered;
# you filter by revision later). Output is IDENTICAL in format to the
# full export (same columns, lookups, merged TDMX_SW_CONFIGURATION).
# ======================================================

SELECTIVE_TABLE = "TN_DOCUMENTS"

# CSV file that lists which objects to fetch
SELECTIVE_INPUT_CSV = r"D:\Utility_Scripts\Sajida\All_Project_Report.csv"

# Column header in the CSV (only FileName is needed now)
SELECTIVE_FILENAME_COL = "FileName"
SELECTIVE_VERSION_COL = "FileVersion"   # kept for reference; not used for matching

# How many TDMX_IDs to match per SQL batch
SELECTIVE_BATCH = 500

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

# ------------------------------------------------------
# Console handler — so every logger.info/.warning/.exception
# (including full tracebacks) also prints to the terminal,
# not only into the log file.
# ------------------------------------------------------
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Avoid duplicate lines if the module is imported more than once
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
# SHARED ROW PROCESSOR
# (resolves lookups + builds merged TDMX_SW_CONFIGURATION)
# Used by BOTH the full export and the selective export so the
# output rows are produced identically.
# ======================================================

def process_row(row, columns, lookup_cache):

    # Resolve lookup columns (applicability, doc-list/design-module, ...)
    for idx, column_name in enumerate(columns):

        if column_name in LOOKUP_CONFIG:

            lookup_value = lookup_cache[column_name].get(row[idx])
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

    return row

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

                processed_rows = [
                    process_row(list(r), columns, lookup_cache)
                    for r in rows
                ]

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
# SELECTIVE EXPORT
# ======================================================

def load_selective_targets():
    """
    Read the selective CSV report and return:
      - tdmx_ids: a de-duplicated, ordered list of TDMX_IDs
      - seen:     a set of those ids for fast membership tests

    Mapping:
      FileName -> TDMX_ID  (drop everything from the first "_")

    Revision is intentionally IGNORED here — we fetch ALL revisions of
    each TDMX_ID and you filter by revision later. Only the FileName
    column is required; FileVersion is not used.
    Pure standard library (csv) — no openpyxl / numpy.
    """
    logger.info(f"Reading selective targets from {SELECTIVE_INPUT_CSV}")

    seen = set()
    tdmx_ids = []

    with open(SELECTIVE_INPUT_CSV, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            logger.warning("Selective input CSV is empty")
            return [], set()

        if SELECTIVE_FILENAME_COL not in reader.fieldnames:
            logger.error(
                f"Required column '{SELECTIVE_FILENAME_COL}' not found. "
                f"Header={reader.fieldnames}"
            )
            return [], set()

        for r in reader:
            raw_name = r.get(SELECTIVE_FILENAME_COL)

            if raw_name is None or str(raw_name).strip() == "":
                continue

            # FileName -> TDMX_ID : drop everything from the first "_"
            tdmx_id = str(raw_name).split("_")[0].strip()
            if not tdmx_id:
                continue

            if tdmx_id not in seen:
                seen.add(tdmx_id)
                tdmx_ids.append(tdmx_id)

    logger.info(
        f"Selective targets: {len(tdmx_ids)} unique TDMX_ID(s) "
        f"(fetching ALL revisions of each)"
    )
    return tdmx_ids, seen


def export_table_selective(conn, lookup_cache):
    """
    Selectively export documents whose TDMX_ID is listed in the CSV.
    ALL revisions of each TDMX_ID are returned (revision is not filtered).
    Output CSV is identical in format to the full export (same columns,
    lookups, merged TDMX_SW_CONFIGURATION).
    """
    table_name = SELECTIVE_TABLE
    columns = TABLE_CONFIG[table_name]

    logger.info("===================================")
    logger.info(f"SELECTIVE export started for {table_name}")
    logger.info("===================================")

    try:
        tdmx_ids, _ = load_selective_targets()
        if not tdmx_ids:
            logger.warning("No selective targets found — nothing to export.")
            print("No selective targets found.")
            return

        csv_file = os.path.join(
            EXPORT_FOLDER,
            f"{table_name}_SELECTIVE_{timestamp}.csv"
        )

        # Export columns only — no REVISION filter column needed now.
        column_string = ", ".join(columns)
        tdmx_pos = columns.index("TDMX_ID")

        cursor = conn.cursor()

        rows_exported = 0
        matched_tdmx = set()

        with open(
            csv_file,
            mode="w",
            newline="",
            encoding="utf-8-sig"
        ) as file:

            writer = csv.writer(file)
            writer.writerow(columns)   # same header as full export

            # Fetch in batches using WHERE TDMX_ID IN (?, ?, ...).
            for start in range(0, len(tdmx_ids), SELECTIVE_BATCH):

                batch = tdmx_ids[start:start + SELECTIVE_BATCH]

                placeholders = ", ".join(["?"] * len(batch))
                query = f"""
                SELECT {column_string}
                FROM dbo.{table_name}
                WHERE TDMX_ID IN ({placeholders})
                """

                cursor.execute(query, batch)

                while True:
                    fetched = cursor.fetchmany(5000)
                    if not fetched:
                        break

                    processed_rows = []
                    for raw in fetched:
                        raw = list(raw)

                        # Track which requested TDMX_IDs were found
                        db_tdmx = raw[tdmx_pos]
                        if db_tdmx is not None:
                            matched_tdmx.add(str(db_tdmx).strip())

                        # Same processing as the full export
                        processed_rows.append(
                            process_row(raw, columns, lookup_cache)
                        )

                    writer.writerows(processed_rows)
                    rows_exported += len(processed_rows)
                    logger.info(
                        f"{table_name} (selective) | Exported rows: {rows_exported}"
                    )

        # Report requested TDMX_IDs that returned no rows at all.
        missed_docs = [t for t in tdmx_ids if t not in matched_tdmx]

        if missed_docs:
            miss_file = os.path.join(
                EXPORT_FOLDER,
                f"{table_name}_SELECTIVE_MISSED_{timestamp}.csv"
            )
            with open(miss_file, "w", newline="", encoding="utf-8-sig") as mf:
                mw = csv.writer(mf)
                mw.writerow(["TDMX_ID"])
                for t in sorted(missed_docs):
                    mw.writerow([t])
            logger.warning(
                f"{len(missed_docs)} requested TDMX_ID(s) had no DB match "
                f"→ {miss_file}"
            )
            print(f"NOT MATCHED: {len(missed_docs)} TDMX_ID(s) (see {miss_file})")

        logger.info(
            f"SUCCESS | {table_name} (selective) | "
            f"Requested TDMX_IDs: {len(tdmx_ids)} | Exported rows: {rows_exported}"
        )
        print(f"SELECTIVE CSV CREATED: {csv_file}  (rows: {rows_exported})")

    except Exception as e:
        logger.exception(f"FAILED | {table_name} (selective) | {str(e)}")


# ======================================================
# SELECTIVE ENTRY (call this when you want a selective run)
# ======================================================

def run_selective():
    """
    Standalone selective run: connects, loads lookup tables, then exports
    only the objects listed in the Excel report. Does NOT run the full
    export. Call this instead of main() when you want a selective fetch.
    """
    logger.info("===================================")
    logger.info("SELECTIVE EXPORT PROCESS STARTED")
    logger.info("===================================")

    try:
        conn = get_connection()

        lookup_cache = {}
        for column_name, config in LOOKUP_CONFIG.items():
            lookup_cache[column_name] = load_lookup_table(
                conn, config["table"], config["key"], config["value"]
            )

        export_table_selective(conn, lookup_cache)

        conn.close()
        logger.info("Database connection closed")

    except Exception as e:
        logger.exception(f"FATAL ERROR (selective) | {str(e)}")

    logger.info("===================================")
    logger.info("SELECTIVE EXPORT PROCESS COMPLETED")
    logger.info("===================================")


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

    import sys

    # DEFAULT behavior: SELECTIVE export (reads the CSV, fetches only the
    # listed TDMX_ID + REVISION documents).
    #     python dbMergeAttrFetch.py
    #
    # To run the FULL DB export instead, pass "full":
    #     python dbMergeAttrFetch.py full
    if len(sys.argv) > 1 and sys.argv[1].lower() in ("full", "all", "main"):
        main()
    else:
        run_selective()