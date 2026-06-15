import os
import json

from auth import get_token
from sharepoint import SharePoint

from project_builder import (
    build_project_tree
)

from builder import process

from config import (
    PROJECT_FOLDER,
    DOCUMENT_FOLDER
)

from logger import (
    log,
    log_session_start,
    get_processed_count,
    reset_processed_count,
    count_document_json
)

# ==========================================
# DEBUG
# ==========================================

log_session_start()

log("\n================ DEBUG ================")

log("CURRENT WORKING DIRECTORY:")
log(os.getcwd())

log("\nPROJECT_FOLDER:")
log(PROJECT_FOLDER)

log("\nDOCUMENT_FOLDER:")
log(DOCUMENT_FOLDER)

log("\nPROJECT EXISTS:")
log(os.path.exists(PROJECT_FOLDER))

log("\nDOCUMENT EXISTS:")
log(os.path.exists(DOCUMENT_FOLDER))

if os.path.exists(PROJECT_FOLDER):

    log("\nPROJECT FILES:")
    log(os.listdir(PROJECT_FOLDER))

if os.path.exists(DOCUMENT_FOLDER):

    log("\nDOCUMENT FILES:")
    log(os.listdir(DOCUMENT_FOLDER))

log("=======================================\n")


def main():

    # ======================================
    # AUTH
    # ======================================

    sp = SharePoint()

    sp.init()

    # ======================================
    # ROOT FOLDER
    # ======================================

    base = "GraphAPI"

    sp.ensure_path(base)

    # ======================================
    # PROJECT FILES
    # ======================================

    project_files = [

        f for f in os.listdir(
            PROJECT_FOLDER
        )

        if f.endswith(".json")
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

        log("\n================================")
        log(f"🚀 PROCESSING ({project_index}/{len(project_files)}):", project_file)
        log("================================")

        # ==================================
        # FILE PATHS
        # ==================================

        project_json_path = os.path.join(
            PROJECT_FOLDER,
            project_file
        )

        document_json_path = os.path.join(
            DOCUMENT_FOLDER,
            project_file
        )

        log("\n📁 Project JSON:")
        log(project_json_path)

        log("\n📁 Document JSON:")
        log(document_json_path)

        # ==================================
        # READ PROJECT JSON
        # ==================================

        with open(
            project_json_path,
            "r",
            encoding="utf-8-sig"
        ) as f:

            project_json = json.load(f)

        log(
            "\n📄 Project JSON Type:",
            type(project_json)
        )

        # ==================================
        # CREATE PROJECT ROOT
        # ==================================

        project_root = None

        if isinstance(project_json, list):

            for project_node in project_json:

                project_root = build_project_tree(
                    project_node,
                    sp,
                    base
                )

        elif isinstance(project_json, dict):

            project_root = build_project_tree(
                project_json,
                sp,
                base
            )

        log(
            "\n✅ Project Root:",
            project_root
        )

        # ==================================
        # DOCUMENT FILE NOT FOUND
        # ==================================

        if not os.path.exists(
            document_json_path
        ):

            log(
                "\n⚠️ No matching document file"
            )

            continue

        # ==================================
        # READ DOCUMENT JSON
        # ==================================

        with open(
            document_json_path,
            "r",
            encoding="utf-8-sig"
        ) as f:

            document_json = json.load(f)

        log("\n================ DOCUMENT DEBUG ================")

        log(
            "Document JSON Type:",
            type(document_json)
        )

        log("================================================\n")

        # ==================================
        # COUNT DOCUMENTS (TOTAL / FILES / FOLDERS)
        # ==================================

        proj_total, proj_files, proj_folders = count_document_json(
            document_json
        )

        log("📊 DOCUMENT COUNTS for " + project_file + ":")
        log(
            f"   Total: {proj_total} | "
            f"Files: {proj_files} | "
            f"Folders: {proj_folders}"
        )

        grand_total_docs += proj_total
        grand_total_files += proj_files
        grand_total_folders += proj_folders

        # ==================================
        # SNAPSHOT COUNT BEFORE PROCESSING
        # ==================================

        processed_before = get_processed_count()

        # ==================================
        # DOCUMENT JSON -> LIST
        # ==================================

        if isinstance(document_json, list):

            for document_root in document_json:

                documents = (
                    document_root.get(
                        "Documents",
                        []
                    )
                )

                log(
                    "\n📂 Total Documents:",
                    len(documents)
                )

                for document_node in documents:

                    process(
                        document_node,
                        sp,
                        project_root
                    )

        # ==================================
        # DOCUMENT JSON -> OBJECT
        # ==================================

        elif isinstance(document_json, dict):

            documents = (
                document_json.get(
                    "Documents",
                    []
                )
            )

            log(
                "\n📂 Total Documents:",
                len(documents)
            )

            for document_node in documents:

                process(
                    document_node,
                    sp,
                    project_root
                )

        # ==================================
        # PER-PROJECT SUMMARY
        # ==================================

        processed_this_project = (
            get_processed_count() - processed_before
        )

        log(
            f"\n📦 PROJECT '{project_file}' DONE — "
            f"{processed_this_project} files handled this project "
            f"(running total: {get_processed_count()})"
        )

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
    main()
