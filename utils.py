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

    return name.strip()