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