import os
import requests
import msal
from dotenv import load_dotenv

load_dotenv()

# =========================================================
# ENV VARIABLES
# =========================================================
TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
THUMBPRINT = os.getenv("THUMBPRINT")
CERT_PATH = os.getenv("CERT_PATH")
SITE_HOST = os.getenv("SITE_HOST")
SITE_PATH = os.getenv("SITE_PATH")

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

# =========================================================
# READ CERTIFICATE
# =========================================================
with open(CERT_PATH, "r") as f:
    private_key = f.read()

# =========================================================
# AUTHENTICATION
# =========================================================
app = msal.ConfidentialClientApplication(
    CLIENT_ID,
    authority=AUTHORITY,
    client_credential={
        "thumbprint": THUMBPRINT,
        "private_key": private_key,
    }
)

token = app.acquire_token_for_client(
    scopes=["https://graph.microsoft.com/.default"]
)

if "access_token" not in token:
    print("❌ Authentication Failed")
    print(token)
    exit()

access_token = token["access_token"]

headers = {
    "Authorization": f"Bearer {access_token}"
}

print("✅ Authentication Successful")

# =========================================================
# STEP 1 : GET SITE ID
# =========================================================
site_url = f"https://graph.microsoft.com/v1.0/sites/{SITE_HOST}:{SITE_PATH}"

site_res = requests.get(site_url, headers=headers)
site_data = site_res.json()

if "id" not in site_data:
    print("❌ Site not found")
    print(site_data)
    exit()

site_id = site_data["id"]

print(f"✅ Site ID : {site_id}")

# =========================================================
# STEP 2 : GET ALL DRIVES
# =========================================================
drives_res = requests.get(
    f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
    headers=headers
)

drives_data = drives_res.json()

# =========================================================
# STEP 3 : FIND ARCHIVAL DRIVE
# =========================================================
drive_id = None

for drive in drives_data["value"]:
    print(f"📂 Found Library : {drive['name']}")

    if drive["name"] == "Archival":
        drive_id = drive["id"]

if not drive_id:
    print("❌ Archival library not found")
    exit()

print(f"✅ Archival Drive ID : {drive_id}")

# =========================================================
# STEP 4 : CREATE FOLDER
# =========================================================
folder_data = {
    "name": "GraphAPITestAttribute",
    "folder": {},
    "@microsoft.graph.conflictBehavior": "rename"
}

create_res = requests.post(
    f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children",
    headers={
        **headers,
        "Content-Type": "application/json"
    },
    json=folder_data
)

print("\n=================================================")
print("📁 CREATE FOLDER RESPONSE")
print("=================================================")
print("Status Code :", create_res.status_code)

if create_res.status_code not in [200, 201]:
    print("❌ Folder creation failed")
    print(create_res.text)
    exit()

create_data = create_res.json()

folder_id = create_data["id"]

print(f"✅ Folder Created : {create_data['name']}")
print(f"🌐 Folder URL     : {create_data['webUrl']}")
print(f"🆔 Folder ID      : {folder_id}")

# =========================================================
# STEP 5 : GET LIST ITEM
# =========================================================
item_res = requests.get(
    f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{folder_id}/listItem",
    headers=headers
)

item_data = item_res.json()

print("\n=================================================")
print("📋 LIST ITEM DETAILS")
print("=================================================")

list_item_id = item_data["id"]

print(f"✅ List Item ID : {list_item_id}")

# =========================================================
# STEP 6 : GET ALL COLUMNS
# =========================================================
list_id = create_data["parentReference"]["sharepointIds"]["listId"]

columns_res = requests.get(
    f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/columns",
    headers=headers
)

columns_data = columns_res.json()

print("\n=================================================")
print("📑 SHAREPOINT COLUMNS")
print("=================================================")

for col in columns_data["value"]:
    print(f"Display Name : {col.get('displayName')}")
    print(f"Internal Name: {col.get('name')}")
    print("------------------------------------------------")

# =========================================================
# STEP 7 : UPDATE METADATA
# IMPORTANT:
# Replace internal names below with actual values
# printed from STEP 6
# =========================================================
metadata = {
    # Replace these with ACTUAL internal names
    # after checking console output

    "_x0033_DX_Title": "FLEET 1 and FLEET 2",
    "Revision": "A",
    "State": "Released",
    "_ExtendedDescription": "updated from graphapi"
}

update_res = requests.patch(
    f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{folder_id}/listItem/fields",
    headers={
        **headers,
        "Content-Type": "application/json"
    },
    json=metadata
)

print("\n=================================================")
print("✏️ METADATA UPDATE RESPONSE")
print("=================================================")

print("Status Code :", update_res.status_code)

if update_res.status_code in [200, 201]:
    print("✅ Metadata updated successfully")
else:
    print("❌ Metadata update failed")

print(update_res.text)

# ====== CONFIG ======
file_path = r"D:\Package\Data_Samples_File System CATIA - Fundamental_Training\CATIA_Data\myAssembly_1.CATProduct"   # local file
file_name = os.path.basename(file_path)
target_folder = "GraphAPITestAttribute"  # your folder in Archival

# ====== UPLOAD (simple upload, <= 4 MB) ======
#upload_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{target_folder}/{file_name}:/content"
""" with open(file_path, "rb") as f:
    upload_res = requests.put(
        upload_url,
        headers={"Authorization": f"Bearer {access_token}"},
        data=f
    )

print("Upload:", upload_res.status_code, upload_res.text)

if upload_res.status_code not in [200, 201]:
    raise Exception("Upload failed")

file_item = upload_res.json()
file_id = file_item["id"]  # Graph Drive Item ID """


# Create upload session for large data
session_res = requests.post(
    f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{target_folder}/{file_name}:/createUploadSession",
    headers={**headers, "Content-Type": "application/json"},
    json={"item": {"@microsoft.graph.conflictBehavior": "rename"}}
)

upload_url = session_res.json()["uploadUrl"]

# Upload in chunks (example: whole file at once if small enough)
with open(file_path, "rb") as f:
    data = f.read()

chunk_res = requests.put(
    upload_url,
    headers={
        "Content-Length": str(len(data)),
        "Content-Range": f"bytes 0-{len(data)-1}/{len(data)}"
    },
    data=data
)

print("Chunk upload:", chunk_res.status_code)
file_id = chunk_res.json()["id"]

print("Uploaded file_id:", file_id)

metadata = {
    "Title": "A340 Structure File",
    "_x0033_DX_Title": "Wing Assembly",   # example – use your real internal name
    "Revision": "A",
    "_ExtendedDescription": "Major"
}

update_res = requests.patch(
    f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{file_id}/listItem/fields",
    headers={**headers, "Content-Type": "application/json"},
    json=metadata
)

print("Metadata:", update_res.status_code, update_res.text)