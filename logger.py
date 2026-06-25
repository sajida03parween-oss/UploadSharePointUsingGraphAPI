import os
import csv
import atexit
import threading
from datetime import datetime

# =========================================================
# Configuration
# =========================================================

LOG_DIR = "."                  # Directory for log files (current dir)
LOG_FILE_PREFIX = "log"        # Filename → log_<timestamp>.txt
BUFFER_FLUSH_LINES = 100       # Write to disk every N buffered lines
FILE_ROTATE_LINES = 50_000     # Start a new log file every N lines


# =========================================================
# Internal state
# =========================================================

_lock = threading.Lock()       # Protects _buffer and file-state vars
_csv_lock = threading.Lock()   # Protects processed_/failed_ CSV appends

_buffer = []                   # Pending formatted lines (not yet on disk)

_current_log_file = None       # Path of the active log file
_lines_in_current_file = 0     # How many lines already written to it

_processed_count = 0           # Global "files processed" counter

_current_project_id = None     # Project id stem (e.g. "3476") for filenames

# A per-run stamp so each execution writes its OWN processed_/failed_
# CSV (instead of appending to a shared one). This lets --resume read
# all prior runs' processed CSVs while never overwriting them.
_RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")


# =========================================================
# Filename helpers
# =========================================================

def _new_log_filename():
    """
    Build a fresh log filename of the form
        log_<YYYYMMDD_HHMMSS>[_<projectId>].log
    in LOG_DIR. When a project id is active, it is appended so each
    project's log is identifiable (e.g. log_20260616_143052_3476.log).
    If a file with that name already exists (fast rotation within the
    same second), suffix with _part2, _part3, ...
    """

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if _current_project_id:
        base_name = f"{LOG_FILE_PREFIX}_{ts}_{_current_project_id}.log"
    else:
        base_name = f"{LOG_FILE_PREFIX}_{ts}.log"

    base_path = (
        os.path.join(LOG_DIR, base_name)
        if LOG_DIR else base_name
    )

    if not os.path.exists(base_path):
        return base_path

    # Collision — append a counter
    i = 2
    while True:
        alt = base_path[:-4] + f"_part{i}.log"
        if not os.path.exists(alt):
            return alt
        i += 1


def _ensure_log_dir():
    """Create LOG_DIR if it doesn't exist (no-op for current dir)."""
    if LOG_DIR and LOG_DIR not in (".", ""):
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
        except Exception:
            pass


def _ensure_log_file_locked():
    """
    Make sure _current_log_file is set. Must be called while holding _lock.
    """

    global _current_log_file, _lines_in_current_file

    if _current_log_file is None:
        _ensure_log_dir()
        _current_log_file = _new_log_filename()
        _lines_in_current_file = 0

        try:
            print(f"📝 Logging to: {_current_log_file}")
        except Exception:
            pass


def _rotate_locked():
    """
    Open a NEW log file. Must be called while holding _lock.
    Caller is responsible for first flushing anything that belongs in
    the old file.
    """

    global _current_log_file, _lines_in_current_file

    _current_log_file = _new_log_filename()
    _lines_in_current_file = 0

    try:
        print(f"🔄 Rotated to new log file: {_current_log_file}")
    except Exception:
        pass


# =========================================================
# Buffer flush
# =========================================================

def _flush_locked():
    """
    Write everything in _buffer to disk, rotating files when the
    current file's line count crosses FILE_ROTATE_LINES.
    Must be called while holding _lock.
    """

    global _buffer, _lines_in_current_file

    if not _buffer:
        return

    _ensure_log_file_locked()

    remaining = _buffer
    _buffer = []

    try:
        while remaining:

            room = FILE_ROTATE_LINES - _lines_in_current_file

            # Current file is full — rotate before writing
            if room <= 0:
                _rotate_locked()
                continue

            # Write what fits in the current file
            chunk = remaining[:room]
            remaining = remaining[room:]

            with open(
                _current_log_file,
                "a",
                encoding="utf-8"
            ) as f:
                f.write("\n".join(chunk) + "\n")

            _lines_in_current_file += len(chunk)

    except Exception as e:
        try:
            print(f"⚠️ logger: failed to flush — {e}")
        except Exception:
            pass


def flush_logs():
    """Force-write any buffered lines to disk now."""
    with _lock:
        _flush_locked()


# Make sure buffered lines hit disk on normal program exit
atexit.register(flush_logs)


# =========================================================
# Core log function
# =========================================================

