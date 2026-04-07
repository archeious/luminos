"""AI-powered directory analysis using a multi-pass, cache-driven agent loop.

Architecture:
  1. Discover all directories under the target
  2. Sort leaves-first (deepest directories first)
  3. Run an isolated agent loop per directory (max 10 turns each)
  4. Cache every file and directory summary to disk
  5. Run a final synthesis pass reading only directory cache entries

Uses the Anthropic SDK for streaming, automatic retries, and token counting.
Uses tree-sitter for AST parsing and python-magic for file classification.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import anthropic
import magic
from luminos_lib.ast_parser import parse_structure
from luminos_lib.cache import _CacheManager, _get_investigation_id
from luminos_lib.capabilities import check_ai_dependencies
from luminos_lib.prompts import (
    _DIR_SYSTEM_PROMPT,
    _SURVEY_SYSTEM_PROMPT,
    _SYNTHESIS_SYSTEM_PROMPT,
)
from luminos_lib.tree import build_tree, render_tree

MODEL = "claude-sonnet-4-20250514"

# Context budget: trigger early exit at 70% of Sonnet's context window.
MAX_CONTEXT = 180_000
CONTEXT_BUDGET = int(MAX_CONTEXT * 0.70)

# Pricing per 1M tokens (Claude Sonnet).
INPUT_PRICE_PER_M = 3.00
OUTPUT_PRICE_PER_M = 15.00

# Directories to always skip during investigation.
_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".tox", ".mypy_cache",
    ".pytest_cache", ".venv", "venv", ".env", "dist", "build",
    ".eggs", "*.egg-info", ".svn", ".hg",
}

# Commands the run_command tool is allowed to execute.
_COMMAND_WHITELIST = {"wc", "file", "grep", "head", "tail", "stat", "du", "find"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_api_key():
    """Read the Anthropic API key from the environment."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("Warning: ANTHROPIC_API_KEY not set. Skipping AI analysis.",
              file=sys.stderr)
    return key


def _path_is_safe(path, target):
    """Return True if *path* resolves to somewhere inside *target*."""
    real = os.path.realpath(path)
    target_real = os.path.realpath(target)
    return real == target_real or real.startswith(target_real + os.sep)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _should_skip_dir(name):
    """Return True if a directory name matches the skip list."""
    if name in _SKIP_DIRS:
        return True
    for pattern in _SKIP_DIRS:
        if pattern.startswith("*") and name.endswith(pattern[1:]):
            return True
    return False


# ---------------------------------------------------------------------------
# Token tracker
# ---------------------------------------------------------------------------

class _TokenTracker:
    """Track cumulative token usage across API calls."""

    def __init__(self):
        self.total_input = 0
        self.total_output = 0
        self.loop_input = 0
        self.loop_output = 0

    def record(self, usage):
        """Record usage from a single API call."""
        inp = getattr(usage, "input_tokens", 0)
        out = getattr(usage, "output_tokens", 0)
        self.total_input += inp
        self.total_output += out
        self.loop_input += inp
        self.loop_output += out

    def reset_loop(self):
        """Reset per-loop counters (called between directory loops)."""
        self.loop_input = 0
        self.loop_output = 0

    @property
    def loop_total(self):
        return self.loop_input + self.loop_output

    def budget_exceeded(self):
        return self.loop_total > CONTEXT_BUDGET

    def summary(self):
        cost_in = self.total_input * INPUT_PRICE_PER_M / 1_000_000
        cost_out = self.total_output * OUTPUT_PRICE_PER_M / 1_000_000
        cost = cost_in + cost_out
        return (f"{self.total_input:,} input / {self.total_output:,} output "
                f"(approx ${cost:.2f})")


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

