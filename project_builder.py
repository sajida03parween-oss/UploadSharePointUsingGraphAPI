import requests

from utils import sanitize
from metadata import build_metadata
from logger import log


def build_project_tree(
    node,
    sp,
    parent
):

    # ==========================================
    # Project Name
    # ==========================================

    project_name = sanitize(
        node.get("TDM_DESCRIPTION")
        or node.get("TITLE")
        or node.get("TDMX_ID")
        or "Unnamed_Project"
    )

    current_path = (
        f"{parent}/{project_name}"
    )

    log("\n📁 PROJECT:", current_path)

    # ==========================================
    # Create Folder
    # ==========================================

    sp.ensure_path(current_path)

    # ==========================================
    # Get SharePoint Item
    # ==========================================

    res = requests.get(
        f"https://graph.microsoft.com/v1.0/drives/{sp.drive_id}/root:/{current_path}",
        headers=sp.get_headers()
    )

    if res.status_code == 200:

        folder_id = res.json()["id"]

        metadata = build_metadata(
            node,
            "PROJECT"
        )

        if metadata:

            log("📝 Applying Project Metadata")

            sp.metadata(
                folder_id,
                metadata
            )

            log("✅ Project Metadata Applied")

    # ==========================================
    # Recursive Children
    # ==========================================

    for child in node.get("children", []):

        build_project_tree(
            child,
            sp,
            current_path
        )

    return current_path
