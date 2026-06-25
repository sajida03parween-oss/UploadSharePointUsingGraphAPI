from platform import node

import requests
import os
import csv
from vault import get_file
from utils import sanitize
from metadata import get_type, build_metadata
from config import FORCE_METADATA_UPDATE, SKIP_EXISTENCE_CHECK

from logger import (
    log,
    increment_processed,
    get_processed_count,
    log_failed,
    log_processed,
    log_duplicate,
)

# Folder-name problems are also recorded in the per-project failed CSV,
# but we keep a simple flat list too for quick scanning.
INVALID_FOLDER_FILE = "invalid_folders.txt"

# =========================================================
# Resume support
#
# When the orchestrator runs with --resume, it loads the set of
# SharePoint paths already completed by previous runs and calls
# set_resume_done(...). process() then skips any file whose final
# path is in this set, with no network call.
# =========================================================

_RESUME_DONE = set()


def set_resume_done(done_paths):
    """Install the set of already-completed SharePoint paths (resume)."""
    global _RESUME_DONE
    _RESUME_DONE = done_paths or set()

# =========================================================
# Duplicate handling
#
# Two file rows are "the same upload" when they resolve to the
# SAME final SharePoint path (folder + final filename). The first
# one uploads; any later row with an identical path is SKIPPED and
# recorded in DUPLICATES_FILE with its full details.
#
# Same file in a DIFFERENT folder, or a DIFFERENT revision, produces
# a different path and is therefore NOT a duplicate — it still uploads.
# =========================================================

# In-memory set of upload paths already seen THIS run (case-insensitive)
_seen_upload_paths = set()