_DIR_TOOLS = [
    {
        "name": "read_file",
        "description": (
            "Read and return the contents of a file. Path must be inside "
            "the target directory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file.",
                },
                "max_bytes": {
                    "type": "integer",
                    "description": "Maximum bytes to read (default 4096).",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_directory",
        "description": (
            "List the contents of a directory with file sizes and types."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the directory.",
                },
                "show_hidden": {
                    "type": "boolean",
                    "description": "Include hidden files (default false).",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "run_command",
        "description": (
            "Run a read-only shell command. Allowed binaries: "
            "wc, file, grep, head, tail, stat, du, find."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "parse_structure",
        "description": (
            "Parse a source file using tree-sitter and return its structural "
            "skeleton: functions, classes, imports, and code metrics. "
            "Supported: Python, JavaScript, TypeScript, Rust, Go."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the source file to parse.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_cache",
        "description": (
            "Write a summary cache entry for a file or directory. The data "
            "must NOT contain raw file contents — summaries only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cache_type": {
                    "type": "string",
                    "enum": ["file", "dir"],
                    "description": "'file' or 'dir'.",
                },
                "path": {
                    "type": "string",
                    "description": "The path being cached.",
                },
                "data": {
                    "type": "object",
                    "description": (
                        "Cache entry. Files: {path, relative_path, size_bytes, "
                        "category, summary, notable, notable_reason, cached_at}. "
                        "Dirs: {path, relative_path, child_count, summary, "
                        "dominant_category, notable_files, cached_at}."
                    ),
                },
            },
            "required": ["cache_type", "path", "data"],
        },
    },
    {
        "name": "think",
        "description": (
            "Record your reasoning before choosing which file or directory "
            "to investigate next. Call this when deciding what to look at "
            "— not before every individual tool call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "observation": {
                    "type": "string",
                    "description": "What you have observed so far.",
                },
                "hypothesis": {
                    "type": "string",
                    "description": "Your hypothesis about the directory.",
                },
                "next_action": {
                    "type": "string",
                    "description": "What you plan to investigate next and why.",
                },
            },
            "required": ["observation", "hypothesis", "next_action"],
        },
    },
    {
        "name": "checkpoint",
        "description": (
            "Summarize what you have learned so far about this directory "
            "and what you still need to determine. Call this after completing "
            "a significant cluster of files — not after every file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "learned": {
                    "type": "string",
                    "description": "What you have learned so far.",
                },
                "still_unknown": {
                    "type": "string",
                    "description": "What you still need to determine.",
                },
                "next_phase": {
                    "type": "string",
                    "description": "What you will investigate next.",
                },
            },
            "required": ["learned", "still_unknown", "next_phase"],
        },
    },
    {
        "name": "flag",
        "description": (
            "Mark a file, directory, or finding as notable or anomalous. "
            "Call this immediately when you discover something surprising, "
            "concerning, or important — do not save it for the report."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path, or 'general'.",
                },
                "finding": {
                    "type": "string",
                    "description": "What you found.",
                },
                "severity": {
                    "type": "string",
                    "enum": ["info", "concern", "critical"],
                    "description": "info | concern | critical",
                },
            },
            "required": ["path", "finding", "severity"],
        },
    },
    {
        "name": "submit_report",
        "description": (
            "Submit the directory summary. This ends the investigation loop."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "1-3 sentence summary of the directory.",
                },
            },
            "required": ["summary"],
        },
    },
]

_SURVEY_TOOLS = [
    {
        "name": "submit_survey",
        "description": (
            "Submit the reconnaissance survey. Call exactly once."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Plain-language description of the target.",
                },
                "approach": {
                    "type": "string",
                    "description": "Recommended analytical approach.",
                },
                "relevant_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tool names the dir loop should lean on.",
                },
                "skip_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tool names whose use would be wrong here.",
                },
                "domain_notes": {
                    "type": "string",
                    "description": "Short actionable hint, or empty string.",
                },
                "confidence": {
                    "type": "number",
                    "description": "0.0–1.0 confidence in this survey.",
                },
            },
            "required": [
                "description", "approach", "relevant_tools",
                "skip_tools", "domain_notes", "confidence",
            ],
        },
    },
]


