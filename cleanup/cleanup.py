import sys
from pathlib import Path
import requests
from dotenv import load_dotenv

# Project root
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

load_dotenv(ROOT_DIR / ".env")

from auth import get_token
from config import SITE_HOST, SITE_PATH, LIBRARY_NAME

EXPECTED_ITEMS = {
    "ARCHIVES",
    "753120044 FLOOR PANEL REWORKED",
    "8. CONTINUED AIRWORTHINESS",
    "7. PROJECT MANAGEMENT",
    "6. PRE-SALES",
    "4. AIRWORTHINESS INSTRUCTIONS",
    "3. SUBSTANTIATION",
    "5. ENGINEERING",
    "2. DEFINITION",
    "1. CHANGE APPROVAL SHEET",
}


def get_site_id(token):
    headers = {"Authorization": f"Bearer {token}"}

    url = f"https://graph.microsoft.com/v1.0/sites/{SITE_HOST}:{SITE_PATH}"

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    return response.json()["id"]


def get_drive_id(token, site_id):
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
        headers=headers
    )
    response.raise_for_status()

    for drive in response.json()["value"]:
        if drive["name"].lower() == LIBRARY_NAME.lower():
            return drive["id"]

    raise Exception(f"Library '{LIBRARY_NAME}' not found")


def cleanup_project(project_name):
    token = get_token()

    site_id = get_site_id(token)
    drive_id = get_drive_id(token, site_id)

    headers = {"Authorization": f"Bearer {token}"}

    folder_path = f"GraphAPI/{project_name}"

    url = (
        f"https://graph.microsoft.com/v1.0/drives/"
        f"{drive_id}/root:/{folder_path}:/children"
    )

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    items = response.json()["value"]

    expected_upper = {x.upper() for x in EXPECTED_ITEMS}

    print(f"\nScanning {folder_path}\n")

    for item in items:
        name = item["name"]

        if name.upper() in expected_upper:
            print(f"KEEP   : {name}")
            continue

        print(f"DELETE : {name}")

        delete_url = (
            f"https://graph.microsoft.com/v1.0/drives/"
            f"{drive_id}/items/{item['id']}"
        )

        delete_response = requests.delete(
            delete_url,
            headers=headers
        )

        if delete_response.status_code in (200, 204):
            print(f"Deleted: {name}")
        else:
            print(
                f"Failed: {name}\n"
                f"{delete_response.status_code}\n"
                f"{delete_response.text}"
            )


if __name__ == "__main__":
    project_name = "B773  - RECONFIGURATION 8P TO 42J"
    cleanup_project(project_name)