def log(*args, **kwargs):
    """
    Print to console AND queue the line for the log file.
    Lines are written to disk in batches of BUFFER_FLUSH_LINES
    (default 100), and the log file rotates every FILE_ROTATE_LINES
    (default 50,000) lines.
    """

    sep = kwargs.get("sep", " ")
    msg = sep.join(str(a) for a in args)

    # 1) Print to console immediately (terminal output stays real-time)
    try:
        print(msg, **kwargs)
    except Exception:
        pass

    # 2) Format with timestamp — one entry per source line
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"[{ts}] {line}" for line in msg.split("\n")]

    # 3) Append to buffer; flush if we've hit the threshold
    with _lock:
        _buffer.extend(lines)
        if len(_buffer) >= BUFFER_FLUSH_LINES:
            _flush_locked()


def log_session_start():
    """
    Write a clear session-start banner and flush immediately
    so the log file appears on disk right away.
    """

    banner = "=" * 60
    log(banner)
    log("NEW SESSION STARTED")
    log(banner)
    flush_logs()


# =========================================================
# Per-project context
# =========================================================

def start_project(project_id):
    """
    Begin a new project. Flushes the current log, then starts a FRESH
    log file named log_<YYYYMMDD_HHMMSS>_<project_id>.log so each
    project gets its own log. Also sets the active project id used by
    builder.py to name failed_<id>.csv and processed_<id>.csv.
    """
    global _current_project_id, _current_log_file, _lines_in_current_file

    with _lock:
        # Flush anything pending into the OLD log file first
        _flush_locked()
        # Switch project + force a brand-new log file on next write
        _current_project_id = str(project_id) if project_id is not None else None
        _current_log_file = None
        _lines_in_current_file = 0

    banner = "=" * 60
    log(banner)
    log(f"PROJECT START: {project_id}")
    log(banner)
    flush_logs()


def get_project_id():
    """Return the active project id stem (or None)."""
    return _current_project_id


# =========================================================
# Per-project FAILED-files CSV
#
# One file per project: failed_<projectId>.csv
# Captures every failure point (metadata, upload, chunk, folder
# create/fetch, vault-missing, naming, etc.) with identifying
# info and the reason.
# =========================================================

FAILED_PREFIX = "failed"

_FAILED_HEADER = [
    "ProjectId",
    "Stage",            # where it failed: FOLDER_CREATE, UPLOAD, CHUNK, METADATA, VAULT, NAMING, ...
    "TDMX_ID",
    "OBJECT_ID",
    "Description",
    "NodeType",         # FILE / FOLDER / PROJECT / UNKNOWN
    "Path",
    "UploadPath",
    "Reason",
]


def _failed_csv_path():
    pid = _current_project_id or "unknown"
    name = f"{FAILED_PREFIX}_{pid}_{_RUN_ID}.csv"
    return os.path.join(LOG_DIR, name) if LOG_DIR else name


def _node_object_id(node):
    # Support several possible id keys seen across project/document JSON
    return (
        node.get("OBJECT_ID")
        or node.get("DocObjectId")
        or node.get("ObjectId")
        or node.get("VAULT_OBJECT_ID")
        or ""
    )


def _node_tdmx_id(node):
    return node.get("TDMX_ID") or node.get("TdmxId") or ""


