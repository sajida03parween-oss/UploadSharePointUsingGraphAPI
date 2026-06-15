project_name = "B773  - RECONFIGURATION 8P TO 42J"

expected_items = [
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
]

cleanup_project_folders(
    access_token=token,
    site_id=site_id,
    drive_id=drive_id,
    parent_folder_id=root_folder_id,
    project_name=project_name,
    expected_items=expected_items,
)