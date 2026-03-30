"""Disk usage summary using du."""

import subprocess


def get_disk_usage(target, show_hidden=False):
    """Get per-directory disk usage via du.

    Returns a list of dicts: {path, size_bytes, size_human}.
    """
    cmd = ["du", "-b", "--max-depth=2", target]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    entries = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        try:
            size = int(parts[0])
        except ValueError:
            continue
        path = parts[1]

        # Skip hidden directories if not requested
        if not show_hidden:
            segments = path.replace(target, "").split("/")
            if any(s.startswith(".") and s != "." for s in segments):
                continue

        entries.append({
            "path": path,
            "size_bytes": size,
            "size_human": _human_size(size),
        })

    return entries


def _human_size(nbytes):
    """Convert bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if nbytes < 1024:
            if unit == "B":
                return f"{nbytes} {unit}"
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} PB"


def top_directories(usage, n=5):
    """Return the top n largest directories from usage data."""
    # Exclude the root entry (last line of du is usually the total)
    sorted_entries = sorted(usage, key=lambda x: x["size_bytes"], reverse=True)
    return sorted_entries[:n]
