"""AI-powered directory analysis using the Claude API (stdlib only)."""

import json
import os
import sys
import urllib.request
import urllib.error

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"
MAX_FILE_SAMPLE_BYTES = 2048
MAX_FILES_TO_SAMPLE = 30


def _get_api_key():
    """Read the Anthropic API key from the environment."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("Warning: ANTHROPIC_API_KEY not set. Skipping AI analysis.",
              file=sys.stderr)
    return key


def _sample_file(path, max_bytes=MAX_FILE_SAMPLE_BYTES):
    """Read the first max_bytes of a text file. Returns None for binary."""
    try:
        with open(path, "r", errors="replace") as f:
            return f.read(max_bytes)
    except (OSError, UnicodeDecodeError):
        return None


def _build_context(report, target):
    """Build a textual context from the scan report for the AI prompt."""
    parts = []

    parts.append(f"Directory: {target}")
    parts.append("")

    # Tree structure
    tree_text = report.get("tree_rendered", "")
    if tree_text:
        parts.append("=== Directory tree ===")
        parts.append(tree_text)
        parts.append("")

    # File categories
    cats = report.get("file_categories", {})
    if cats:
        parts.append("=== File categories ===")
        for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
            parts.append(f"  {cat}: {count}")
        parts.append("")

    # Languages
    langs = report.get("languages", [])
    loc = report.get("lines_of_code", {})
    if langs:
        parts.append("=== Languages detected ===")
        for lang in sorted(loc, key=loc.get, reverse=True):
            parts.append(f"  {lang}: {loc[lang]} lines")
        parts.append("")

    # Sample file contents
    classified = report.get("classified_files", [])
    # Prioritize source and config files for sampling
    priority = {"source": 0, "config": 1, "document": 2, "data": 3}
    samplable = sorted(classified,
                       key=lambda f: priority.get(f["category"], 99))
    sampled = 0
    samples = []
    for f in samplable:
        if sampled >= MAX_FILES_TO_SAMPLE:
            break
        content = _sample_file(f["path"])
        if content and content.strip():
            rel = os.path.relpath(f["path"], target)
            samples.append(f"--- {rel} ---\n{content}")
            sampled += 1

    if samples:
        parts.append("=== File samples (first ~2KB each) ===")
        parts.append("\n\n".join(samples))

    return "\n".join(parts)


def _call_claude(api_key, context):
    """Call the Claude API and return the response text."""
    prompt = (
        "You are analyzing a directory on a file system. Based on the tree "
        "structure, file types, languages, and file content samples below, "
        "produce two sections:\n\n"
        "1. **BRIEF SUMMARY** (2-4 sentences): What is this directory? What is "
        "its purpose? What kind of project or data does it contain?\n\n"
        "2. **DETAILED BREAKDOWN**: A thorough analysis covering:\n"
        "   - The overall purpose and architecture of the project/directory\n"
        "   - Key components and what they do\n"
        "   - Technologies and frameworks in use\n"
        "   - Notable patterns, conventions, or design decisions\n"
        "   - Any potential concerns (e.g., missing tests, large binaries, "
        "stale files)\n\n"
        "Format your response exactly as:\n"
        "BRIEF: <your brief summary>\n\n"
        "DETAILED:\n<your detailed breakdown>\n\n"
        "Be specific and concrete — reference actual filenames and directories. "
        "Do not hedge or use filler phrases."
    )

    body = json.dumps({
        "model": MODEL,
        "max_tokens": 2048,
        "messages": [
            {"role": "user", "content": f"{prompt}\n\n{context}"},
        ],
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            # Extract text from the response
            for block in data.get("content", []):
                if block.get("type") == "text":
                    return block["text"]
            return ""
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"Warning: Claude API error {e.code}: {body}", file=sys.stderr)
        return ""
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        print(f"Warning: Claude API request failed: {e}", file=sys.stderr)
        return ""


def _parse_response(text):
    """Parse the AI response into brief and detailed sections."""
    brief = ""
    detailed = ""

    if "BRIEF:" in text:
        after_brief = text.split("BRIEF:", 1)[1]
        if "DETAILED:" in after_brief:
            brief = after_brief.split("DETAILED:", 1)[0].strip()
            detailed = after_brief.split("DETAILED:", 1)[1].strip()
        else:
            brief = after_brief.strip()
    elif "DETAILED:" in text:
        detailed = text.split("DETAILED:", 1)[1].strip()
    else:
        # Fallback: use the whole thing as brief
        brief = text.strip()

    return brief, detailed


def analyze_directory(report, target):
    """Run AI analysis on the directory. Returns (brief, detailed) strings.

    Returns ("", "") if the API key is missing or the request fails.
    """
    api_key = _get_api_key()
    if not api_key:
        return "", ""

    print("  [AI] Analyzing directory with Claude...", file=sys.stderr)
    context = _build_context(report, target)
    raw = _call_claude(api_key, context)
    if not raw:
        return "", ""

    return _parse_response(raw)
