import os
import re
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed

from auth import get_token
from sharepoint import SharePoint

from project_builder import (
    build_project_tree,
    PROJECT_NODES
)

from builder import process, set_resume_done

from utils import sanitize

from config import (
    PROJECT_FOLDER,
    DOCUMENT_CSV_FOLDER,
    UPLOAD_WORKERS,
)

from logger import (
    log,
    log_session_start,
    get_processed_count,
    start_project,
    log_processed,
    log_failed,
    load_done_paths,
    begin_file_log,
    end_file_log,
)


def sanitize_for_filename(raw):
    """
    Make a string safe to use in a filename. Keeps letters, digits,
    '-', '_', '.'; replaces every other run of characters with a single
    underscore. Returns "" for empty/None so the caller can fall back.
    Mirrors the C# SanitizeForFileName so SmarTeam and GraphAPI agree.
    """
    if not raw:
        return ""
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", str(raw))
    s = re.sub(r"_+", "_", s)
    return s.strip("_. ")

# ==========================================
# DEBUG
# ==========================================

log_session_start()

log("\n================ DEBUG ================")

log("CURRENT WORKING DIRECTORY:")
log(os.getcwd())

log("\nPROJECT_FOLDER:")
log(PROJECT_FOLDER)

log("\nDOCUMENT_CSV_FOLDER:")
log(DOCUMENT_CSV_FOLDER)

log("\nPROJECT EXISTS:")
log(os.path.exists(PROJECT_FOLDER) if PROJECT_FOLDER else False)

log("\nDOCUMENT_CSV_FOLDER EXISTS:")
log(os.path.exists(DOCUMENT_CSV_FOLDER) if DOCUMENT_CSV_FOLDER else False)

if PROJECT_FOLDER and os.path.exists(PROJECT_FOLDER):
    log("\nPROJECT FILES:")
    log(os.listdir(PROJECT_FOLDER))

if DOCUMENT_CSV_FOLDER and os.path.exists(DOCUMENT_CSV_FOLDER):
    log("\nDOCUMENT CSV FILES:")
    log([f for f in os.listdir(DOCUMENT_CSV_FOLDER) if f.startswith("Documents_Tree")])

log("=======================================\n")

# def walk_projects(node):
#     yield node

#     for child in node.get("children", []):
#         yield from walk_projects(child)

