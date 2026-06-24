def sanitize(name):

    if not name:
        return "Unknown"

    invalid_chars = [
        "/",
        "\\",
        '"',
        "*",
        ":",
        "<",
        ">",
        "?",
        "|"
    ]

    for char in invalid_chars:
        name = name.replace(char, "_")

    # SharePoint silently strips trailing periods and spaces when it stores
    # a folder name. If our code creates "ASSY." SharePoint stores "ASSY",
    # then GET /root:/...ASSY.: returns 404 and all children are skipped.
    # Strip both trailing spaces AND trailing periods from each path segment
    # so our names always match what SharePoint will actually store.
    segments = name.strip().split("/")
    cleaned = [seg.strip().rstrip(".") for seg in segments]
    name = "/".join(cleaned)

    return name.strip()