_SYNTHESIS_TOOLS = [
    {
        "name": "read_cache",
        "description": "Read a previously cached summary for a file or directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cache_type": {
                    "type": "string",
                    "enum": ["file", "dir"],
                },
                "path": {
                    "type": "string",
                    "description": "The path to look up.",
                },
            },
            "required": ["cache_type", "path"],
        },
    },
    {
        "name": "list_cache",
        "description": "List all cached entry paths of a given type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cache_type": {
                    "type": "string",
                    "enum": ["file", "dir"],
                },
            },
            "required": ["cache_type"],
        },
    },
    {
        "name": "flag",
        "description": (
            "Mark a file, directory, or finding as notable or anomalous. "
            "Call this immediately when you discover something surprising, "
            "concerning, or important — do not save it for the report."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path, or 'general'.",
                },
                "finding": {
                    "type": "string",
                    "description": "What you found.",
                },
                "severity": {
                    "type": "string",
                    "enum": ["info", "concern", "critical"],
                    "description": "info | concern | critical",
                },
            },
            "required": ["path", "finding", "severity"],
        },
    },
    {
        "name": "submit_report",
        "description": "Submit the final analysis report.",
        "input_schema": {
            "type": "object",
            "properties": {
                "brief": {
                    "type": "string",
                    "description": "2-4 sentence summary.",
                },
                "detailed": {
                    "type": "string",
                    "description": "Thorough breakdown.",
                },
            },
            "required": ["brief", "detailed"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _tool_read_file(args, target, _cache):
    path = args.get("path", "")
    max_bytes = args.get("max_bytes", 4096)
    if not os.path.isabs(path):
        path = os.path.join(target, path)
    if not _path_is_safe(path, target):
        return f"Error: path '{path}' is outside the target directory."
    try:
        file_size = os.path.getsize(path)
        with open(path, "r", errors="replace") as f:
            content = f.read(max_bytes)
        if not content:
            return "(empty file)"
        if file_size > max_bytes:
            content += (
                f"\n\n[TRUNCATED — showed {max_bytes} of {file_size} bytes. "
                f"Call again with a larger max_bytes or use "
                f"run_command('tail -n ... {os.path.relpath(path, target)}') "
                f"to see the rest.]"
            )
        return content
    except OSError as e:
        return f"Error reading file: {e}"


def _tool_list_directory(args, target, _cache):
    path = args.get("path", target)
    show_hidden = args.get("show_hidden", False)
    if not os.path.isabs(path):
        path = os.path.join(target, path)
    if not _path_is_safe(path, target):
        return f"Error: path '{path}' is outside the target directory."
    if not os.path.isdir(path):
        return f"Error: '{path}' is not a directory."
    try:
        entries = sorted(os.listdir(path))
        lines = []
        for name in entries:
            if not show_hidden and name.startswith("."):
                continue
            full = os.path.join(path, name)
            try:
                st = os.stat(full)
                mime = magic.from_file(full, mime=True) if not os.path.isdir(full) else None
                if os.path.isdir(full):
                    lines.append(f"  {name}/  (dir)")
                else:
                    mime_str = f"  [{mime}]" if mime else ""
                    lines.append(f"  {name}  ({st.st_size} bytes){mime_str}")
            except OSError:
                lines.append(f"  {name}  (stat failed)")
        return "\n".join(lines) if lines else "(empty directory)"
    except OSError as e:
        return f"Error listing directory: {e}"


def _tool_run_command(args, target, _cache):
    command = args.get("command", "")
    parts = command.split()
    if not parts:
        return "Error: empty command."
    binary = os.path.basename(parts[0])
    if binary not in _COMMAND_WHITELIST:
        return (
            f"Error: '{binary}' is not allowed. "
            f"Whitelist: {', '.join(sorted(_COMMAND_WHITELIST))}"
        )
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=15, cwd=target,
        )
        output = result.stdout
        if result.returncode != 0 and result.stderr:
            output += f"\n(stderr: {result.stderr.strip()})"
        return output.strip() if output.strip() else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 15 seconds."
    except OSError as e:
        return f"Error running command: {e}"


def _tool_parse_structure(args, target, _cache):
    path = args.get("path", "")
    if not os.path.isabs(path):
        path = os.path.join(target, path)
    if not _path_is_safe(path, target):
        return f"Error: path '{path}' is outside the target directory."
    return parse_structure(path)


def _tool_write_cache(args, _target, cache):
    cache_type = args.get("cache_type", "")
    path = args.get("path", "")
    data = args.get("data", {})
    if cache_type not in ("file", "dir"):
        return "Error: cache_type must be 'file' or 'dir'."
    return cache.write_entry(cache_type, path, data)


def _tool_read_cache(args, _target, cache):
    cache_type = args.get("cache_type", "")
    path = args.get("path", "")
    if cache_type not in ("file", "dir"):
        return "Error: cache_type must be 'file' or 'dir'."
    entry = cache.read_entry(cache_type, path)
    if entry is None:
        return "null"
    return json.dumps(entry, indent=2)


def _tool_list_cache(args, _target, cache):
    cache_type = args.get("cache_type", "")
    if cache_type not in ("file", "dir"):
        return "Error: cache_type must be 'file' or 'dir'."
    paths = cache.list_entries(cache_type)
    if not paths:
        return "(no cached entries)"
    return "\n".join(paths)


def _tool_think(args, _target, _cache):
    obs = args.get("observation", "")
    hyp = args.get("hypothesis", "")
    nxt = args.get("next_action", "")
    print(f"  [AI] THINK", file=sys.stderr)
    print(f"       observation: {obs}", file=sys.stderr)
    print(f"       hypothesis:  {hyp}", file=sys.stderr)
    print(f"       next_action: {nxt}", file=sys.stderr)
    return "ok"


def _tool_checkpoint(args, _target, _cache):
    learned = args.get("learned", "")
    unknown = args.get("still_unknown", "")
    phase = args.get("next_phase", "")
    print(f"  [AI] CHECKPOINT", file=sys.stderr)
    print(f"       learned:       {learned}", file=sys.stderr)
    print(f"       still_unknown: {unknown}", file=sys.stderr)
    print(f"       next_phase:    {phase}", file=sys.stderr)
    return "ok"


def _tool_flag(args, _target, cache):
    path = args.get("path", "general")
    finding = args.get("finding", "")
    severity = args.get("severity", "info")
    print(f"  [AI] FLAG [{severity.upper()}] {path}", file=sys.stderr)
    print(f"       {finding}", file=sys.stderr)
    flags_path = os.path.join(cache.root, "flags.jsonl")
    entry = {"path": path, "finding": finding, "severity": severity}
    try:
        with open(flags_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass
    return "ok"


_TOOL_DISPATCH = {
    "read_file": _tool_read_file,
    "list_directory": _tool_list_directory,
    "run_command": _tool_run_command,
    "parse_structure": _tool_parse_structure,
    "write_cache": _tool_write_cache,
    "read_cache": _tool_read_cache,
    "list_cache": _tool_list_cache,
    "think": _tool_think,
    "checkpoint": _tool_checkpoint,
    "flag": _tool_flag,
}


def _execute_tool(name, args, target, cache, dir_rel, turn, verbose=False):
    """Execute a tool by name and return the result string."""
    handler = _TOOL_DISPATCH.get(name)
    if handler is None:
        return f"Error: unknown tool '{name}'."
    result = handler(args, target, cache)

    cache.log_turn(dir_rel, turn, name,
                   {k: v for k, v in args.items() if k != "data"},
                   len(result))

    if verbose:
        preview = result[:200] + "..." if len(result) > 200 else result
        print(f"  [AI]     <- {len(result)} chars: {preview}", file=sys.stderr)

    return result


# ---------------------------------------------------------------------------
# Streaming API caller
# ---------------------------------------------------------------------------

def _call_api_streaming(client, system, messages, tools, tracker):
    """Call Claude via streaming. Print tool decisions in real-time.

    Returns (content_blocks, usage) where content_blocks is the list of
    content blocks from the response.
    """
    with client.messages.stream(
        model=MODEL,
        max_tokens=4096,
        system=system,
        messages=messages,
        tools=tools,
    ) as stream:
        # Print tool call names as they arrive
        current_tool = None
        for event in stream:
            if event.type == "content_block_start":
                block = event.content_block
                if block.type == "tool_use":
                    current_tool = block.name
                    # We'll print the full args after the block is complete
            elif event.type == "content_block_stop":
                current_tool = None

        response = stream.get_final_message()

    tracker.record(response.usage)
    return response.content, response.usage


# ---------------------------------------------------------------------------
# Directory discovery
# ---------------------------------------------------------------------------

def _discover_directories(target, show_hidden=False, exclude=None):
    """Walk the target and return all directories sorted leaves-first."""
    extra = set(exclude or [])
    dirs = []
    target_real = os.path.realpath(target)
    for root, subdirs, _files in os.walk(target_real, topdown=True):
        subdirs[:] = [
            d for d in subdirs
            if not _should_skip_dir(d)
            and d not in extra
            and (show_hidden or not d.startswith("."))
        ]
        dirs.append(root)
    dirs.sort(key=lambda d: (-d.count(os.sep), d))
    return dirs


# ---------------------------------------------------------------------------
# Per-directory agent loop
# ---------------------------------------------------------------------------

def _build_dir_context(dir_path):
    lines = []
    try:
        entries = sorted(os.listdir(dir_path))
        for name in entries:
            if name.startswith("."):
                continue
            full = os.path.join(dir_path, name)
            try:
                st = os.stat(full)
                if os.path.isdir(full):
                    lines.append(f"  {name}/  (dir)")
                else:
                    mime = magic.from_file(full, mime=True)
                    lines.append(f"  {name}  ({st.st_size} bytes)  [{mime}]")
            except OSError:
                lines.append(f"  {name}  (stat failed)")
    except OSError:
        lines.append("  (could not list directory)")
    return "Directory contents:\n" + "\n".join(lines) if lines else "(empty)"


def _get_child_summaries(dir_path, cache):
    parts = []
    try:
        for name in sorted(os.listdir(dir_path)):
            child = os.path.join(dir_path, name)
            if not os.path.isdir(child):
                continue
            entry = cache.read_entry("dir", child)
            if entry:
                rel = entry.get("relative_path", name)
                summary = entry.get("summary", "(no summary)")
                parts.append(f"- {rel}/: {summary}")
    except OSError:
        pass
    return "\n".join(parts) if parts else "(none — this is a leaf directory)"


_SURVEY_CONFIDENCE_THRESHOLD = 0.5
_PROTECTED_DIR_TOOLS = {"submit_report"}

# Survey-skip thresholds. Skip the survey only when BOTH are below.
# See #46 for the plan to revisit these with empirical data.
_SURVEY_MIN_FILES = 5
_SURVEY_MIN_DIRS = 2


def _default_survey():
    """Synthetic survey for targets too small to justify the API call.

    confidence=0.0 ensures _filter_dir_tools() never enforces skip_tools
    based on this synthetic value — the dir loop keeps its full toolbox.
    """
    return {
        "description": "Small target — survey skipped.",
        "approach": (
            "The target is small enough to investigate exhaustively. "
            "Read every file directly."
        ),
        "relevant_tools": [],
        "skip_tools": [],
        "domain_notes": "",
        "confidence": 0.0,
    }


def _format_survey_block(survey):
    """Render survey output as a labeled text block for the dir prompt."""
    if not survey:
        return "(no survey available)"
    lines = [
        f"Description: {survey.get('description', '')}",
        f"Approach: {survey.get('approach', '')}",
    ]
    notes = survey.get("domain_notes", "")
    if notes:
        lines.append(f"Domain notes: {notes}")
    relevant = survey.get("relevant_tools") or []
    if relevant:
        lines.append(f"Relevant tools (lean on these): {', '.join(relevant)}")
    skip = survey.get("skip_tools") or []
    if skip:
        lines.append(f"Skip tools (already removed from your toolbox): "
                     f"{', '.join(skip)}")
    return "\n".join(lines)


def _filter_dir_tools(survey):
    """Return _DIR_TOOLS with skip_tools removed, gated on confidence.

    - Returns full list if survey is None or confidence < threshold.
    - Always preserves control-flow tools in _PROTECTED_DIR_TOOLS.
    - Tool names in skip_tools that don't match anything are silently ignored.
    """
    if not survey:
        return list(_DIR_TOOLS)
    try:
        confidence = float(survey.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < _SURVEY_CONFIDENCE_THRESHOLD:
        return list(_DIR_TOOLS)
    skip = set(survey.get("skip_tools") or []) - _PROTECTED_DIR_TOOLS
    if not skip:
        return list(_DIR_TOOLS)
    return [t for t in _DIR_TOOLS if t["name"] not in skip]


def _run_dir_loop(client, target, cache, tracker, dir_path, max_turns=14,
                  verbose=False, survey=None):
    """Run an isolated agent loop for a single directory."""
    dir_rel = os.path.relpath(dir_path, target)
    if dir_rel == ".":
        dir_rel = os.path.basename(target)

    context = _build_dir_context(dir_path)
    child_summaries = _get_child_summaries(dir_path, cache)
    survey_context = _format_survey_block(survey)
    dir_tools = _filter_dir_tools(survey)

    system = _DIR_SYSTEM_PROMPT.format(
        dir_path=dir_path,
        dir_rel=dir_rel,
        max_turns=max_turns,
        context=context,
        child_summaries=child_summaries,
        survey_context=survey_context,
    )

    messages = [
        {
            "role": "user",
            "content": (
                "Investigate this directory now. Use parse_structure for "
                "source files, read_file for others, cache summaries, and "
                "call submit_report. Batch tool calls for efficiency."
            ),
        },
    ]

    tracker.reset_loop()
    summary = None

    for turn in range(max_turns):
        # Check context budget
        if tracker.budget_exceeded():
            print(f"  [AI]   Context budget reached — exiting early "
                  f"({tracker.loop_total:,} tokens used)", file=sys.stderr)
            # Flush a partial directory summary from cached file entries
            if not cache.has_entry("dir", dir_path):
                dir_real = os.path.realpath(dir_path)
                file_entries = [
                    e for e in cache.read_all_entries("file")
                    if os.path.realpath(e.get("path", "")).startswith(
                        dir_real + os.sep)
                    or os.path.dirname(
                        os.path.join(target, e.get("relative_path", ""))
                    ) == dir_real
                ]
                if file_entries:
                    file_summaries = [
                        e["summary"] for e in file_entries if e.get("summary")
                    ]
                    notable = [
                        e.get("relative_path", e.get("path", ""))
                        for e in file_entries if e.get("notable")
                    ]
                    partial_summary = " ".join(file_summaries)
                    cache.write_entry("dir", dir_path, {
                        "path": dir_path,
                        "relative_path": os.path.relpath(dir_path, target),
                        "child_count": len([
                            n for n in os.listdir(dir_path)
                            if not n.startswith(".")
                        ]) if os.path.isdir(dir_path) else 0,
                        "summary": partial_summary,
                        "dominant_category": "unknown",
                        "notable_files": notable,
                        "partial": True,
                        "partial_reason": "context budget reached",
                        "cached_at": _now_iso(),
                    })
                    if not summary:
                        summary = partial_summary
                else:
                    cache.write_entry("dir", dir_path, {
                        "path": dir_path,
                        "relative_path": os.path.relpath(dir_path, target),
                        "child_count": 0,
                        "summary": ("Investigation incomplete — context budget "
                                    "reached before any files were processed."),
                        "dominant_category": "unknown",
                        "notable_files": [],
                        "partial": True,
                        "partial_reason": (
                            "context budget reached before files processed"),
                        "cached_at": _now_iso(),
                    })
            break

        try:
            content_blocks, usage = _call_api_streaming(
                client, system, messages, dir_tools, tracker,
            )
        except anthropic.APIError as e:
            print(f"  [AI]   API error: {e}", file=sys.stderr)
            break

        # Print text blocks (step numbering, reasoning) to stderr
        for b in content_blocks:
            if b.type == "text" and b.text.strip():
                for line in b.text.strip().split("\n"):
                    print(f"  [AI]   {line}", file=sys.stderr)

        # Print tool decisions now that we have the full response
        tool_uses = [b for b in content_blocks if b.type == "tool_use"]
        for tu in tool_uses:
            arg_summary = ", ".join(
                f"{k}={v!r}" for k, v in tu.input.items() if k != "data"
            ) if tu.input else ""
            print(f"  [AI]   -> {tu.name}({arg_summary})", file=sys.stderr)

        messages.append({
            "role": "assistant",
            "content": [_block_to_dict(b) for b in content_blocks],
        })

        if not tool_uses:
            messages.append({
                "role": "user",
                "content": "Please call submit_report with your summary.",
            })
            continue

        tool_results = []
        done = False
        for tu in tool_uses:
            if tu.name == "submit_report":
                summary = tu.input.get("summary", "")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": "Summary submitted.",
                })
                done = True
            else:
                result_text = _execute_tool(
                    tu.name, tu.input, target, cache, dir_rel,
                    turn + 1, verbose=verbose,
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result_text,
                })

        messages.append({"role": "user", "content": tool_results})

        if done:
            break
    else:
        print(f"  [AI]   Warning: max turns reached for {dir_rel}",
              file=sys.stderr)

    return summary


def _block_to_dict(block):
    """Convert an SDK content block to a plain dict for message history."""
    if block.type == "text":
        return {"type": "text", "text": block.text}
    elif block.type == "tool_use":
        return {"type": "tool_use", "id": block.id,
                "name": block.name, "input": block.input}
    return {"type": block.type}


# ---------------------------------------------------------------------------
# Synthesis pass
# ---------------------------------------------------------------------------

def _format_survey_signals(signals):
    """Render the survey_signals dict as a labeled text block."""
    if not signals or not signals.get("total_files"):
        return "(no files classified)"

    lines = [f"Total files: {signals.get('total_files', 0)}", ""]

    ext_hist = signals.get("extension_histogram") or {}
    if ext_hist:
        lines.append("Extensions (top, by count):")
        for ext, n in ext_hist.items():
            lines.append(f"  {ext}: {n}")
        lines.append("")

    descs = signals.get("file_descriptions") or {}
    if descs:
        lines.append("file --brief output (top, by count):")
        for desc, n in descs.items():
            lines.append(f"  {desc}: {n}")
        lines.append("")

    samples = signals.get("filename_samples") or []
    if samples:
        lines.append("Filename samples (evenly drawn):")
        for name in samples:
            lines.append(f"  {name}")

    return "\n".join(lines).rstrip()


def _run_survey(client, target, report, tracker, max_turns=3, verbose=False):
    """Run the reconnaissance survey pass.

    Returns a survey dict on success, or None on failure / out-of-turns.
    Survey is advisory — callers must treat None as "no survey context".
    """
    signals = report.get("survey_signals") or {}
    survey_signals_text = _format_survey_signals(signals)

    try:
        tree_node = build_tree(target, max_depth=2)
        tree_preview = render_tree(tree_node)
    except Exception:
        tree_preview = "(tree unavailable)"

    tool_names = [t["name"] for t in _DIR_TOOLS if t["name"] != "submit_report"]
    available_tools = ", ".join(tool_names)

    system = _SURVEY_SYSTEM_PROMPT.format(
        target=target,
        survey_signals=survey_signals_text,
        tree_preview=tree_preview,
        available_tools=available_tools,
    )

    messages = [
        {
            "role": "user",
            "content": (
                "All inputs are in the system prompt above. Call "
                "submit_survey now — no other tool calls needed."
            ),
        },
    ]

    survey = None

    for turn in range(max_turns):
        try:
            content_blocks, _usage = _call_api_streaming(
                client, system, messages, _SURVEY_TOOLS, tracker,
            )
        except anthropic.APIError as e:
            print(f"  [AI]   API error: {e}", file=sys.stderr)
            return None

        for b in content_blocks:
            if b.type == "text" and b.text.strip():
                for line in b.text.strip().split("\n"):
                    print(f"  [AI]   {line}", file=sys.stderr)

        tool_uses = [b for b in content_blocks if b.type == "tool_use"]
        for tu in tool_uses:
            arg_summary = ", ".join(
                f"{k}={v!r}" for k, v in tu.input.items()
            ) if tu.input else ""
            print(f"  [AI]   -> {tu.name}({arg_summary})", file=sys.stderr)

        messages.append({
            "role": "assistant",
            "content": [_block_to_dict(b) for b in content_blocks],
        })

        if not tool_uses:
            messages.append({
                "role": "user",
                "content": "Please call submit_survey.",
            })
            continue

        tool_results = []
        done = False
        for tu in tool_uses:
            if tu.name == "submit_survey":
                survey = {
                    "description": tu.input.get("description", ""),
                    "approach": tu.input.get("approach", ""),
                    "relevant_tools": tu.input.get("relevant_tools", []) or [],
                    "skip_tools": tu.input.get("skip_tools", []) or [],
                    "domain_notes": tu.input.get("domain_notes", ""),
                    "confidence": float(tu.input.get("confidence", 0.0) or 0.0),
                }
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": "Survey received. Thank you.",
                })
                done = True
            else:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": "Unknown tool. Call submit_survey.",
                    "is_error": True,
                })

        messages.append({"role": "user", "content": tool_results})

        if done:
            break
    else:
        print("  [AI] Warning: survey ran out of turns.", file=sys.stderr)

    return survey


