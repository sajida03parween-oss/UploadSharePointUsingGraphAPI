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
        self.session = requests.Session()
        self.path_cache = {}
        self.file_cache = {}
        import threading
        self._cache_lock = threading.Lock()
        self._ensure_lock = threading.Lock()

    def get_headers(self):

        token = get_token()

        return {
            "Authorization": f"Bearer {token}"
        }

    # =====================================================
    # FILE EXISTS CHECK
    # =====================================================

    def file_exists(self, sp_path):
    
        if sp_path in self.file_cache:
            return True

        res = self.session.get(
             f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root:/{sp_path}",
            headers=self.get_headers()
        )

        if res.status_code == 200:
            self.file_cache[sp_path] = True
            return True

        return False

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

        if path in self.path_cache:
            return self.path_cache[path]

        # Serialize folder creation: concurrent uploads often target the
        # same parent folder; without this, two threads could both try to
        # create it. The cache check above is the fast path (no lock) for
        # already-known folders; only first-time creation takes the lock.
        with self._ensure_lock:
            # Re-check inside the lock (another thread may have just made it)
            if path in self.path_cache:
                return self.path_cache[path]

            parts = [p for p in path.split("/") if p]
            current = ""
            last_item = None
            for p in parts:

                current = f"{current}/{p}" if current else p
                if current in self.path_cache:
                    last_item = self.path_cache[current]
                    continue

                res = self.session.get(
                    f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root:/{current}",
                    headers=self.get_headers()
                )

                if res.status_code == 200:
                    last_item = res.json()
                    self.path_cache[current] = last_item
                    continue

                if res.status_code == 404:
                    parent = "/".join(
                        current.split("/")[:-1]
                    )

                    create_res = self.session.post(
                        f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root:/{parent}:/children",
                        headers={
                            **self.get_headers(),
                            "Content-Type": "application/json"
                        },
                        json={
                            "name": p,
                            "folder": {},
                            "@microsoft.graph.conflictBehavior": "replace"
                        }
                    )

                    if create_res.status_code not in [200, 201]:
                        raise Exception(
                            f"Folder create failed: "
                            f"{create_res.status_code} "
                            f"{create_res.text}"
                        )

                    last_item = create_res.json()
                    self.path_cache[current] = last_item
                    continue

                raise Exception(
                    f"Unexpected Graph response "
                    f"{res.status_code}: {res.text}"
                )

            return last_item

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

        import time

        try:

            for attempt in range(1, 4):

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

                if res.status_code in [200, 201]:
                    log("✅ Upload Success")
                    return {
                        "success": True,
                        "data": res.json()
                    }

                # Throttled or transient server error → wait + retry
                if (res.status_code == 429 or res.status_code >= 500) and attempt < 3:
                    try:
                        wait = int(res.headers.get("Retry-After", 10))
                    except (ValueError, TypeError):
                        wait = 10
                    log(f"🔁 Upload throttled/transient {res.status_code} — "
                        f"retry {attempt}/3 after {wait}s...")
                    time.sleep(wait)
                    continue

                # Non-retryable failure
                log("❌ Upload failed:")
                log(res.text)
                return {
                    "success": False,
                    "error": res.text
                }

            # Exhausted retries
            return {
                "success": False,
                "error": f"Upload failed after retries (HTTP {res.status_code})"
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
                        chunk_res = None

                    # ============================================
                    # WAIT BEFORE RETRY
                    # Honor Retry-After when present (throttling); else
                    # use a shorter backoff than the old fixed 180s.
                    # ============================================

                    if attempt < 2:
                        wait = 30
                        try:
                            if chunk_res is not None:
                                wait = int(chunk_res.headers.get("Retry-After", 30))
                        except (ValueError, TypeError):
                            wait = 30
                        log(f"⏳ Waiting {wait}s before chunk retry...")
                        time.sleep(wait)

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

    def metadata(self, item_id, data, retries=3, retry_wait=5):
        """
        Apply list-item metadata via PATCH.

        Returns a result dict so callers can detect failure:
            {"success": True,  "status": <code>}
            {"success": False, "status": <code|0>, "error": "<text>"}

        Retries on transient failures (e.g. 429/503/5xx) up to `retries`
        attempts, waiting `retry_wait` seconds between tries.
        """
        import time

        last_status = 0
        last_error = ""

        for attempt in range(1, retries + 1):

            try:
                res = requests.patch(
                    f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/items/{item_id}/listItem/fields",
                    headers={
                       **self.get_headers(),
                        "Content-Type": "application/json"
                    },
                    json=data,
                    timeout=120
                )
            except Exception as e:
                last_status = 0
                last_error = f"PATCH exception: {e}"
                log(f"⚠️ Metadata attempt {attempt}/{retries} exception: {e}")
                if attempt < retries:
                    log(f"⏳ Waiting {retry_wait}s before metadata retry...")
                    time.sleep(retry_wait)
                continue

            last_status = res.status_code
            log("Metadata:", res.status_code)

            if res.status_code in [200, 201]:
                return {"success": True, "status": res.status_code}

            # Non-success — capture body, decide whether to retry
            last_error = res.text
            log(res.text)

            # Retry on transient/server errors; give up immediately on
            # clear client errors (4xx other than 429 throttling).
            transient = (
                res.status_code == 429
                or res.status_code >= 500
            )

            if transient and attempt < retries:
                # Honor Retry-After when SharePoint sends it (throttling)
                try:
                    wait = int(res.headers.get("Retry-After", retry_wait))
                except (ValueError, TypeError):
                    wait = retry_wait
                log(f"🔁 Metadata transient {res.status_code} — retry "
                    f"{attempt}/{retries} after {wait}s...")
                time.sleep(wait)
                continue

            # Non-transient, or out of retries
            break

        return {
            "success": False,
            "status": last_status,
            "error": last_error or f"HTTP {last_status}"
        }

#------------------------------------------------
# Get Path
#------------------------------------------------
    def get_item(self, sp_path):
    
        if sp_path in self.path_cache:
            return self.path_cache[sp_path]

        res = self.session.get(
            f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root:/{sp_path}",
            headers=self.get_headers()
        )

        if res.status_code == 200:
            item = res.json()
            self.path_cache[sp_path] = item
            return item

        log("❌ Get Item Failed")
        log(sp_path)
        log(res.text)

        return None
