from email.quoprimime import quote
import os
import token
import requests
from requests.compat import quote
from auth import get_token
from config import (
    SITE_HOST,
    SITE_PATH,
    LIBRARY_NAME
)
from logger import log


class SharePoint:

    def __init__(self):
        self.drive_id = None

    def get_headers(self):

        token = get_token()

        return {
            "Authorization": f"Bearer {token}"
        }

    # =====================================================
    # FILE EXISTS CHECK
    # =====================================================

    def file_exists(self, sp_path):
        encoded_path = quote(sp_path)
        res = requests.get(
            f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root:/{sp_path}",
            headers=self.get_headers()
        )

        return res.status_code == 200

    # =====================================================
    # INIT
    # =====================================================

    def init(self):

        site = requests.get(
            f"https://graph.microsoft.com/v1.0/sites/{SITE_HOST}:{SITE_PATH}",
            headers=self.get_headers()
        ).json()

        site_id = site["id"]

        drives = requests.get(
            f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
            headers=self.get_headers()
        ).json()

        log("\n📂 Libraries:")

        for d in drives["value"]:

            log(" -", d["name"])

            if d["name"].lower() == LIBRARY_NAME.lower():

                self.drive_id = d["id"]

        if not self.drive_id:

            raise Exception("Archival not found")

        log("✅ Drive ID:", self.drive_id)

    # =====================================================
    # ENSURE PATH
    # =====================================================

    def ensure_path(self, path):

        parts = path.split("/")

        current = ""

        for p in parts:

            current = (
                f"{current}/{p}"
                if current else p
            )

            res = requests.get(
                f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root:/{current}",
                headers=self.get_headers()
            )

            if res.status_code == 404:

                parent = "/".join(
                    current.split("/")[:-1]
                )

                create_res = requests.post(
                    f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root:/{parent}:/children",
                    headers={
                        **self.get_headers(),
                        "Content-Type": "application/json"
                    },
                    json={
                        "name": p,
                        "folder": {}
                    }
                )

                if create_res.status_code not in [200, 201]:

                    log("❌ Folder create failed")
                    log(create_res.text)

    # =====================================================
    # MAIN UPLOAD ROUTER
    # =====================================================

    def upload(self, local_path, sp_path):

        file_size = os.path.getsize(local_path)

        log("\n📦 File Size:", file_size)

        # =================================================
        # SMALL FILE
        # =================================================

        if file_size < 4 * 1024 * 1024:

            return self.simple_upload(
                local_path,
                sp_path
            )

        # =================================================
        # LARGE FILE
        # =================================================

        return self.large_upload(
            local_path,
            sp_path
        )

    # =====================================================
    # SIMPLE UPLOAD
    # =====================================================

    def simple_upload(
        self,
        local_path,
        sp_path
    ):

        log("\n🚀 SIMPLE FILE UPLOAD")

        url = (
            f"https://graph.microsoft.com/v1.0/"
            f"drives/{self.drive_id}/root:/{sp_path}:/content"
        )

        log("\n☁️ Upload URL:")
        log(url)

        log("\n📄 Local File:")
        log(local_path)

        try:

            with open(local_path, "rb") as f:

                res = requests.put(
                    url,
                    headers={
                       **self.get_headers() ,
                        "Content-Type": "application/octet-stream"
                    },
                    data=f,
                    timeout=300
                )

            log("📡 Upload Status:", res.status_code)

            if res.status_code not in [200, 201]:

                log("❌ Upload failed:")
                log(res.text)

                return {
                    "success": False,
                    "error": res.text
                }

            log("✅ Upload Success")

            return {
                "success": True,
                "data": res.json()
            }

        except Exception as e:

            log("❌ Upload Exception:")
            log(str(e))

            return {
                "success": False,
                "error": str(e)
            }

    # =====================================================
    # LARGE FILE UPLOAD SESSION
    # =====================================================

    def large_upload(
        self,
        local_path,
        sp_path
    ):

        log("\n🚀 LARGE FILE UPLOAD")

        # =================================================
        # CREATE SESSION
        # =================================================

        session_url = (
            f"https://graph.microsoft.com/v1.0/"
            f"drives/{self.drive_id}/root:/{sp_path}:/createUploadSession"
        )

        session_res = requests.post(
            session_url,
            headers={
                **self.get_headers(),
                "Content-Type": "application/json"
            },
            json={}
        )

        log(
            "📡 Session Status:",
            session_res.status_code
        )

        if session_res.status_code not in [200, 201]:

            log("❌ Failed to create upload session")
            log(session_res.text)

            return {
                "success": False,
                "error": session_res.text
            }

        upload_url = session_res.json()["uploadUrl"]

        log("✅ Upload Session Created")

        # =================================================
        # CHUNK SETTINGS
        # =================================================

        chunk_size = 10 * 1024 * 1024  # 10 MB

        file_size = os.path.getsize(local_path)

        uploaded = 0

        # =================================================
        # START CHUNK UPLOAD
        # =================================================

        with open(local_path, "rb") as f:

            while uploaded < file_size:

                chunk_data = f.read(chunk_size)

                start = uploaded

                end = uploaded + len(chunk_data) - 1

                headers = {
                    "Content-Length": str(len(chunk_data)),
                    "Content-Range": (
                        f"bytes {start}-{end}/{file_size}"
                    )
                }

                log(
                    f"⬆️ Uploading Chunk:"
                    f" {start} - {end}"
                )

                import time

                success = False

                for attempt in range(3):

                    try:

                        log(
                        f"🔁 Chunk Retry Attempt: {attempt + 1}"
                        )

                        chunk_res = requests.put(
                            upload_url,
                            headers=headers,
                            data=chunk_data,
                            timeout=300
                        )

                        log(
                            "📡 Chunk Status:",
                            chunk_res.status_code
                        )

                        if chunk_res.status_code in [200, 201, 202]:
                            success = True
                            break
                        else:
                            log(chunk_res.text)

                    except Exception as e:
                        log("⚠️ Chunk Upload Error:")
                        log(str(e))

                    # ============================================
                    # WAIT BEFORE RETRY
                    # ============================================

                    if attempt < 2:

                        log(
                            "⏳ Waiting 180 seconds before retry..."
                        )

                        time.sleep(180)

                # ================================================
                # FINAL FAILURE
                # ================================================

                if not success:
                    log("❌ Chunk upload failed permanently")
                    return {
                        "success": False,
                        "error": "❌ Chunk upload failed permanently"
                    }

                log(
                    "📡 Chunk Status:",
                    chunk_res.status_code
                )

                if chunk_res.status_code not in [200, 201, 202]:

                    log("❌ Chunk upload failed")
                    log(chunk_res.text)

                    return {
                        "success": False,
                        "error": chunk_res.text
                    }

                uploaded += len(chunk_data)

        log("✅ Large Upload Complete")

        return {
            "success": True,
            "data": chunk_res.json()
        }

    # =====================================================
    # METADATA
    # =====================================================

    def metadata(self, item_id, data):

        res = requests.patch(
            f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/items/{item_id}/listItem/fields",
            headers={
               **self.get_headers(),
                "Content-Type": "application/json"
            },
            json=data
        )

        log("Metadata:", res.status_code)

        if res.status_code not in [200, 201]:

            log(res.text)

#------------------------------------------------
# Get Path
#------------------------------------------------
    def get_item(self, sp_path):
        encoded_path = quote(sp_path)
        res = requests.get(
            f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root:/{sp_path}",
            headers=self.get_headers()
        )

        if res.status_code == 200:
            return res.json()
        log("❌ Get Item Failed")
        log(sp_path)
        log(res.text)
        return None
