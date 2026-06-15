from platform import node

import requests
import os
from vault import get_file
from utils import sanitize
from metadata import get_type, build_metadata
from config import FORCE_METADATA_UPDATE

from logger import (
    log,
    increment_processed,
    get_processed_count
)

FAILED_FILE = "failed_files.txt"
# =========================================================
# Recursive Processor
# =========================================================

def process(node, sp, parent):

    node_type = get_type(node)

    # =====================================================
    # FOLDER
    # =====================================================

    if node_type == "FOLDER":

        cad_identifier = str(node.get("TDMX_CAD_IDENTIFIER") or "").strip()

        description = str(node.get("Description") or "").strip()

        folder_name = " - ".join(
            [
                x for x in [
                    cad_identifier,
                    description
                ]
                if x
            ]
        )

        folder_name = sanitize(
            folder_name
        )

        current_path = (
            f"{parent}/{folder_name}"
            if parent else folder_name
        )

        log("\n===================================")
        log("📁 FOLDER")
        log("Creating:", current_path)
        log("===================================")

        # =================================================
        # Create Folder
        # =================================================

        sp.ensure_path(current_path)

        # =================================================
        # Get SharePoint Folder Item
        # =================================================

        folder_res = requests.get(
            f"https://graph.microsoft.com/v1.0/drives/{sp.drive_id}/root:/{current_path}",
            headers=sp.get_headers()
        )

        if folder_res.status_code == 200:

            folder_item = folder_res.json()

            folder_id = folder_item["id"]

            # =============================================
            # Apply Folder Metadata
            # =============================================

            metadata = build_metadata(
                node,
                "FOLDER"
            )

            if metadata:

                log("📝 Applying Folder Metadata")

                sp.metadata(
                    folder_id,
                    metadata
                )

                log("✅ Folder Metadata Applied")

        else:

            log("❌ Failed to fetch folder")
            log(folder_res.text)

        # =================================================
        # Recursive Children
        # =================================================

        children = (
            node.get("Children")
            or node.get("children")
            or []
        )

        for child in children:

            process(
                child,
                sp,
                current_path
            )

    # =====================================================
    # FILE
    # =====================================================

    elif node_type == "FILE":

        log("\n----------------------------------")
        log("📄 FILE DETECTED")
        log("----------------------------------")

        log("Description:", node.get("Description"))
        log("FILE_NAME:", node.get("FILE_NAME"))
        log("CAD_REF_FILE_NAME:", node.get("CAD_REF_FILE_NAME"))
        log("Path:", node.get("Path"))

        # =================================================
        # Get vault file
        # =================================================

        local_file = get_file(node)

        if not local_file:

            log("❌ File not found in vault")
            # Count this as processed (handled) even though it failed,
            # so progress count reflects every file node we visited.
            count = increment_processed()
            log(f"📈 Progress: {count} files processed so far")
            return

        # =================================================
        # Upload Name + Path Logic
        #
        # SmarTeam now PRECOMPUTES the upload filename and the
        # previous-revision decision. GraphAPI reads "UploadPath"
        # (project-relative, e.g. "<Project>/<folder>/.../<file>")
        # and reuses ITS TAIL — the final filename and the
        # previous_revision flag — instead of recomputing CAD-ref
        # vs FILE_NAME and the revision branch on the fly.
        #
        # The folder is still anchored on GraphAPI's own `parent`
        # base (GraphAPI/<project tree>) so the two path bases stay
        # consistent regardless of how SmarTeam names its root.
        #
        # Falls back to the legacy computation when UploadPath is
        # absent (older CSV/JSON files still work).
        # =================================================

        original_name = node.get("FILE_NAME")
        cad_ref_name = node.get("CAD_REF_FILE_NAME")
        precomputed_upload = (node.get("UploadPath") or "").strip()

        if precomputed_upload:

            # ---- BLIND PATH: trust SmarTeam's computation ----
            normalized = precomputed_upload.replace("\\", "/")

            # Final upload filename = last path segment
            upload_name = normalized.rsplit("/", 1)[-1]

            # Previous-revision decision = presence of the marker folder
            is_previous_revision = (
                "/previous_revision/" in normalized.lower()
            )

            log("\n🚀 Upload Details (from SmarTeam UploadPath)")
            log("UploadPath:", precomputed_upload)
            log("Final Upload Name:", upload_name)

        else:

            # ---- FALLBACK: legacy on-the-fly computation ----
            json_path = (node.get("Path", "") or "").lower()

            is_previous_revision = (
                "previous_revision" in json_path
            )

            if is_previous_revision:
                upload_name = original_name
            else:
                upload_name = cad_ref_name or original_name

            log("\n🚀 Upload Details (computed)")
            log("Original Name:", original_name)
            log("CAD Ref Name:", cad_ref_name)
            log("Final Upload Name:", upload_name)

        # =================================================
        # Target Folder (anchored on GraphAPI parent base)
        # =================================================

        target_folder = parent

        if is_previous_revision:

            target_folder = (
                f"{parent}/Previous_Revision"
            )

            log("\n📂 Creating Previous_Revision Folder")

            sp.ensure_path(
                target_folder
            )

        # =================================================
        # Final Upload Path
        # =================================================

        full_sharepoint_path = (
            f"{target_folder}/{upload_name}"
        )

        log("\n☁️ SharePoint Upload Path:")
        log(full_sharepoint_path)

        # =================================================
        # CHECKPOINT SKIP
        # =================================================

        already_processed = False

        if is_processed(full_sharepoint_path):

            log(
                "⏭️ Already Processed:",
                full_sharepoint_path
            )

            already_processed = True

        # =================================================
        # SHAREPOINT EXISTENCE CHECK
        # =================================================

        if sp.file_exists(full_sharepoint_path):

            if FORCE_METADATA_UPDATE:

                item = sp.get_item(full_sharepoint_path)

                if not item:

                    log_failed(
                        full_sharepoint_path,
                        "Unable to get SharePoint item"
                    )

                else:

                    metadata = build_metadata(
                        node,
                        "FILE"
                    )

                    sp.metadata(
                        item["id"],
                        metadata
                    )
                log(
                    "✅ Metadata Force Updated"
                )
            else :
                log(
                    "⏭️ Already Exists in SharePoint:",
                    full_sharepoint_path
                )

            #mark_processed(full_sharepoint_path)
            already_processed = True

        # =================================================
        # Upload File
        # =================================================
        if not already_processed:
            uploaded = sp.upload(
                local_file,
                full_sharepoint_path
            )

            if uploaded is None:

                log_failed(
                    full_sharepoint_path,
                    "Upload returned None"
                )
                # Still counts as a handled file node
                count = increment_processed()
                log(f"📈 Progress: {count} files processed so far")
                return

            if not uploaded["success"]:

                log("❌ Upload failed")
                log_failed(
                    full_sharepoint_path,
                    uploaded["error"]
                )
                count = increment_processed()
                log(f"📈 Progress: {count} files processed so far")
                return

        if not already_processed:

            log("✅ Upload Success")

            file_id = uploaded["data"]["id"]

            # =================================================
            # Apply File Metadata
            # =================================================

            metadata = build_metadata(
                node,
                "FILE"
            )

            if metadata:

                log("📝 Applying File Metadata")

                sp.metadata(
                    file_id,
                    metadata
                )

                log("✅ File Metadata Applied")

            mark_processed(
                full_sharepoint_path
            )

        # =================================================
        # PROGRESS — single line, every file completion
        # =================================================

        count = increment_processed()
        log(f"📈 Progress: {count} files processed so far")

        log("----------------------------------")
        # =================================================
        # PROCESS CHILDREN OF FILE
        # =================================================

        children = (
            node.get("Children")
            or node.get("children")
            or []
        )

        for child in children:

            process(
                child,
                sp,
                parent
            )
#------------------------------------------------
# Add Checkpoint
#------------------------------------------------

CHECKPOINT_FILE = "processed_files.txt"

def is_processed(path):

    if not os.path.exists(CHECKPOINT_FILE):
        return False

    with open(
        CHECKPOINT_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        processed = {
            line.strip()
            for line in f
        }

    return path in processed

#---------------------------------------
# Failed Logs
#---------------------------------------

def mark_processed(path):

    with open(
        CHECKPOINT_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(path + "\n")

def log_failed(path, error):

    with open(
        FAILED_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            f"{path} | {error}\n"
        )
