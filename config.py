import os
from dotenv import load_dotenv

load_dotenv()

TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
THUMBPRINT = os.getenv("THUMBPRINT")
CERT_PATH = os.getenv("CERT_PATH")

SITE_HOST = os.getenv("SITE_HOST")
SITE_PATH = os.getenv("SITE_PATH")
LIBRARY_NAME = os.getenv("LIBRARY_NAME")

PROJECT_FOLDER = os.getenv("PROJECT_FOLDER") 
DOCUMENT_FOLDER = os.getenv("DOCUMENT_FOLDER")

# Folder where Documents_Tree_<TDMX_ID>.csv files are stored.
# Defaults to DOCUMENT_FOLDER if not set separately.
DOCUMENT_CSV_FOLDER = os.getenv("DOCUMENT_CSV_FOLDER") or DOCUMENT_FOLDER

OLD_ROOT = os.getenv("OLD_ROOT")
NEW_ROOT = os.getenv("NEW_ROOT")

FORCE_METADATA_UPDATE = True

# Number of concurrent file uploads in Pass 2. I/O-bound work, so more
# workers = more throughput until SharePoint starts throttling (429).
# Start ~8; raise if few 429s appear, lower if many. Set in .env.
try:
    UPLOAD_WORKERS = int(os.getenv("UPLOAD_WORKERS", "8"))
except (ValueError, TypeError):
    UPLOAD_WORKERS = 8
if UPLOAD_WORKERS < 1:
    UPLOAD_WORKERS = 1

# Skip the per-file SharePoint existence check (file_exists GET) before
# uploading. Safe ONLY for a FRESH upload into an empty destination,
# where every file is new — it removes one round-trip per file.
# Leave OFF (default) for resume/re-runs, where files may already exist
# and the check prevents needless re-uploads.
#   SKIP_EXISTENCE_CHECK=true  -> fresh-run fast path
SKIP_EXISTENCE_CHECK = str(
    os.getenv("SKIP_EXISTENCE_CHECK", "false")
).strip().lower() in ("1", "true", "yes", "on")