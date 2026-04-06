"""Code detection — languages, line counts, large file flagging."""

import os
import subprocess

LANG_EXTENSIONS = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
    ".jsx": "JavaScript (JSX)", ".tsx": "TypeScript (TSX)",
    ".java": "Java", ".c": "C", ".cpp": "C++", ".cc": "C++",
    ".h": "C/C++ Header", ".hpp": "C++ Header",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".swift": "Swift", ".kt": "Kotlin", ".scala": "Scala",
    ".sh": "Shell", ".bash": "Bash", ".zsh": "Zsh",
    ".pl": "Perl", ".lua": "Lua", ".r": "R", ".m": "Objective-C",
    ".cs": "C#", ".hs": "Haskell", ".ex": "Elixir", ".exs": "Elixir",
    ".erl": "Erlang", ".clj": "Clojure", ".sql": "SQL",
}

LARGE_LINE_THRESHOLD = 1000
LARGE_SIZE_THRESHOLD = 10 * 1024 * 1024  # 10 MB


def _count_lines(filepath):
    """Count lines in a file using wc -l."""
    try:
        result = subprocess.run(
            ["wc", "-l", filepath],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return int(result.stdout.strip().split()[0])
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return 0


def detect_languages(classified_files, on_file=None):
    """Detect languages present and count lines of code per language.

    Returns (languages_set, loc_by_language).
    on_file(path) is called per source file, if provided.
    """
    source_files = [f for f in classified_files if f["category"] == "source"]
    languages = set()
    loc = {}

    for f in source_files:
        ext = os.path.splitext(f["name"])[1].lower()
        lang = LANG_EXTENSIONS.get(ext, "Other")
        languages.add(lang)
        lines = _count_lines(f["path"])
        loc[lang] = loc.get(lang, 0) + lines
        if on_file:
            on_file(f["path"])

    return sorted(languages), loc


def find_large_files(classified_files, on_file=None):
    """Find files that are unusually large (>1000 lines or >10MB).

    on_file(path) is called per source file checked, if provided.
    """
    source_files = [f for f in classified_files if f["category"] == "source"]
    large = []

    for f in source_files:
        reasons = []
        if f["size"] > LARGE_SIZE_THRESHOLD:
            reasons.append(f"size: {f['size'] / (1024*1024):.1f} MB")
        lines = _count_lines(f["path"])
        if lines > LARGE_LINE_THRESHOLD:
            reasons.append(f"lines: {lines}")
        if reasons:
            large.append({"path": f["path"], "name": f["name"],
                          "reasons": reasons})
        if on_file:
            on_file(f["path"])

    return large