def log_failed(node, stage, reason, node_type="", upload_path=""):
    """
    Append a failure record to failed_<projectId>.csv.

    node       : the JSON node dict (file/folder/project) — may be {} if unknown
    stage      : short stage tag, e.g. "UPLOAD", "FOLDER_CREATE", "METADATA"
    reason     : human-readable error / exception text
    node_type  : FILE / FOLDER / PROJECT (optional)
    upload_path: target SharePoint path if known (optional)
    """
    node = node or {}
    path = _failed_csv_path()

    row = [
        _current_project_id or "",
        stage,
        _node_tdmx_id(node),
        _node_object_id(node),
        node.get("Description") or node.get("TDM_DESCRIPTION") or "",
        node_type,
        node.get("Path", ""),
        upload_path or node.get("UploadPath", ""),
        reason,
    ]

    try:
        if LOG_DIR and LOG_DIR not in (".", ""):
            os.makedirs(LOG_DIR, exist_ok=True)
        with _csv_lock:
            with open(path, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                if f.tell() == 0:
                    w.writerow(_FAILED_HEADER)
                w.writerow(row)
    except Exception as e:
        # Never let failure-logging crash the run
        log(f"⚠️ Could not write failed record: {e}")


# =========================================================
# Per-project PROCESSED CSV
#
# One file per project: processed_<projectId>.csv
# Records EVERY node processed (project / folder / file) with the
# fields present in the JSON plus the SharePoint path and a
# Success/Failure status. Replaces the old processed_files.txt.
# =========================================================

PROCESSED_PREFIX = "processed"

_PROCESSED_HEADER = [
    "ProjectId",
    "NodeType",         # PROJECT / FOLDER / FILE
    "OBJECT_ID",
    "TDMX_ID",
    "Reference",        # PROJECT: CN_REFERENCE_PROJECT | FOLDER/FILE: TDMX_CAD_IDENTIFIER
    "CADRefFileName",   # FILE: CAD_REF_FILE_NAME | empty for PROJECT/FOLDER
    "Description",      # TDMX description / Description
    "FILE_NAME",
    "FileExtension",    # e.g. .pdf / .CATDrawing (blank for folders/projects)
    "FILE_SIZE",        # raw bytes from Documents_Tree (blank for folders)
    "FILE_SIZE_DISPLAY",# human-readable size from Documents_Tree
    "REVISION",
    "Path",             # source/tree path from JSON
    "SharePointPath",   # where it was created/uploaded
    "Status",           # Success / Failure / Skipped(...)
    "Detail",           # optional extra note (reason, "duplicate", etc.)
    "ExtractTimestamp", # when SmarTeam extracted the doc (carried from JSON)
    "UploadTimestamp",  # when GraphAPI processed/uploaded this row (local time)
]


def _processed_csv_path():
    pid = _current_project_id or "unknown"
    name = f"{PROCESSED_PREFIX}_{pid}_{_RUN_ID}.csv"
    return os.path.join(LOG_DIR, name) if LOG_DIR else name


def log_processed(node, node_type, status, sharepoint_path="", detail=""):
    """
    Append a processed-node record to processed_<projectId>.csv.

    node           : the JSON node dict
    node_type      : PROJECT / FOLDER / FILE
    status         : "Success" / "Failure" / "Skipped(...)" etc.
    sharepoint_path: created folder path or uploaded file path
    detail         : optional extra note

    Two timestamps are recorded:
      - ExtractTimestamp: taken from the node (set by SmarTeam at extract)
      - UploadTimestamp : now (when GraphAPI handled this row)
    """
    node = node or {}
    path = _processed_csv_path()

    upload_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Reference column by node type:
    #   PROJECT      -> CN_REFERENCE_PROJECT
    #   FOLDER/FILE  -> TDMX_CAD_IDENTIFIER
    nt = (node_type or "").upper()
    if nt == "PROJECT":
        reference = node.get("CN_REFERENCE_PROJECT", "") or ""
    else:  # FOLDER or FILE
        reference = node.get("TDMX_CAD_IDENTIFIER", "") or ""

    # CADRefFileName column: only for FILE (documents); empty otherwise
    if nt == "FILE":
        cad_ref_file_name = node.get("CAD_REF_FILE_NAME", "") or ""
    else:
        cad_ref_file_name = ""

    # File extension (only meaningful for files), e.g. ".pdf" / ".CATDrawing"
    file_name = node.get("FILE_NAME", "") or ""
    file_ext = os.path.splitext(file_name)[1] if file_name else ""

    row = [
        _current_project_id or "",
        node_type,
        _node_object_id(node),
        _node_tdmx_id(node),
        reference,
        cad_ref_file_name,
        node.get("Description")
            or node.get("TDM_DESCRIPTION")
            or node.get("TDMX_DESCRIPTION")
            or "",
        file_name,
        file_ext,
        node.get("FILE_SIZE", ""),
        node.get("FILE_SIZE_DISPLAY", ""),
        node.get("REVISION", ""),
        node.get("Path", ""),
        sharepoint_path,
        status,
        detail,
        node.get("ExtractTimestamp", ""),
        upload_ts,
    ]

    try:
        if LOG_DIR and LOG_DIR not in (".", ""):
            os.makedirs(LOG_DIR, exist_ok=True)
        with _csv_lock:
            with open(path, "a", newline="", encoding="utf-8-sig") as f:
                # Semicolon-separated (instead of comma) per requirement
                w = csv.writer(f, delimiter=";")
                if f.tell() == 0:   # header only when file is empty/new
                    w.writerow(_PROCESSED_HEADER)
                w.writerow(row)
    except Exception as e:
        log(f"⚠️ Could not write processed record: {e}")


def load_done_paths(project_id, done_statuses=("Success", "Skipped(Duplicate)")):
    """
    For --resume: scan ALL prior processed_<project_id>_*.csv files in
    LOG_DIR and return a set of SharePointPath values whose Status is in
    done_statuses. These are the nodes (folders + files) already handled
    by previous runs, so the current run can skip them.

    The current run's own processed CSV (named with this run's _RUN_ID)
    won't exist yet when this is called at startup, so it's naturally
    excluded. Matching is exact on the SharePointPath column, which for
    files already includes the filename.
    """
    pid = str(project_id) if project_id is not None else "unknown"
    # Prior runs may have used either naming scheme:
    #   processed_<pid>.csv            (old: no run-id)
    #   processed_<pid>_<runid>.csv    (new: per-run)
    # Match BOTH so a crash on the old code can still be resumed.
    exact = f"{PROCESSED_PREFIX}_{pid}.csv"
    prefix = f"{PROCESSED_PREFIX}_{pid}_"
    folder = LOG_DIR if LOG_DIR else "."

    done = set()
    current_run_file = f"{PROCESSED_PREFIX}_{pid}_{_RUN_ID}.csv"
    try:
        names = [
            n for n in os.listdir(folder)
            if n.endswith(".csv")
            and (n == exact or n.startswith(prefix))
            and n != current_run_file        # never read our own output
        ]
    except FileNotFoundError:
        names = []

    for name in names:
        full = os.path.join(folder, name) if folder else name
        try:
            with open(full, "r", encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f, delimiter=";"):
                    if (row.get("Status") or "").strip() in done_statuses:
                        sp = (row.get("SharePointPath") or "").strip()
                        if sp:
                            done.add(sp)
        except Exception as e:
            log(f"⚠️ Could not read prior processed file {name}: {e}")

    log(f"🔁 Resume: loaded {len(done)} already-done paths "
        f"from {len(names)} prior processed file(s) for {pid}")
    return done


def log_not_reached(csv_row):
    """
    Log a Documents_Tree CSV row that was never visited by the builder.
    Maps the CSV columns (comma-separated, SmarTeam output) to the
    processed CSV format and writes status="Not reached".

    csv_row: dict from csv.DictReader of Documents_Tree_<id>.csv
    """
    has_root = bool((csv_row.get("ROOT_DIR_ON_SERVER") or "").strip())
    node_type = "FILE" if has_root else "FOLDER"

    # Map Documents_Tree CSV columns -> processed node dict
    node = {
        "OBJECT_ID":          csv_row.get("DocObjectId", ""),
        "TDMX_ID":            csv_row.get("TDMX_ID", ""),
        "Description":        csv_row.get("Description", ""),
        "FILE_NAME":          csv_row.get("FILE_NAME", ""),
        "CAD_REF_FILE_NAME":  csv_row.get("CAD_REF_FILE_NAME", ""),
        "REVISION":           csv_row.get("REVISION", ""),
        "FILE_SIZE":          csv_row.get("FILE_SIZE", ""),
        "FILE_SIZE_DISPLAY":  "",      # not in Documents_Tree CSV
        "Path":               csv_row.get("DocPath", ""),
        "ExtractTimestamp":   csv_row.get("ExtractTimestamp", ""),
        "TDMX_CAD_IDENTIFIER":csv_row.get("TDMX_CAD_IDENTIFIER", ""),
        "CN_REFERENCE_PROJECT": "",    # not a project node
    }

    log_processed(
        node,
        node_type=node_type,
        status="Not reached",
        sharepoint_path=csv_row.get("UploadPath", ""),
        detail="In Documents_Tree CSV but not visited by builder (not in JSON tree or parent failed)",
    )


# =========================================================
# Upload / processing counter
# =========================================================

_count_lock = threading.Lock()


def increment_processed():
    """Increment the global processed counter and return new value.
    Thread-safe for concurrent uploads."""
    global _processed_count
    with _count_lock:
        _processed_count += 1
        return _processed_count


def get_processed_count():
    with _count_lock:
        return _processed_count


def reset_processed_count():
    global _processed_count
    _processed_count = 0


# =========================================================
# Document tree counter
# =========================================================

def count_document_tree(node):
    """
    Recursively count nodes in a document tree.
    Returns (total, files, folders).

    Uses metadata.get_type() to classify each node — same logic
    used by builder.process(), so the count matches what is processed.
    """

    total = 0
    files = 0
    folders = 0

    if not isinstance(node, dict):
        return total, files, folders

    total = 1

    # Lazy import to avoid any chance of circular import
    try:
        from metadata import get_type
        nt = get_type(node)
    except Exception:
        nt = None

    if nt == "FILE":
        files = 1
    elif nt == "FOLDER":
        folders = 1

    children = (
        node.get("Children")
        or node.get("children")
        or []
    )

    for child in children:
        t, f, fd = count_document_tree(child)
        total += t
        files += f
        folders += fd

    return total, files, folders


def count_document_json(document_json):
    """
    Count total/files/folders across an entire document JSON payload
    (either a single dict with 'Documents' key or a list of such dicts).
    Returns (total, files, folders).
    """

    total = 0
    files = 0
    folders = 0

    def _walk_payload(payload):
        nonlocal total, files, folders

        if isinstance(payload, list):
            for root in payload:
                _walk_payload(root)
            return

        if not isinstance(payload, dict):
            return

        documents = payload.get("Documents", [])

        for doc_node in documents:
            t, f, fd = count_document_tree(doc_node)
            total += t
            files += f
            folders += fd

    _walk_payload(document_json)

    return total, files, folders
