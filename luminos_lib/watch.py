"""Watch mode — re-scan and show diffs every 30 seconds."""

import json
import sys
import time
import os


def _snapshot(classified_files):
    """Create a snapshot dict: path -> (size, category)."""
    return {f["path"]: (f["size"], f["category"]) for f in classified_files}


def _diff_snapshots(old, new):
    """Compare two snapshots and return changes."""
    old_paths = set(old.keys())
    new_paths = set(new.keys())

    added = new_paths - old_paths
    removed = old_paths - new_paths
    common = old_paths & new_paths

    size_changes = []
    for p in common:
        old_size = old[p][0]
        new_size = new[p][0]
        if old_size != new_size:
            size_changes.append((p, old_size, new_size))

    return added, removed, size_changes


def _human_size(nbytes):
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            if unit == "B":
                return f"{nbytes} {unit}"
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def watch_loop(target, depth=3, show_hidden=False, json_output=False):
    """Run scan in a loop, printing diffs between runs."""
    # Import here to avoid circular import
    from luminos_lib.filetypes import classify_files

    print(f"[luminos] Watching {target} (Ctrl+C to stop)")
    print(f"[luminos] Scanning every 30 seconds...")
    print()

    prev_snapshot = None

    try:
        while True:
            classified = classify_files(target, show_hidden=show_hidden)
            current = _snapshot(classified)

            if prev_snapshot is not None:
                added, removed, size_changes = _diff_snapshots(
                    prev_snapshot, current
                )

                if not added and not removed and not size_changes:
                    ts = time.strftime("%H:%M:%S")
                    print(f"[{ts}] No changes detected.")
                else:
                    ts = time.strftime("%H:%M:%S")
                    print(f"[{ts}] Changes detected:")

                    if json_output:
                        diff = {
                            "timestamp": ts,
                            "added": sorted(added),
                            "removed": sorted(removed),
                            "size_changes": [
                                {"path": p, "old_size": o, "new_size": n}
                                for p, o, n in size_changes
                            ],
                        }
                        print(json.dumps(diff, indent=2))
                    else:
                        for p in sorted(added):
                            name = os.path.basename(p)
                            print(f"  + NEW  {name}")
                            print(f"         {p}")
                        for p in sorted(removed):
                            name = os.path.basename(p)
                            print(f"  - DEL  {name}")
                            print(f"         {p}")
                        for p, old_s, new_s in size_changes:
                            name = os.path.basename(p)
                            delta = new_s - old_s
                            sign = "+" if delta > 0 else ""
                            print(f"  ~ SIZE {name}  "
                                  f"{_human_size(old_s)} -> {_human_size(new_s)} "
                                  f"({sign}{_human_size(delta)})")
                    print()
            else:
                print(f"[{time.strftime('%H:%M:%S')}] "
                      f"Initial scan complete: {len(current)} files indexed.")
                print()

            prev_snapshot = current
            time.sleep(30)

    except KeyboardInterrupt:
        print("\n[luminos] Watch stopped.")
