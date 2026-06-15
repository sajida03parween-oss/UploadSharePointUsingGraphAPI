import os
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

_buffer = []                   # Pending formatted lines (not yet on disk)

_current_log_file = None       # Path of the active log file
_lines_in_current_file = 0     # How many lines already written to it

_processed_count = 0           # Global "files processed" counter


# =========================================================
# Filename helpers
# =========================================================

def _new_log_filename():
    """
    Build a fresh log filename of the form log_<YYYY-MM-DD_HH-MM-SS>.txt
    in LOG_DIR. If a file with that name already exists (e.g. a fast
    rotation within the same second), suffix with _part2, _part3, ...
    """

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    base_name = f"{LOG_FILE_PREFIX}_{ts}.txt"

    base_path = (
        os.path.join(LOG_DIR, base_name)
        if LOG_DIR else base_name
    )

    if not os.path.exists(base_path):
        return base_path

    # Collision — append a counter
    i = 2
    while True:
        alt = base_path[:-4] + f"_part{i}.txt"
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
# Upload / processing counter
# =========================================================

def increment_processed():
    """Increment the global processed counter and return new value."""
    global _processed_count
    _processed_count += 1
    return _processed_count


def get_processed_count():
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