def _run_synthesis(client, target, cache, tracker, max_turns=5, verbose=False):
    """Run the final synthesis pass. Returns (brief, detailed)."""
    dir_entries = cache.read_all_entries("dir")

    summary_lines = []
    for entry in dir_entries:
        rel = entry.get("relative_path", "?")
        summary = entry.get("summary", "(no summary)")
        dominant = entry.get("dominant_category", "?")
        notable = entry.get("notable_files", [])
        summary_lines.append(f"### {rel}/")
        summary_lines.append(f"Category: {dominant}")
        summary_lines.append(f"Summary: {summary}")
        if notable:
            summary_lines.append(f"Notable files: {', '.join(notable)}")
        summary_lines.append("")

    summaries_text = "\n".join(summary_lines) if summary_lines else "(none)"

    system = _SYNTHESIS_SYSTEM_PROMPT.format(
        target=target,
        summaries_text=summaries_text,
    )

    messages = [
        {
            "role": "user",
            "content": (
                "All directory summaries are in the system prompt above. "
                "Synthesize them into a cohesive report and call "
                "submit_report immediately — no other tool calls needed."
            ),
        },
    ]

    brief, detailed = "", ""

    for turn in range(max_turns):
        try:
            content_blocks, usage = _call_api_streaming(
                client, system, messages, _SYNTHESIS_TOOLS, tracker,
            )
        except anthropic.APIError as e:
            print(f"  [AI]   API error: {e}", file=sys.stderr)
            break

        # Print text blocks to stderr
        for b in content_blocks:
            if b.type == "text" and b.text.strip():
                for line in b.text.strip().split("\n"):
                    print(f"  [AI]   {line}", file=sys.stderr)

        tool_uses = [b for b in content_blocks if b.type == "tool_use"]
        for tu in tool_uses:
            arg_summary = ", ".join(
                f"{k}={v!r}" for k, v in tu.input.items() if k != "data"
            ) if tu.input else ""
            print(f"  [AI]   -> {tu.name}({arg_summary})", file=sys.stderr)

        messages.append({
            "role": "assistant",
            "content": [_block_to_dict(b) for b in content_blocks],
        })

        if not tool_uses:
            messages.append({
                "role": "user",
                "content": "Please call submit_report with your analysis.",
            })
            continue

        tool_results = []
        done = False
        for tu in tool_uses:
            if tu.name == "submit_report":
                brief = tu.input.get("brief", "")
                detailed = tu.input.get("detailed", "")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": "Report submitted. Thank you.",
                })
                done = True
            else:
                result_text = _execute_tool(
                    tu.name, tu.input, target, cache, "(synthesis)",
                    turn + 1, verbose=verbose,
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result_text,
                })

        messages.append({"role": "user", "content": tool_results})

        if done:
            break
    else:
        print("  [AI] Warning: synthesis ran out of turns.", file=sys.stderr)
        brief, detailed = _synthesize_from_cache(cache)

    return brief, detailed


