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


def classify_files(target, show_hidden=False, exclude=None, on_file=None):
    exclude = exclude or []
    """Walk the target directory and classify every file.

    Returns a list of dicts: {path, name, category, size, description}.
    on_file(path) is called after each file is classified, if provided.
    """
    results = []
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs
                   if d not in exclude
                   and (show_hidden or not d.startswith("."))]
        if not show_hidden:
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


_SURVEY_TOP_N = 20
_SURVEY_DESC_TRUNCATE = 80


def survey_signals(classified, max_samples=20):
    """Return raw, unbucketed signals for the AI survey pass.

    Unlike `summarize_categories`, which collapses files into a small
    biased taxonomy, this exposes the primary signals so the survey
    LLM can characterize the target without being misled by the
    classifier's source-code bias.

    See #42 for the rationale and #48 for the unit-of-analysis
    limitation: the unit here is still "file" — containers like mbox,
    SQLite, and zip will under-count, while dense file collections like
    Maildir will over-count.

    Returns a dict with:
      total_files       — total count
      extension_histogram — {ext: count}, top _SURVEY_TOP_N by count
      file_descriptions — {description: count}, top _SURVEY_TOP_N by count
      filename_samples  — up to max_samples filenames, evenly drawn
    """
    total = len(classified)

    ext_counts = {}
    desc_counts = {}
    for f in classified:
        ext = os.path.splitext(f.get("name", ""))[1].lower() or "(none)"
        ext_counts[ext] = ext_counts.get(ext, 0) + 1

        desc = (f.get("description") or "").strip()
        if desc:
            if len(desc) > _SURVEY_DESC_TRUNCATE:
                desc = desc[:_SURVEY_DESC_TRUNCATE] + "..."
            desc_counts[desc] = desc_counts.get(desc, 0) + 1

    def _top(d):
        items = sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))
        return dict(items[:_SURVEY_TOP_N])

    if total > 0 and max_samples > 0:
        if total <= max_samples:
            samples = [f.get("name", "") for f in classified]
        else:
            stride = total / max_samples
            samples = [
                classified[int(i * stride)].get("name", "")
                for i in range(max_samples)
            ]
    else:
        samples = []

    return {
        "total_files": total,
        "extension_histogram": _top(ext_counts),
        "file_descriptions": _top(desc_counts),
        "filename_samples": samples,
    }
