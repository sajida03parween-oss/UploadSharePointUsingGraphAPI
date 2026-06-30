from platform import node

import requests

from utils import sanitize
from metadata import build_metadata
from logger import log

PROJECT_NODES = {}

def build_project_tree(
    node,
    sp,
    parent
):

    # ==========================================
    # Project Name
    # ==========================================

    cad_identifier = (
        node.get("CN_REFERENCE_PROJECT")
        or ""
    ).strip()

    description = (
        node.get("TDM_DESCRIPTION")
        or ""
    ).strip()

    project_name = sanitize(
        f"[{cad_identifier}] {description}"
    )

    current_path = (
        f"{parent}/{project_name}"
    )

    # Save the SharePoint path inside the node
    node["SP_PATH"] = current_path

    PROJECT_NODES[node["TDMX_ID"]] = {
        "path": current_path,
        "node": node
    }

    log("\n📁 PROJECT:", current_path)

    # ==========================================
    # Create Folder
    # ==========================================

    sp.ensure_path(current_path)

    # ==========================================
    # Get SharePoint Item
    # Use sp.get_item (which percent-encodes the path) instead of a raw
    # request, so project names containing # + & don't truncate the URL.
    # ==========================================

    item = sp.get_item(current_path)

    if item:

        folder_id = item["id"]

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