def _synthesize_from_cache(cache):
    """Build a best-effort report from cached directory summaries."""
    dir_entries = cache.read_all_entries("dir")
    if not dir_entries:
        return ("(AI analysis incomplete — no data was cached)", "")

    brief_parts = []
    detail_parts = []
    for entry in dir_entries:
        rel = entry.get("relative_path", "?")
        summary = entry.get("summary", "")
        if summary:
            detail_parts.append(f"**{rel}/**: {summary}")
            brief_parts.append(summary)

    brief = brief_parts[0] if brief_parts else "(AI analysis incomplete)"
    detailed = "\n\n".join(detail_parts) if detail_parts else ""
    return brief, detailed


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def _run_investigation(client, target, report, show_hidden=False,
                       fresh=False, verbose=False, exclude=None):
    """Orchestrate the multi-pass investigation. Returns (brief, detailed, flags)."""
    investigation_id, is_new = _get_investigation_id(target, fresh=fresh)
    cache = _CacheManager(investigation_id, target)
    tracker = _TokenTracker()

    if is_new:
        cache.write_meta(MODEL, _now_iso())

    print(f"  [AI] Investigation ID: {investigation_id}"
          f"{'' if is_new else ' (resumed)'}", file=sys.stderr)
    print(f"  [AI] Cache: {cache.root}/", file=sys.stderr)

    all_dirs = _discover_directories(target, show_hidden=show_hidden,
                                     exclude=exclude)

    total_files = sum((report.get("file_categories") or {}).values())
    total_dirs = len(all_dirs)
    if total_files < _SURVEY_MIN_FILES and total_dirs < _SURVEY_MIN_DIRS:
        print(
            f"  [AI] Survey skipped — {total_files} files, {total_dirs} dirs "
            f"(below threshold).",
            file=sys.stderr,
        )
        survey = _default_survey()
    else:
        print("  [AI] Survey pass...", file=sys.stderr)
        survey = _run_survey(client, target, report, tracker, verbose=verbose)
    if survey:
        print(
            f"  [AI] Survey: {survey['description']} "
            f"(confidence {survey['confidence']:.2f})",
            file=sys.stderr,
        )
        if survey.get("domain_notes"):
            print(f"  [AI] Survey notes: {survey['domain_notes']}", file=sys.stderr)
        if survey.get("relevant_tools"):
            print(
                f"  [AI] Survey relevant_tools: {', '.join(survey['relevant_tools'])}",
                file=sys.stderr,
            )
        if survey.get("skip_tools"):
            print(
                f"  [AI] Survey skip_tools: {', '.join(survey['skip_tools'])}",
                file=sys.stderr,
            )
    else:
        print("  [AI] Survey unavailable — proceeding without it.", file=sys.stderr)

    to_investigate = []
    cached_count = 0
    for d in all_dirs:
        if cache.has_entry("dir", d):
            cached_count += 1
            rel = os.path.relpath(d, target)
            print(f"  [AI] Skipping (cached): {rel}/", file=sys.stderr)
        else:
            to_investigate.append(d)

    total = len(to_investigate)
    if cached_count:
        print(f"  [AI] Directories cached: {cached_count}", file=sys.stderr)
    print(f"  [AI] Directories to investigate: {total}", file=sys.stderr)

    for i, dir_path in enumerate(to_investigate, 1):
        dir_rel = os.path.relpath(dir_path, target)
        if dir_rel == ".":
            dir_rel = os.path.basename(target)
        print(f"  [AI] Investigating: {dir_rel}/ ({i}/{total})",
              file=sys.stderr)

        summary = _run_dir_loop(
            client, target, cache, tracker, dir_path, verbose=verbose,
            survey=survey,
        )

        if summary and not cache.has_entry("dir", dir_path):
            cache.write_entry("dir", dir_path, {
                "path": dir_path,
                "relative_path": os.path.relpath(dir_path, target),
                "child_count": len([
                    n for n in os.listdir(dir_path)
                    if not n.startswith(".")
                ]) if os.path.isdir(dir_path) else 0,
                "summary": summary,
                "dominant_category": "unknown",
                "notable_files": [],
                "cached_at": _now_iso(),
            })

    cache.update_meta(
        directories_investigated=total + cached_count,
        end_time=_now_iso(),
    )

    print("  [AI] Synthesis pass...", file=sys.stderr)
    brief, detailed = _run_synthesis(
        client, target, cache, tracker, verbose=verbose,
    )

    # Read flags from flags.jsonl
    flags = []
    flags_path = os.path.join(cache.root, "flags.jsonl")
    try:
        with open(flags_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    flags.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        pass

    print(f"  [AI] Total tokens used: {tracker.summary()}", file=sys.stderr)

    return brief, detailed, flags


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def analyze_directory(report, target, verbose_tools=False, fresh=False,
                      exclude=None):
    """Run AI analysis on the directory. Returns (brief, detailed, flags).

    Returns ("", "", []) if the API key is missing or dependencies are not met.
    """
    if not check_ai_dependencies():
        sys.exit(1)

    api_key = _get_api_key()
    if not api_key:
        return "", "", []

    print("  [AI] Starting multi-pass investigation...", file=sys.stderr)

    client = anthropic.Anthropic(api_key=api_key)

    try:
        brief, detailed, flags = _run_investigation(
            client, target, report, fresh=fresh, verbose=verbose_tools,
            exclude=exclude,
        )
    except Exception as e:
        print(f"Warning: AI analysis failed: {e}", file=sys.stderr)
        return "", "", []

    if not brief and not detailed:
        print("  [AI] Warning: agent produced no output.", file=sys.stderr)

    print("  [AI] Investigation complete.", file=sys.stderr)
    return brief, detailed, flags
