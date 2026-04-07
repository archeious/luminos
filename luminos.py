#!/usr/bin/env python3
"""Luminos — file system intelligence tool."""

import argparse
import json
import os
import shutil
import sys

from luminos_lib.tree import build_tree, render_tree
from luminos_lib.filetypes import (
    classify_files,
    summarize_categories,
    survey_signals,
)
from luminos_lib.code import detect_languages, find_large_files
from luminos_lib.recency import find_recent_files
from luminos_lib.disk import get_disk_usage, top_directories
from luminos_lib.watch import watch_loop
from luminos_lib.report import format_report


def _progress(label):
    """Return (on_file, finish) for in-place per-file progress on stderr.

    on_file(path) overwrites the current line with the label and truncated path.
    finish() finalises the line with a newline.
    """
    cols = shutil.get_terminal_size((80, 20)).columns
    prefix = f"  [scan] {label}... "
    available = max(cols - len(prefix), 10)

    def on_file(path):
        rel = os.path.relpath(path)
        if len(rel) > available:
            rel = "..." + rel[-(available - 3):]
        print(f"\r{prefix}{rel}\033[K", end="", file=sys.stderr, flush=True)

    def finish():
        print(f"\r{prefix}done\033[K", file=sys.stderr, flush=True)

    return on_file, finish


def scan(target, depth=3, show_hidden=False, exclude=None):
    """Run all analyses on the target directory and return a report dict."""
    report = {}

    exclude = exclude or []

    print(f"  [scan] Building directory tree (depth={depth})...", file=sys.stderr)
    tree = build_tree(target, max_depth=depth, show_hidden=show_hidden,
                      exclude=exclude)
    report["tree"] = tree
    report["tree_rendered"] = render_tree(tree)

    on_file, finish = _progress("Classifying files")
    classified = classify_files(target, show_hidden=show_hidden,
                                exclude=exclude, on_file=on_file)
    finish()
    report["file_categories"] = summarize_categories(classified)
    report["classified_files"] = classified
    report["survey_signals"] = survey_signals(classified)

    on_file, finish = _progress("Counting lines")
    languages, loc = detect_languages(classified, on_file=on_file)
    finish()
    report["languages"] = languages
    report["lines_of_code"] = loc

    on_file, finish = _progress("Checking for large files")
    report["large_files"] = find_large_files(classified, on_file=on_file)
    finish()

    print("  [scan] Finding recently modified files...", file=sys.stderr)
    report["recent_files"] = find_recent_files(target, show_hidden=show_hidden,
                                               exclude=exclude)

    print("  [scan] Calculating disk usage...", file=sys.stderr)
    usage = get_disk_usage(target, show_hidden=show_hidden, exclude=exclude)
    report["disk_usage"] = usage
    report["top_directories"] = top_directories(usage, n=5)

    print("  [scan] Base scan complete.", file=sys.stderr)
    return report


def main():
    parser = argparse.ArgumentParser(
        prog="luminos",
        description="Luminos — file system intelligence tool. "
                    "Explores a directory and produces a reconnaissance report.",
    )
    parser.add_argument("target", nargs="?", help="Target directory to analyze")
    parser.add_argument("-d", "--depth", type=int, default=3,
                        help="Maximum tree depth (default: 3)")
    parser.add_argument("-a", "--all", action="store_true",
                        help="Include hidden files and directories")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output report as JSON")
    parser.add_argument("-o", "--output", metavar="FILE",
                        help="Write report to a file")
    parser.add_argument("--ai", action="store_true",
                        help="Use Claude AI to analyze directory purpose "
                             "(requires ANTHROPIC_API_KEY)")
    parser.add_argument("--watch", action="store_true",
                        help="Re-scan every 30 seconds and show diffs")
    parser.add_argument("--clear-cache", action="store_true",
                        help="Clear the AI investigation cache (/tmp/luminos/)")
    parser.add_argument("--fresh", action="store_true",
                        help="Force a new AI investigation (ignore cached results)")
    parser.add_argument("--install-extras", action="store_true",
                        help="Show status of optional AI dependencies")
    parser.add_argument("-x", "--exclude", metavar="DIR", action="append",
                        default=[],
                        help="Exclude a directory name from scan and analysis "
                             "(repeatable, e.g. -x .git -x node_modules)")

    args = parser.parse_args()

    # --install-extras: show package status and exit
    if args.install_extras:
        from luminos_lib.capabilities import print_status
        print_status()
        return

    # --clear-cache: wipe /tmp/luminos/ (lazy import to avoid AI deps)
    if args.clear_cache:
        from luminos_lib.capabilities import clear_cache
        clear_cache()
        if not args.target:
            return

    if not args.target:
        parser.error("the following arguments are required: target")

    target = os.path.abspath(args.target)
    if not os.path.isdir(target):
        print(f"Error: '{args.target}' is not a directory or does not exist.",
              file=sys.stderr)
        sys.exit(1)

    if args.exclude:
        print(f"  [scan] Excluding: {', '.join(args.exclude)}", file=sys.stderr)

    if args.watch:
        watch_loop(target, depth=args.depth, show_hidden=args.all,
                   json_output=args.json_output)
        return

    report = scan(target, depth=args.depth, show_hidden=args.all,
                  exclude=args.exclude)

    flags = []
    if args.ai:
        from luminos_lib.ai import analyze_directory
        brief, detailed, flags = analyze_directory(
            report, target, fresh=args.fresh, exclude=args.exclude)
        report["ai_brief"] = brief
        report["ai_detailed"] = detailed
        report["flags"] = flags

    if args.json_output:
        output = json.dumps(report, indent=2, default=str)
    else:
        output = format_report(report, target, flags=flags)

    if args.output:
        try:
            with open(args.output, "w") as f:
                f.write(output + "\n")
            print(f"Report written to {args.output}")
        except OSError as e:
            print(f"Error writing to '{args.output}': {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(output)


if __name__ == "__main__":
    main()
