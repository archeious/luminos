#!/usr/bin/env python3
"""Luminos — file system intelligence tool."""

import argparse
import json
import sys
import os

from luminos_lib.tree import build_tree, render_tree
from luminos_lib.filetypes import classify_files, summarize_categories
from luminos_lib.code import detect_languages, find_large_files
from luminos_lib.recency import find_recent_files
from luminos_lib.disk import get_disk_usage, top_directories
from luminos_lib.watch import watch_loop
from luminos_lib.report import format_report
from luminos_lib.ai import analyze_directory


def scan(target, depth=3, show_hidden=False):
    """Run all analyses on the target directory and return a report dict."""
    report = {}

    tree = build_tree(target, max_depth=depth, show_hidden=show_hidden)
    report["tree"] = tree
    report["tree_rendered"] = render_tree(tree)

    classified = classify_files(target, show_hidden=show_hidden)
    report["file_categories"] = summarize_categories(classified)
    report["classified_files"] = classified

    languages, loc = detect_languages(classified)
    report["languages"] = languages
    report["lines_of_code"] = loc
    report["large_files"] = find_large_files(classified)

    report["recent_files"] = find_recent_files(target, show_hidden=show_hidden)

    usage = get_disk_usage(target, show_hidden=show_hidden)
    report["disk_usage"] = usage
    report["top_directories"] = top_directories(usage, n=5)

    return report


def main():
    parser = argparse.ArgumentParser(
        prog="luminos",
        description="Luminos — file system intelligence tool. "
                    "Explores a directory and produces a reconnaissance report.",
    )
    parser.add_argument("target", help="Target directory to analyze")
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

    args = parser.parse_args()

    target = os.path.abspath(args.target)
    if not os.path.isdir(target):
        print(f"Error: '{args.target}' is not a directory or does not exist.",
              file=sys.stderr)
        sys.exit(1)

    if args.watch:
        watch_loop(target, depth=args.depth, show_hidden=args.all,
                   json_output=args.json_output)
        return

    report = scan(target, depth=args.depth, show_hidden=args.all)

    if args.ai:
        brief, detailed = analyze_directory(report, target)
        report["ai_brief"] = brief
        report["ai_detailed"] = detailed

    if args.json_output:
        output = json.dumps(report, indent=2, default=str)
    else:
        output = format_report(report, target)

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