def main(resume=False):

    if resume:
        log("\n🔁 RESUME MODE ON — already-completed nodes "
            "(Success/Skipped) from prior runs will be skipped.")

    # ======================================
    # AUTH
    # ======================================

    sp = SharePoint()

    sp.init()

    # ======================================
    # ROOT FOLDER
    # ======================================

    base = "Testing_saj"

    sp.ensure_path(base)

    # ======================================
    # PROJECT FILES (Projects_Tree_<id>.csv)
    # ======================================

    project_files = [
        f for f in os.listdir(PROJECT_FOLDER)
        if f.startswith("Projects_Tree") and f.endswith(".csv")
    ]

    log(
        "\n📂 Total Projects:",
        len(project_files)
    )

    # ======================================
    # GRAND TOTALS (across all projects)
    # ======================================

    grand_total_docs = 0
    grand_total_files = 0
    grand_total_folders = 0

    # ======================================
    # PROCESS EACH PROJECT
    # ======================================

    for project_index, project_file in enumerate(project_files, start=1):

        # ==================================
        # FILE PATHS
        # ==================================

        project_csv_path = os.path.join(
            PROJECT_FOLDER,
            project_file
        )

        # ==================================
        # READ PROJECT TREE CSV
        # One row per project node. Columns:
        #   LEVEL, PARENT_ID, CHILD_ID, TDMX_ID, TDM_DESCRIPTION,
        #   CN_REFERENCE_PROJECT, USER_OBJECT_ID, MODIFICATION_DATE,
        #   CN_REF_PM_PT, CN_PROJECT_TYPE, TDMX_CUSTOMER, TDMX_COMMENTS,
        #   CN_CLASSIFICATION, CREATION_DATE, TITLE, DETAILS, FULL_PATH
        # We rebuild the parent→children tree from PARENT_ID/CHILD_ID
        # so build_project_tree() can recurse exactly as it did on JSON.
        # ==================================

        proj_rows = []
        with open(project_csv_path, "r", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                # skip any summary/blank rows defensively
                if (r.get("CHILD_ID") or "").strip():
                    proj_rows.append(r)

        if not proj_rows:
            log(f"\n⚠️ Project CSV empty: {project_csv_path}")
            continue

        # Build node dicts keyed by CHILD_ID, with a children list.
        proj_nodes = {}
        for r in proj_rows:
            cid = r["CHILD_ID"].strip()
            proj_nodes[cid] = {
                "OBJECT_ID":            cid,
                "TDMX_ID":              r.get("TDMX_ID", ""),
                "TDM_DESCRIPTION":      r.get("TDM_DESCRIPTION", ""),
                "CN_REFERENCE_PROJECT": r.get("CN_REFERENCE_PROJECT", ""),
                "USER_OBJECT_ID":       r.get("USER_OBJECT_ID", ""),
                "MODIFICATION_DATE":    r.get("MODIFICATION_DATE", ""),
                "CN_REF_PM_PT":         r.get("CN_REF_PM_PT", ""),
                "CN_PROJECT_TYPE":      r.get("CN_PROJECT_TYPE", ""),
                "TDMX_CUSTOMER":        r.get("TDMX_CUSTOMER", ""),
                "TDMX_COMMENTS":        r.get("TDMX_COMMENTS", ""),
                "CN_CLASSIFICATION":    r.get("CN_CLASSIFICATION", ""),
                "CREATION_DATE":        r.get("CREATION_DATE", ""),
                "TITLE":                r.get("TITLE", ""),
                "DETAILS":              r.get("DETAILS", ""),
                "LEVEL":                r.get("LEVEL", ""),
                "PARENT_ID":            (r.get("PARENT_ID") or "").strip(),
                "children":             [],
            }

        # Link children to parents; roots are rows whose PARENT_ID is
        # empty or not present among the nodes.
        roots = []
        for cid, node in proj_nodes.items():
            pid = node["PARENT_ID"]
            if pid and pid in proj_nodes:
                proj_nodes[pid]["children"].append(node)
            else:
                roots.append(node)

        # Derive TDMX_ID for filenames from the first root.
        tdmx_id = roots[0].get("TDMX_ID") if roots else None
        stem = os.path.splitext(project_file)[0]
        # strip the "Projects_Tree_" prefix for a clean tag fallback
        if stem.startswith("Projects_Tree_"):
            stem = stem[len("Projects_Tree_"):]
        #project_tag = sanitize_for_filename(tdmx_id) or stem

        #start_project(project_tag)

        # ==================================
        # RESUME: load already-done paths for THIS project from prior
        # runs' processed CSVs, and install them in the builder so files
        # already uploaded are skipped. Folder skipping uses the same set.
        # ==================================
        #done_paths = load_done_paths(project_tag) if resume else set()
        #set_resume_done(done_paths)

        # log("\n================================")
        # log(f"🚀 PROCESSING ({project_index}/{len(project_files)}):", project_file)
        # log(f"   TDMX_ID: {tdmx_id} | file tag: {project_tag}")
        # log(f"   Project nodes: {len(proj_nodes)} | roots: {len(roots)}")
        # if resume:
        #     log(f"   Resume: {len(done_paths)} paths already done (will skip)")
        # log("================================")

        # ==================================
        # CREATE PROJECT ROOT (+ nested project folders)
        # ==================================

        project_root = None

        for project_node in roots:
            project_root = build_project_tree(project_node, sp, base)
            log_processed(
                project_node,
                node_type="PROJECT",
                status="Success",
                sharepoint_path=project_root or "",
                detail="Project root created",
            )


        log("\n✅ Project Root:", project_root)

        # ==================================
        # READ DOCUMENTS_TREE CSV
        # All document data comes from the CSV — not from JSON.
        # The CSV is the authoritative, flat list of every
        # document-parent relationship (all 7k+ rows), with all
        # fields pre-populated by SmarTeam. Reading from CSV
        # ensures no rows are missed due to JSON tree traversal
        # constraints (visited-set skipping paths).
        # ==================================
    
        for project_id, info in PROJECT_NODES.items():
            project = info["node"]
            project_tag = project["TDMX_ID"]
            project_root = project["SP_PATH"]
             # ADD THESE TWO LINES
            start_project(project_tag)
            # ==================================
            # RESUME: load already-done paths for THIS project from prior
            # runs' processed CSVs, and install them in the builder so files
            # already uploaded are skipped. Folder skipping uses the same set.
            # ==================================
            done_paths = load_done_paths(project_tag) if resume else set()
            set_resume_done(done_paths)
            log("\n================================")
            log(f"🚀 PROCESSING ({project_index}/{len(project_files)}):", project_file)
            log(f"   TDMX_ID: {tdmx_id} | file tag: {project_tag}")
            log(f"   Project nodes: {len(proj_nodes)} | roots: {len(roots)}")
            if resume:
                log(f"   Resume: {len(done_paths)} paths already done (will skip)")
            log("================================")
            doc_csv_path = os.path.join(
                DOCUMENT_CSV_FOLDER,
                f"Documents_Tree_{project_tag}.csv"
            ) if DOCUMENT_CSV_FOLDER else None
            
            doc_csv_name = os.path.basename(doc_csv_path)

            if not doc_csv_path or not os.path.exists(doc_csv_path):
                log(f"\n⚠️ Documents_Tree CSV not found: {doc_csv_path}")
                log("  Set DOCUMENT_CSV_FOLDER in .env to the folder containing Documents_Tree_*.csv files")
                continue

            # Read all rows, split into folder vs file rows.
            folder_rows = []
            file_rows = []

            with open(doc_csv_path, "r", encoding="utf-8-sig", newline="") as cf:
                for row in csv.DictReader(cf):
                    if (row.get("ROOT_DIR_ON_SERVER") or "").strip():
                        file_rows.append(row)
                    else:
                        folder_rows.append(row)

            grand_total_folders += len(folder_rows)
            grand_total_files += len(file_rows)
            grand_total_docs += len(folder_rows) + len(file_rows)

            log(f"\n📊 CSV rows for {project_file}:")
            log(f"\n📄 Processing Document CSV: {doc_csv_name}")
            log(f"   FOLDER rows: {len(folder_rows)}")
            log(f"   FILE rows:   {len(file_rows)}")

            processed_before = get_processed_count()

            # ==================================
            # CSV path → SharePoint path
            # DocPath/UploadPath format: "ProjectName/seg/seg/.../name"
            # The first segment is the SmarTeam project name; we replace it
            # with project_root and translate the "previous_revision" marker
            # to a "Previous_Revision" subfolder. SmarTeam already collapses
            # file-assembly folders, so we trust the path as written.
            # ==================================

            def csv_dir_to_sp(csv_path, drop_last=False, keep_prev=True):
                parts = [p for p in csv_path.split("/") if p]
                
                if drop_last and parts:
                    parts = parts[:-1]          # drop filename for UploadPath
                seg = parts[1:]                 # drop SmarTeam project name
                out = []
                for p in seg:
                    if p.lower() == "previous_revision":
                        if keep_prev:
                            out.append("Previous_Revision")
                        # else: skip — builder will add Previous_Revision once
                    else:
                        out.append(sanitize(p))
                return (project_root or "") + ("/" + "/".join(out) if out else "")

            # ==================================
            # HELPER: build node dict from CSV row
            # ==================================

            def make_node(row):
                return {
                    "OBJECT_ID":                row.get("DocObjectId", ""),
                    "TDMX_ID":                  row.get("TDMX_ID", ""),
                    "Description":              row.get("Description", ""),
                    "FILE_NAME":                row.get("FILE_NAME", ""),
                    "CAD_REF_FILE_NAME":        row.get("CAD_REF_FILE_NAME", ""),
                    "ROOT_DIR_ON_SERVER":       row.get("ROOT_DIR_ON_SERVER", ""),
                    "REVISION":                 row.get("REVISION", ""),
                    "REVISION_STG":             row.get("REVISION_STG", ""),
                    "PAR_REVISION":             row.get("PAR_REVISION", ""),
                    "STATE":                    row.get("STATE", ""),
                    "TDM_FILE_ID":              row.get("TDM_FILE_ID", ""),
                    "VAULT_OBJECT_ID":          row.get("VAULT_OBJECT_ID", ""),
                    "FILE_SIZE":                row.get("FILE_SIZE", ""),
                    "FILE_SIZE_DISPLAY":        row.get("FILE_SIZE", ""),
                    "TDMX_CAD_IDENTIFIER":      row.get("TDMX_CAD_IDENTIFIER", ""),
                    "USER_OBJECT_ID":           row.get("USER_OBJECT_ID", ""),
                    "MODIFICATION_DATE":        row.get("MODIFICATION_DATE", ""),
                    "CREATION_DATE":            row.get("CREATION_DATE", ""),
                    "CN_DOCUMENT_APPLICABILITY":row.get("CN_DOCUMENT_APPLICABILITY", ""),
                    "TDMX_DETAILED_DESCRIPTION":row.get("TDMX_DETAILED_DESCRIPTION", ""),
                    "TDMX_COMMENTS":            row.get("TDMX_COMMENTS", ""),
                    "DESIGN_MODULE":            row.get("DESIGN_MODULE", ""),
                    "Path":                     row.get("DocPath", ""),
                    "UploadPath":               row.get("UploadPath", ""),
                    "ExtractTimestamp":         row.get("ExtractTimestamp", ""),
                    "Children":                 [],
                }

            # ==================================
            # PASS 1: FOLDER CREATION + METADATA
            # Only real folders (rows without ROOT_DIR_ON_SERVER) are
            # created. SmarTeam already excluded file-assembly folders
            # from the folder rows' DocPath collapse, so folder paths are
            # taken straight from DocPath.
            # ==================================

            log("\n📁 Pass 1: creating folders...")
            folders_done = 0

            for row in folder_rows:

                doc_path = (row.get("DocPath") or "").strip()
                if not doc_path:
                    continue
                log("=" * 100)
                log(f"Project Tag  : {project_tag}")
                log(f"Project Root : {project_root}")
                log(f"Doc Path     : {doc_path}")
                sp_path = csv_dir_to_sp(doc_path)
                log(f"Final SP Path: {sp_path}")
                node = make_node(row)

                # Resume: folder already created+metadata'd in a prior run
                if resume and sp_path in done_paths:
                    log_processed(node, "FOLDER", "Skipped(Resume)", sp_path,
                                "Already completed in a previous run (--resume)")
                    folders_done += 1
                    continue

                folder_status = "Success"
                folder_detail = "Folder created"

                try:
                    log("=" * 100)
                    log(f"Project TDMX_ID : {project_tag}")
                    log(f"Project Root    : {project_root}")
                    log(f"DocPath         : {doc_path}")
                    log(f"SharePoint Path : {sp_path}")
                    log("Calling sp.ensure_path()...")

                    sp.ensure_path(sp_path)
                    log("Folder created successfully.")
                except Exception as e:
                    folder_status = "Failure"
                    folder_detail = f"ensure_path error: {e}"
                    log_failed(node, "FOLDER_CREATE", str(e), "FOLDER", sp_path)
                    log_processed(node, "FOLDER", folder_status, sp_path, folder_detail)
                    continue

                # Apply folder metadata
                try:
                    item = sp.get_item(sp_path)
                    if item:
                        from metadata import build_metadata
                        meta = build_metadata(node, "FOLDER")
                        if meta:
                            meta_res = sp.metadata(item["id"], meta)
                            if not (meta_res and meta_res.get("success")):
                                err = (meta_res or {}).get("error", "unknown")
                                code = (meta_res or {}).get("status", "")
                                folder_status = "Failure"
                                folder_detail = f"Folder created but metadata failed (HTTP {code})"
                                log_failed(node, "FOLDER_METADATA", str(err)[:300], "FOLDER", sp_path)
                except Exception as e:
                    folder_status = "Failure"
                    folder_detail = f"Metadata error: {e}"
                    log_failed(node, "FOLDER_METADATA", str(e), "FOLDER", sp_path)

                log_processed(node, "FOLDER", folder_status, sp_path, folder_detail)
                folders_done += 1

            log(f"✅ Folders done: {folders_done}")

            # ==================================
            # PASS 2: FILE UPLOADS (parallel)
            # SmarTeam's UploadPath is authoritative (paths collapsed, prev-rev
            # marker present). We derive the parent folder by dropping the
            # filename, then call process() concurrently across UPLOAD_WORKERS
            # threads. Uploads are I/O-bound (waiting on Graph), so threads give
            # a large speedup. process() itself is unchanged; logging/counter/
            # caches are thread-safe, and SharePoint throttling (429) is handled
            # with Retry-After backoff inside the upload calls.
            # ==================================

            log(f"\n📄 Pass 2: uploading files (workers={UPLOAD_WORKERS})...")

            def _handle_file(row):
                upload_path = (row.get("UploadPath") or "").strip()
                if not upload_path:
                    return
                # Parent folder = UploadPath minus filename, WITHOUT the
                # previous_revision marker — builder.process() re-adds the
                # Previous_Revision subfolder once when it sees the marker.
                parent_sp = csv_dir_to_sp(upload_path, drop_last=True, keep_prev=False)
                node = make_node(row)
                # Group all of THIS file's log lines into one contiguous block
                # so concurrent workers don't interleave their output.
                begin_file_log()
                try:
                    process(node, sp, parent_sp)
                except Exception as e:
                    # A single file's failure must never kill the pool, and the
                    # node must STILL appear in processed.csv (with Failure) so
                    # the processed count always matches the Documents_Tree.
                    log(f"⚠️ Unhandled error processing "
                        f"{row.get('DocObjectId','')}: {e}")
                    log_failed(node, "UPLOAD_UNHANDLED",
                            str(e), "FILE", upload_path)
                    log_processed(node, "FILE", "Failure", upload_path,
                                f"Unhandled error: {e}")
                finally:
                    # Emit the whole block atomically, even on error.
                    end_file_log()

            if UPLOAD_WORKERS <= 1:
                # Sequential fallback (set UPLOAD_WORKERS=1 to disable threading)
                for row in file_rows:
                    _handle_file(row)
            else:
                with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
                    futures = [pool.submit(_handle_file, row) for row in file_rows]
                    for fut in as_completed(futures):
                        # Exceptions are already caught inside _handle_file;
                        # this just surfaces anything truly unexpected.
                        exc = fut.exception()
                        if exc:
                            log(f"⚠️ Worker raised: {exc}")

            # ==================================
            # PER-PROJECT SUMMARY
            # ==================================

            processed_this_project = get_processed_count() - processed_before

            log(
                f"\n📦 PROJECT '{project_file}' DONE — "
                f"{processed_this_project} nodes handled "
                f"(running total: {get_processed_count()})"
            )
            log("\n=========== PROJECT SUMMARY ===========")
            log(f"📁 Project       : {project_tag}")
            log(f"📂 Path          : {project_root}")
            log(f"📊 Folder Rows   : {len(folder_rows)}")
            log(f"📊 File Rows     : {len(file_rows)}")
            log(f"📊 Processed     : {processed_this_project}")
            log("======================================")

        # ======================================
        # FINAL SUMMARY
        # ======================================

        log("\n=========== FINAL SUMMARY ===========")
        log(f"📊 Projects processed:   {len(project_files)}")
        log(f"📊 Grand total nodes:    {grand_total_docs}")
        log(f"📊 Grand total FILES:    {grand_total_files}")
        log(f"📊 Grand total FOLDERS:  {grand_total_folders}")
        log(f"📊 Files handled (run):  {get_processed_count()}")
        log("=====================================")

        log("\n✅ Migration Complete")


if __name__ == "__main__":
    import sys
    resume_flag = "--resume" in sys.argv[1:]
    main(resume=resume_flag)
