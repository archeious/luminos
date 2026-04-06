"""Directory tree visualization."""

import os


def build_tree(path, max_depth=3, show_hidden=False, exclude=None, _depth=0):
    exclude = exclude or []
    """Build a nested dict representing the directory tree with file sizes."""
    name = os.path.basename(path) or path
    node = {"name": name, "path": path, "type": "directory", "children": []}

    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        node["error"] = "permission denied"
        return node

    for entry in entries:
        if not show_hidden and entry.startswith("."):
            continue
        if entry in exclude:
            continue
        full = os.path.join(path, entry)
        if os.path.isdir(full):
            if _depth < max_depth:
                child = build_tree(full, max_depth, show_hidden, exclude, _depth + 1)
                node["children"].append(child)
            else:
                node["children"].append({
                    "name": entry, "path": full,
                    "type": "directory", "truncated": True,
                })
        elif os.path.isfile(full):
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            node["children"].append({
                "name": entry, "path": full,
                "type": "file", "size": size,
            })

    return node


def _human_size(nbytes):
    """Convert bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if nbytes < 1024:
            if unit == "B":
                return f"{nbytes} {unit}"
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} PB"


def render_tree(node, prefix="", is_last=True, is_root=True):
    """Render the tree dict as a visual string."""
    lines = []

    if is_root:
        lines.append(f"{node['name']}/")
    else:
        connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
        label = node["name"]
        if node["type"] == "file":
            label += f"  ({_human_size(node.get('size', 0))})"
        elif node.get("truncated"):
            label += "/  ..."
        elif node["type"] == "directory":
            label += "/"
        if node.get("error"):
            label += f"  [{node['error']}]"
        lines.append(prefix + connector + label)

    children = node.get("children", [])
    for i, child in enumerate(children):
        if is_root:
            child_prefix = ""
        else:
            child_prefix = prefix + ("    " if is_last else "\u2502   ")
        lines.append(
            render_tree(child, child_prefix, i == len(children) - 1, False)
        )

    return "\n".join(lines)
