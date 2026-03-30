"""Recency analysis — find most recently modified files."""

import subprocess
import os
from datetime import datetime


def find_recent_files(target, n=10, show_hidden=False):
    """Find the n most recently modified files using find and stat.

    Returns a list of dicts: {path, name, modified, modified_human}.
    """
    # Build find command
    cmd = ["find", target, "-type", "f"]
    if not show_hidden:
        cmd.extend(["-not", "-path", "*/.*"])
    cmd.extend(["-printf", "%T@\t%p\n"])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    if result.returncode != 0:
        return []

    # Parse and sort by timestamp descending
    entries = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        try:
            ts = float(parts[0])
        except ValueError:
            continue
        entries.append((ts, parts[1]))

    entries.sort(key=lambda x: x[0], reverse=True)

    recent = []
    for ts, path in entries[:n]:
        dt = datetime.fromtimestamp(ts)
        recent.append({
            "path": path,
            "name": os.path.basename(path),
            "modified": ts,
            "modified_human": dt.strftime("%Y-%m-%d %H:%M:%S"),
        })

    return recent
