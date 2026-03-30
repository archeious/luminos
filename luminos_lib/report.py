"""Report formatting — human-readable terminal output."""


def format_report(report, target):
    """Format the full report as a human-readable string."""
    sep = "=" * 60
    lines = []

    lines.append(sep)
    lines.append(f"  LUMINOS — File System Intelligence Report")
    lines.append(f"  Target: {target}")
    lines.append(sep)

    # AI brief summary (top of report)
    ai_brief = report.get("ai_brief", "")
    if ai_brief:
        lines.append("")
        lines.append(">> SUMMARY (AI)")
        lines.append("-" * 40)
        for paragraph in ai_brief.split("\n"):
            lines.append(f"  {paragraph}")

    # Directory tree
    lines.append("")
    lines.append(">> DIRECTORY TREE")
    lines.append("-" * 40)
    lines.append(report.get("tree_rendered", "(unavailable)"))

    # File type summary
    lines.append("")
    lines.append(">> FILE TYPE INTELLIGENCE")
    lines.append("-" * 40)
    cats = report.get("file_categories", {})
    if cats:
        total = sum(cats.values())
        for cat in sorted(cats, key=cats.get, reverse=True):
            count = cats[cat]
            bar = "#" * min(count, 40)
            lines.append(f"  {cat:<12} {count:>4}  {bar}")
        lines.append(f"  {'TOTAL':<12} {total:>4}")
    else:
        lines.append("  No files found.")

    # Languages & LOC
    lines.append("")
    lines.append(">> CODE DETECTION")
    lines.append("-" * 40)
    langs = report.get("languages", [])
    loc = report.get("lines_of_code", {})
    if langs:
        lines.append(f"  Languages detected: {', '.join(langs)}")
        lines.append("")
        lines.append("  Lines of code:")
        for lang in sorted(loc, key=loc.get, reverse=True):
            lines.append(f"    {lang:<20} {loc[lang]:>8} lines")
        lines.append(f"    {'TOTAL':<20} {sum(loc.values()):>8} lines")
    else:
        lines.append("  No source code files detected.")

    large = report.get("large_files", [])
    if large:
        lines.append("")
        lines.append("  Unusually large files:")
        for f in large:
            lines.append(f"    ! {f['name']}  ({', '.join(f['reasons'])})")

    # Recency
    lines.append("")
    lines.append(">> RECENTLY MODIFIED FILES")
    lines.append("-" * 40)
    recent = report.get("recent_files", [])
    if recent:
        for i, f in enumerate(recent, 1):
            lines.append(f"  {i:>2}. {f['modified_human']}  {f['name']}")
            lines.append(f"      {f['path']}")
    else:
        lines.append("  No recent files found.")

    # Disk usage
    lines.append("")
    lines.append(">> DISK USAGE — TOP DIRECTORIES")
    lines.append("-" * 40)
    top = report.get("top_directories", [])
    if top:
        for d in top:
            lines.append(f"  {d['size_human']:>10}  {d['path']}")
    else:
        lines.append("  No usage data available.")

    # AI detailed breakdown (end of report)
    ai_detailed = report.get("ai_detailed", "")
    if ai_detailed:
        lines.append("")
        lines.append(">> DETAILED AI ANALYSIS")
        lines.append("-" * 40)
        for paragraph in ai_detailed.split("\n"):
            lines.append(f"  {paragraph}")

    lines.append("")
    lines.append(sep)
    lines.append("  End of report.")
    lines.append(sep)

    return "\n".join(lines)
