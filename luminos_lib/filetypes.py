"""File type intelligence — classify files by category."""

import os
import subprocess

# Extension-based classification
EXTENSION_MAP = {
    # Source code
    ".py": "source", ".js": "source", ".ts": "source", ".jsx": "source",
    ".tsx": "source", ".java": "source", ".c": "source", ".cpp": "source",
    ".cc": "source", ".h": "source", ".hpp": "source", ".go": "source",
    ".rs": "source", ".rb": "source", ".php": "source", ".swift": "source",
    ".kt": "source", ".scala": "source", ".sh": "source", ".bash": "source",
    ".zsh": "source", ".pl": "source", ".lua": "source", ".r": "source",
    ".m": "source", ".cs": "source", ".hs": "source", ".ex": "source",
    ".exs": "source", ".erl": "source", ".clj": "source", ".vim": "source",
    ".el": "source", ".sql": "source",

    # Config
    ".json": "config", ".yaml": "config", ".yml": "config", ".toml": "config",
    ".ini": "config", ".cfg": "config", ".conf": "config", ".xml": "config",
    ".env": "config", ".properties": "config", ".editorconfig": "config",

    # Data
    ".csv": "data", ".tsv": "data", ".parquet": "data", ".sqlite": "data",
    ".db": "data", ".sql": "data", ".ndjson": "data", ".jsonl": "data",

    # Media
    ".png": "media", ".jpg": "media", ".jpeg": "media", ".gif": "media",
    ".svg": "media", ".bmp": "media", ".ico": "media", ".webp": "media",
    ".mp3": "media", ".wav": "media", ".mp4": "media", ".avi": "media",
    ".mkv": "media", ".mov": "media", ".flac": "media", ".ogg": "media",

    # Documents
    ".md": "document", ".txt": "document", ".rst": "document",
    ".pdf": "document", ".doc": "document", ".docx": "document",
    ".odt": "document", ".rtf": "document", ".tex": "document",
    ".html": "document", ".htm": "document", ".css": "document",

    # Archives
    ".zip": "archive", ".tar": "archive", ".gz": "archive",
    ".bz2": "archive", ".xz": "archive", ".7z": "archive",
    ".rar": "archive", ".tgz": "archive",
}

# Patterns from `file` command output
FILE_CMD_PATTERNS = {
    "text": "source",
    "script": "source",
    "program": "source",
    "JSON": "config",
    "XML": "config",
    "image": "media",
    "audio": "media",
    "video": "media",
    "PDF": "document",
    "document": "document",
    "archive": "archive",
    "compressed": "archive",
}


def _file_command(path):
    """Run `file --brief` on a path and return the output."""
    try:
        result = subprocess.run(
            ["file", "--brief", path],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _classify_one(filepath):
    """Classify a single file. Returns (category, file_description)."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext in EXTENSION_MAP:
        return EXTENSION_MAP[ext], None

    desc = _file_command(filepath)
    for pattern, category in FILE_CMD_PATTERNS.items():
        if pattern.lower() in desc.lower():
            return category, desc

    return "unknown", desc


def classify_files(target, show_hidden=False, on_file=None):
    """Walk the target directory and classify every file.

    Returns a list of dicts: {path, name, category, size, description}.
    on_file(path) is called after each file is classified, if provided.
    """
    results = []
    for root, dirs, files in os.walk(target):
        if not show_hidden:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            files = [f for f in files if not f.startswith(".")]
        for fname in files:
            full = os.path.join(root, fname)
            if not os.path.isfile(full):
                continue
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            category, desc = _classify_one(full)
            results.append({
                "path": full,
                "name": fname,
                "category": category,
                "size": size,
                "description": desc,
            })
            if on_file:
                on_file(full)
    return results


def summarize_categories(classified):
    """Return a dict of category -> count."""
    summary = {}
    for f in classified:
        cat = f["category"]
        summary[cat] = summary.get(cat, 0) + 1
    return summary
