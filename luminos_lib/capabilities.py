"""Capability detection and cache management for optional luminos dependencies.

The base tool requires zero external packages. The --ai flag requires:
  - anthropic       (API transport)
  - tree-sitter     (AST parsing via parse_structure tool)
  - python-magic    (improved file classification)

This module is the single place that knows about optional dependencies.
"""

_PACKAGES = {
    "anthropic": {
        "import": "anthropic",
        "pip": "anthropic",
        "purpose": "Claude API client (streaming, retries, token counting)",
    },
    "tree-sitter": {
        "import": "tree_sitter",
        "pip": ("tree-sitter tree-sitter-python tree-sitter-javascript "
                "tree-sitter-rust tree-sitter-go"),
        "purpose": "AST parsing for parse_structure tool",
    },
    "python-magic": {
        "import": "magic",
        "pip": "python-magic",
        "purpose": "Improved file type detection via libmagic",
    },
}


def _check_package(import_name):
    """Return True if a package is importable."""
    try:
        __import__(import_name)
        return True
    except ImportError:
        return False


ANTHROPIC_AVAILABLE = _check_package("anthropic")
TREE_SITTER_AVAILABLE = _check_package("tree_sitter")
MAGIC_AVAILABLE = _check_package("magic")


def check_ai_dependencies():
    """Check that all --ai dependencies are installed.

    If any are missing, prints a clear error with the pip install command
    and returns False. Returns True if everything is available.
    """
    missing = []
    for name, info in _PACKAGES.items():
        if not _check_package(info["import"]):
            missing.append(name)

    if not missing:
        return True

    # Also check tree-sitter grammar packages
    grammar_missing = []
    if "tree-sitter" not in missing:
        for grammar in ["tree_sitter_python", "tree_sitter_javascript",
                        "tree_sitter_rust", "tree_sitter_go"]:
            if not _check_package(grammar):
                grammar_missing.append(grammar.replace("_", "-"))

    import sys
    print("\nluminos --ai requires missing packages:", file=sys.stderr)
    for name in missing:
        print(f"  \u2717 {name}", file=sys.stderr)
    for name in grammar_missing:
        print(f"  \u2717 {name}", file=sys.stderr)

    # Build pip install command
    pip_parts = []
    for name in missing:
        pip_parts.append(_PACKAGES[name]["pip"])
    for name in grammar_missing:
        pip_parts.append(name)
    pip_cmd = " \\\n                ".join(pip_parts)

    print(f"\n  Install with:\n    pip install {pip_cmd}\n", file=sys.stderr)
    return False


def print_status():
    """Print the install status of all optional packages."""
    print("\nLuminos optional dependencies:\n")

    for name, info in _PACKAGES.items():
        available = _check_package(info["import"])
        mark = "\u2713" if available else "\u2717"
        status = "installed" if available else "missing"
        print(f"  {mark} {name:20s} {status:10s}  {info['purpose']}")

    # Grammar packages
    grammars = {
        "tree-sitter-python": "tree_sitter_python",
        "tree-sitter-javascript": "tree_sitter_javascript",
        "tree-sitter-rust": "tree_sitter_rust",
        "tree-sitter-go": "tree_sitter_go",
    }
    print()
    for name, imp in grammars.items():
        available = _check_package(imp)
        mark = "\u2713" if available else "\u2717"
        status = "installed" if available else "missing"
        print(f"  {mark} {name:20s} {status:10s}  Language grammar")

    # Full install command (deduplicated)
    all_pkgs = []
    seen = set()
    for info in _PACKAGES.values():
        for pkg in info["pip"].split():
            if pkg not in seen:
                all_pkgs.append(pkg)
                seen.add(pkg)
    for name in grammars:
        if name not in seen:
            all_pkgs.append(name)
            seen.add(name)

    print(f"\n  Install all with:\n    pip install {' '.join(all_pkgs)}\n")


from luminos_lib.cache import CACHE_ROOT


def clear_cache():
    """Remove all investigation caches under /tmp/luminos/."""
    import shutil
    import os
    import sys
    if os.path.isdir(CACHE_ROOT):
        shutil.rmtree(CACHE_ROOT)
        print(f"Cleared cache: {CACHE_ROOT}", file=sys.stderr)
    else:
        print(f"No cache to clear ({CACHE_ROOT} does not exist).",
              file=sys.stderr)