def is_duplicate_upload(upload_path):
    """
    True if this upload path was already handled this run.
    Registers the path as seen when it is new (returns False then).
    """
    key = (upload_path or "").strip().lower()
    if not key:
        return False
    if key in _seen_upload_paths:
        return True
    _seen_upload_paths.add(key)
    return False


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

        # ==========================================
        # INVALID FOLDER CHECK
        # ==========================================

        if not folder_name:
            log_invalid_folder(node)
            log_failed(
                node,
                stage="FOLDER_NAMING",
                reason=f"Empty folder name (CAD='{cad_identifier}', DESC='{description}')",
                node_type="FOLDER",
            )

            log(
                "\n❌ INVALID FOLDER NAME DETECTED"
            )
            log(
                f"CAD_IDENTIFIER: {cad_identifier}"
            )
            log(
                f"DESCRIPTION: {description}"
            )

            folder_name = (
                node.get("TDMX_ID")
                or "INVALID_FOLDER"
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

        folder_status = "Success"
        folder_detail = ""

        # try:
        #     sp.ensure_path(current_path)
        # except Exception as e:
        #     folder_status = "Failure"
        #     folder_detail = f"ensure_path error: {e}"
        #     log("❌ Folder create error:", str(e))
        #     log_failed(
        #         node,
        #         stage="FOLDER_CREATE",
        #         reason=str(e),
        #         node_type="FOLDER",
        #         upload_path=current_path,
        #     )

        # =================================================
        # Get SharePoint Folder Item
        # =================================================

        # try:
        #     folder_res = requests.get(
        #         f"https://graph.microsoft.com/v1.0/drives/{sp.drive_id}/root:/{current_path}",
        #         headers=sp.get_headers()
        #     )
        # except Exception as e:
        #     folder_res = None
        #     folder_status = "Failure"
        #     folder_detail = f"folder fetch error: {e}"
        #     log("❌ Folder fetch exception:", str(e))
        #     log_failed(
        #         node,
        #         stage="FOLDER_FETCH",
        #         reason=str(e),
        #         node_type="FOLDER",
        #         upload_path=current_path,
        #     )

        folder_item = None
        try:

            folder_item = sp.ensure_path(
            current_path
        )

        except Exception as e:
            folder_status = "Failure"
            folder_detail = (
                f"ensure_path error: {e}"
            )

            log(
                "❌ Folder create error:",
                str(e)
            )

            log_failed(
                node,
                stage="FOLDER_CREATE",
                reason=str(e),
                node_type="FOLDER",
                upload_path=current_path,
            )
        # if folder_res is not None and folder_res.status_code == 200:

        #     folder_item = folder_res.json()

        #     folder_id = folder_item["id"]

        #     # =============================================
        #     # Apply Folder Metadata
        #     # =============================================

        #     metadata = build_metadata(
        #         node,
        #         "FOLDER"
        #     )

        #     if metadata:

        #         log("📝 Applying Folder Metadata")

        #         try:
        #             meta_res = sp.metadata(
        #                 folder_id,
        #                 metadata
        #             )
        #             if meta_res and meta_res.get("success"):
        #                 log("✅ Folder Metadata Applied")
        #             else:
        #                 err = (meta_res or {}).get("error", "unknown metadata error")
        #                 status_code = (meta_res or {}).get("status", "")
        #                 folder_status = "Failure"
        #                 folder_detail = (
        #                     f"Folder created but metadata failed "
        #                     f"(HTTP {status_code}): {str(err)[:200]}"
        #                 )
        #                 log("❌ Folder metadata FAILED:", folder_detail)
        #                 log_failed(
        #                     node,
        #                     stage="FOLDER_METADATA",
        #                     reason=f"Metadata failed (HTTP {status_code}): {str(err)[:300]}",
        #                     node_type="FOLDER",
        #                     upload_path=current_path,
        #                 )
        #         except Exception as e:
        #             folder_status = "Failure"
        #             folder_detail = f"metadata error: {e}"
        #             log("❌ Folder metadata error:", str(e))
        #             log_failed(
        #                 node,
        #                 stage="FOLDER_METADATA",
        #                 reason=str(e),
        #                 node_type="FOLDER",
        #                 upload_path=current_path,
        #             )

        # elif folder_res is not None:

        #     folder_status = "Failure"
        #     folder_detail = f"fetch status {folder_res.status_code}"
        #     log("❌ Failed to fetch folder")
        #     log(folder_res.text)
        #     log_failed(
        #         node,
        #         stage="FOLDER_FETCH",
        #         reason=f"HTTP {folder_res.status_code}: {folder_res.text[:300]}",
        #         node_type="FOLDER",
        #         upload_path=current_path,
        #     )
        if folder_item:
    
            folder_id = folder_item["id"]

            metadata = build_metadata(
                node,
                "FOLDER"
            )

            if metadata:

                log(
                    "📝 Applying Folder Metadata"
                )

                try:

                    meta_res = sp.metadata(
                        folder_id,
                        metadata
                    )

                    if (
                        meta_res
                        and
                        meta_res.get("success")
                    ):

                        log(
                            "✅ Folder Metadata Applied"
                        )

                    else:

                        err = (
                            meta_res or {}
                        ).get(
                            "error",
                            "unknown metadata error"
                        )

                        status_code = (
                            meta_res or {}
                        ).get(
                            "status",
                            ""
                        )

                        folder_status = "Failure"

                        folder_detail = (
                            f"Folder created "
                            f"but metadata failed "
                            f"(HTTP {status_code}): "
                            f"{str(err)[:200]}"
                        )

                        log(
                            "❌ Folder metadata FAILED:",
                            folder_detail
                        )

                except Exception as e:

                    folder_status = "Failure"

                    folder_detail = (
                        f"metadata error: {e}"
                    )

                    log(
                        "❌ Folder metadata error:",
                        str(e)
                    )
        # Record the folder node in the per-project processed CSV
        if folder_status == "Success" and not folder_detail:
            folder_detail = "Folder created"
        log_processed(
            node,
            node_type="FOLDER",
            status=folder_status,
            sharepoint_path=current_path,
            detail=folder_detail,
        )

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
        # DUPLICATE SKIP (same file, same folder, same name)
        #
        # Use SmarTeam's precomputed UploadPath as the dedup key.
        # If we've already handled this exact destination this run,
        # skip BEFORE the costly vault fetch / upload, and record it
        # in duplicates.csv with full details.
        #
        # Different folder or different revision => different
        # UploadPath => NOT a duplicate => still uploaded.
        # =================================================

        dedup_key = (node.get("UploadPath") or "").strip()

        if dedup_key and is_duplicate_upload(dedup_key):

            log("\n⏭️ DUPLICATE — skipping (already handled this run):")
            log(dedup_key)

            log_duplicate(node, dedup_key)
            log_processed(
                node,
                node_type="FILE",
                status="Skipped(Duplicate)",
                sharepoint_path=dedup_key,
                detail="Same UploadPath already handled this run",
            )

            count = increment_processed()
            log(f"📈 Progress: {count} files processed so far")
            return

        # =================================================
        # Get vault file
        # =================================================

        local_file = get_file(node)

        if not local_file:

            log("❌ File not found in vault")
            log_failed(
                node,
                stage="VAULT_MISSING",
                reason="File not found in vault (ROOT_DIR_ON_SERVER + FILE_NAME)",
                node_type="FILE",
                upload_path=dedup_key,
            )
            log_processed(
                node,
                node_type="FILE",
                status="Failure",
                sharepoint_path=dedup_key,
                detail="Vault file missing",
            )
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

            try:
                sp.ensure_path(
                    target_folder
                )
            except Exception as e:
                log("❌ Previous_Revision folder ensure failed:", str(e))
                log_failed(
                    node,
                    stage="FOLDER_ENSURE",
                    reason=f"Previous_Revision ensure failed: {e}",
                    node_type="FILE",
                    upload_path=f"{target_folder}/{upload_name}",
                )
                log_processed(
                    node,
                    node_type="FILE",
                    status="Failure",
                    sharepoint_path=f"{target_folder}/{upload_name}",
                    detail=f"Previous_Revision ensure failed: {e}",
                )
                count = increment_processed()
                log(f"📈 Progress: {count} files processed so far")
                return
        else:
            # Safety net: make sure the parent folder exists before
            # uploading. Normally Pass 1 created it, but when running a
            # trimmed/leftover tree the folder row may be absent — this
            # guarantees the upload never lands in a missing folder.
            # ensure_path is cached, so for already-known folders this is
            # a no-op (no network call).
            #
            # Wrapped in try/except: a folder problem must become a normal
            # logged Failure (recorded in BOTH processed and failed CSVs),
            # NOT an exception that escapes process() and bypasses the
            # processed-CSV row. Every node must appear in processed.csv.
            try:
                sp.ensure_path(target_folder)
            except Exception as e:
                log("❌ Parent folder ensure failed:", str(e))
                log_failed(
                    node,
                    stage="FOLDER_ENSURE",
                    reason=f"Parent folder ensure failed: {e}",
                    node_type="FILE",
                    upload_path=f"{target_folder}/{upload_name}",
                )
                log_processed(
                    node,
                    node_type="FILE",
                    status="Failure",
                    sharepoint_path=f"{target_folder}/{upload_name}",
                    detail=f"Parent folder ensure failed: {e}",
                )
                count = increment_processed()
                log(f"📈 Progress: {count} files processed so far")
                return

        # =================================================
        # Final Upload Path
        # =================================================

        full_sharepoint_path = (
            f"{target_folder}/{upload_name}"
        )

        log("\n☁️ SharePoint Upload Path:")
        log(full_sharepoint_path)

        # =================================================
        # RESUME SKIP
        # If --resume loaded a set of already-done paths and THIS file's
        # final path is in it, it was uploaded (Success/Skipped) by a
        # prior run — skip with no network call. This is the main
        # time-saver after a crash.
        # =================================================

        if _RESUME_DONE and full_sharepoint_path in _RESUME_DONE:
            log("\n⏭️ RESUME — already done in a previous run, skipping:")
            log(full_sharepoint_path)
            log_processed(
                node,
                node_type="FILE",
                status="Skipped(Resume)",
                sharepoint_path=full_sharepoint_path,
                detail="Already completed in a previous run (--resume)",
            )
            count = increment_processed()
            log(f"📈 Progress: {count} files processed so far")
            return

        # =================================================
        # DUPLICATE SKIP (fallback)
        #
        # If the node had no precomputed UploadPath, the early check
        # above couldn't run. Dedup here on the computed path instead,
        # so older CSV/JSON (without UploadPath) is still de-duplicated.
        # =================================================

        if not dedup_key:

            if is_duplicate_upload(full_sharepoint_path):

                log("\n⏭️ DUPLICATE — skipping (already handled this run):")
                log(full_sharepoint_path)

                log_duplicate(node, full_sharepoint_path)
                log_processed(
                    node,
                    node_type="FILE",
                    status="Skipped(Duplicate)",
                    sharepoint_path=full_sharepoint_path,
                    detail="Same path already handled this run",
                )

                count = increment_processed()
                log(f"📈 Progress: {count} files processed so far")
                return

        # =================================================
        # Status tracking for this file
        # =================================================

        file_status = "Success"
        file_detail = ""
        already_processed = False

        # =================================================
        # SHAREPOINT EXISTENCE CHECK
        #
        # Skipped entirely when SKIP_EXISTENCE_CHECK is on (fresh upload
        # into an empty destination) — saves one GET per file. In that
        # mode every file goes straight to upload, and metadata is applied
        # from the upload response (no extra GET). Resume still protects
        # against re-doing already-uploaded files via the resume skip above.
        # =================================================

        if not SKIP_EXISTENCE_CHECK and sp.file_exists(full_sharepoint_path):

            if FORCE_METADATA_UPDATE:

                item = sp.get_item(full_sharepoint_path)

                if not item:

                    file_status = "Failure"
                    file_detail = "Unable to get SharePoint item for metadata update"
                    log_failed(
                        node,
                        stage="METADATA_GET_ITEM",
                        reason="Unable to get SharePoint item",
                        node_type="FILE",
                        upload_path=full_sharepoint_path,
                    )

                else:

                    metadata = build_metadata(
                        node,
                        "FILE"
                    )

                    try:
                        meta_res = sp.metadata(
                            item["id"],
                            metadata
                        )
                        if meta_res and meta_res.get("success"):
                            file_detail = "Metadata force-updated (already existed)"
                            log("✅ Metadata Force Updated")
                        else:
                            err = (meta_res or {}).get("error", "unknown metadata error")
                            status_code = (meta_res or {}).get("status", "")
                            file_status = "Failure"
                            file_detail = (
                                f"Already existed but metadata update failed "
                                f"(HTTP {status_code}): {str(err)[:200]}"
                            )
                            log("❌ Metadata Force Update FAILED:", file_detail)
                            log_failed(
                                node,
                                stage="METADATA_UPDATE",
                                reason=f"Metadata update failed (HTTP {status_code}): {str(err)[:300]}",
                                node_type="FILE",
                                upload_path=full_sharepoint_path,
                            )
                    except Exception as e:
                        file_status = "Failure"
                        file_detail = f"metadata update error: {e}"
                        log("❌ Metadata update error:", str(e))
                        log_failed(
                            node,
                            stage="METADATA_UPDATE",
                            reason=str(e),
                            node_type="FILE",
                            upload_path=full_sharepoint_path,
                        )
            else:
                file_detail = "Already exists in SharePoint"
                log(
                    "⏭️ Already Exists in SharePoint:",
                    full_sharepoint_path
                )

            already_processed = True

        # =================================================
        # Upload File
        # =================================================
        if not already_processed:

            try:
                uploaded = sp.upload(
                    local_file,
                    full_sharepoint_path
                )
            except Exception as e:
                log("❌ Upload exception:", str(e))
                log_failed(
                    node,
                    stage="UPLOAD",
                    reason=f"Upload exception: {e}",
                    node_type="FILE",
                    upload_path=full_sharepoint_path,
                )
                log_processed(
                    node,
                    node_type="FILE",
                    status="Failure",
                    sharepoint_path=full_sharepoint_path,
                    detail=f"Upload exception: {e}",
                )
                count = increment_processed()
                log(f"📈 Progress: {count} files processed so far")
                return

            if uploaded is None:

                log_failed(
                    node,
                    stage="UPLOAD",
                    reason="Upload returned None",
                    node_type="FILE",
                    upload_path=full_sharepoint_path,
                )
                log_processed(
                    node,
                    node_type="FILE",
                    status="Failure",
                    sharepoint_path=full_sharepoint_path,
                    detail="Upload returned None",
                )
                count = increment_processed()
                log(f"📈 Progress: {count} files processed so far")
                return

            if not uploaded["success"]:

                log("❌ Upload failed")
                # Distinguish chunked-upload failures for clearer triage
                err = str(uploaded.get("error", ""))
                stage = "CHUNK_UPLOAD" if "chunk" in err.lower() else "UPLOAD"
                log_failed(
                    node,
                    stage=stage,
                    reason=err,
                    node_type="FILE",
                    upload_path=full_sharepoint_path,
                )
                log_processed(
                    node,
                    node_type="FILE",
                    status="Failure",
                    sharepoint_path=full_sharepoint_path,
                    detail=err[:300],
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

                try:
                    meta_res = sp.metadata(
                        file_id,
                        metadata
                    )
                    if meta_res and meta_res.get("success"):
                        log("✅ File Metadata Applied")
                    else:
                        # File uploaded OK, but metadata failed.
                        err = (meta_res or {}).get("error", "unknown metadata error")
                        status_code = (meta_res or {}).get("status", "")
                        file_status = "Failure"
                        file_detail = (
                            f"Uploaded success but metadata failed "
                            f"(HTTP {status_code}): {str(err)[:200]}"
                        )
                        log("❌ File metadata FAILED (upload was OK):", file_detail)
                        log_failed(
                            node,
                            stage="METADATA",
                            reason=f"Upload OK but metadata failed (HTTP {status_code}): {str(err)[:300]}",
                            node_type="FILE",
                            upload_path=full_sharepoint_path,
                        )
                except Exception as e:
                    file_status = "Failure"
                    file_detail = f"Uploaded success but metadata exception: {e}"
                    log("❌ File metadata error:", str(e))
                    log_failed(
                        node,
                        stage="METADATA",
                        reason=f"Upload OK but metadata exception: {e}",
                        node_type="FILE",
                        upload_path=full_sharepoint_path,
                    )

        # =================================================
        # Record processed status for this file
        # =================================================

        if file_status == "Success" and not file_detail:
            file_detail = "Uploaded" if not already_processed else "Already existed"

        log_processed(
            node,
            node_type="FILE",
            status=file_status,
            sharepoint_path=full_sharepoint_path,
            detail=file_detail,
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
# Invalid folder flat log (quick-scan companion to failed CSV)
#------------------------------------------------

def log_invalid_folder(node):

    with open(
        INVALID_FOLDER_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            f"ObjectId={node.get('OBJECT_ID') or node.get('ObjectId')} | "
            f"TDMX_ID={node.get('TDMX_ID')} | "
            f"Description={node.get('Description')} | "
            f"CAD={node.get('TDMX_CAD_IDENTIFIER')}\n"
        )