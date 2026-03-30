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
import tree_sitter
import tree_sitter_python
import tree_sitter_javascript
import tree_sitter_rust
import tree_sitter_go

from luminos_lib.cache import CACHE_ROOT, _CacheManager, _get_investigation_id
from luminos_lib.capabilities import check_ai_dependencies

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

# tree-sitter language registry: extension → (grammar_module, language_name)
_TS_LANGUAGES = {
    ".py": (tree_sitter_python, "python"),
    ".js": (tree_sitter_javascript, "javascript"),
    ".jsx": (tree_sitter_javascript, "javascript"),
    ".mjs": (tree_sitter_javascript, "javascript"),
    ".rs": (tree_sitter_rust, "rust"),
    ".go": (tree_sitter_go, "go"),
}

# Precompute Language objects once.
_TS_LANG_CACHE = {}


def _get_ts_parser(ext):
    """Return a (Parser, language_name) tuple for a file extension, or None."""
    entry = _TS_LANGUAGES.get(ext)
    if entry is None:
        return None
    module, lang_name = entry
    if lang_name not in _TS_LANG_CACHE:
        _TS_LANG_CACHE[lang_name] = tree_sitter.Language(module.language())
    lang = _TS_LANG_CACHE[lang_name]
    parser = tree_sitter.Parser(lang)
    return parser, lang_name


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
    if not os.path.isfile(path):
        return f"Error: '{path}' is not a file."

    ext = os.path.splitext(path)[1].lower()
    ts = _get_ts_parser(ext)
    if ts is None:
        return f"Error: no grammar for extension '{ext}'. Supported: {', '.join(sorted(_TS_LANGUAGES.keys()))}"

    parser, lang_name = ts

    try:
        with open(path, "rb") as f:
            source = f.read()
    except OSError as e:
        return f"Error reading file: {e}"

    tree = parser.parse(source)
    root = tree.root_node
    source_text = source.decode("utf-8", errors="replace")
    lines = source_text.split("\n")
    line_count = len(lines)

    functions = []
    classes = []
    imports = []
    has_docstrings = False
    comment_lines = 0

    def _walk(node):
        nonlocal has_docstrings, comment_lines
        for child in node.children:
            ntype = child.type

            # Comments
            if ntype in ("comment", "line_comment", "block_comment"):
                comment_lines += child.text.decode("utf-8", errors="replace").count("\n") + 1

            # Python
            if lang_name == "python":
                if ntype == "function_definition":
                    functions.append(_py_func_sig(child))
                elif ntype == "class_definition":
                    classes.append(_py_class(child))
                elif ntype in ("import_statement", "import_from_statement"):
                    imports.append(child.text.decode("utf-8", errors="replace").strip())
                elif ntype == "expression_statement":
                    first = child.children[0] if child.children else None
                    if first and first.type == "string":
                        has_docstrings = True

            # JavaScript
            elif lang_name == "javascript":
                if ntype in ("function_declaration", "arrow_function",
                             "function"):
                    functions.append(_js_func_sig(child))
                elif ntype == "class_declaration":
                    classes.append(_js_class(child))
                elif ntype in ("import_statement",):
                    imports.append(child.text.decode("utf-8", errors="replace").strip())

            # Rust
            elif lang_name == "rust":
                if ntype == "function_item":
                    functions.append(_rust_func_sig(child))
                elif ntype in ("struct_item", "enum_item", "impl_item"):
                    classes.append(_rust_struct(child))
                elif ntype == "use_declaration":
                    imports.append(child.text.decode("utf-8", errors="replace").strip())

            # Go
            elif lang_name == "go":
                if ntype == "function_declaration":
                    functions.append(_go_func_sig(child))
                elif ntype == "type_declaration":
                    classes.append(_go_type(child))
                elif ntype == "import_declaration":
                    imports.append(child.text.decode("utf-8", errors="replace").strip())

            _walk(child)

    _walk(root)

    code_lines = max(1, line_count - comment_lines)
    result = {
        "language": lang_name,
        "functions": functions[:50],
        "classes": classes[:30],
        "imports": imports[:30],
        "line_count": line_count,
        "has_docstrings": has_docstrings,
        "has_comments": comment_lines > 0,
        "comment_to_code_ratio": round(comment_lines / code_lines, 2),
    }
    return json.dumps(result, indent=2)


# --- tree-sitter extraction helpers ---

def _child_by_type(node, *types):
    for c in node.children:
        if c.type in types:
            return c
    return None


def _text(node):
    return node.text.decode("utf-8", errors="replace") if node else ""


def _py_func_sig(node):
    name = _text(_child_by_type(node, "identifier"))
    params = _text(_child_by_type(node, "parameters"))
    ret = _child_by_type(node, "type")
    sig = f"{name}{params}"
    if ret:
        sig += f" -> {_text(ret)}"
    return sig


def _py_class(node):
    name = _text(_child_by_type(node, "identifier"))
    methods = []
    body = _child_by_type(node, "block")
    if body:
        for child in body.children:
            if child.type == "function_definition":
                methods.append(_py_func_sig(child))
    return {"name": name, "methods": methods[:20]}


def _js_func_sig(node):
    name = _text(_child_by_type(node, "identifier"))
    params = _text(_child_by_type(node, "formal_parameters"))
    return f"{name}{params}" if name else f"(anonymous){params}"


def _js_class(node):
    name = _text(_child_by_type(node, "identifier"))
    methods = []
    body = _child_by_type(node, "class_body")
    if body:
        for child in body.children:
            if child.type == "method_definition":
                mname = _text(_child_by_type(child, "property_identifier"))
                mparams = _text(_child_by_type(child, "formal_parameters"))
                methods.append(f"{mname}{mparams}")
    return {"name": name, "methods": methods[:20]}


def _rust_func_sig(node):
    name = _text(_child_by_type(node, "identifier"))
    params = _text(_child_by_type(node, "parameters"))
    ret = _child_by_type(node, "type_identifier", "generic_type",
                         "reference_type", "scoped_type_identifier")
    sig = f"{name}{params}"
    if ret:
        sig += f" -> {_text(ret)}"
    return sig


def _rust_struct(node):
    name = _text(_child_by_type(node, "type_identifier"))
    return {"name": name or _text(node)[:60], "methods": []}


def _go_func_sig(node):
    name = _text(_child_by_type(node, "identifier"))
    params = _text(_child_by_type(node, "parameter_list"))
    return f"{name}{params}"


def _go_type(node):
    spec = _child_by_type(node, "type_spec")
    name = _text(_child_by_type(spec, "type_identifier")) if spec else ""
    return {"name": name or _text(node)[:60], "methods": []}


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

def _discover_directories(target, show_hidden=False):
    """Walk the target and return all directories sorted leaves-first."""
    dirs = []
    target_real = os.path.realpath(target)
    for root, subdirs, _files in os.walk(target_real, topdown=True):
        subdirs[:] = [
            d for d in subdirs
            if not _should_skip_dir(d)
            and (show_hidden or not d.startswith("."))
        ]
        dirs.append(root)
    dirs.sort(key=lambda d: (-d.count(os.sep), d))
    return dirs


# ---------------------------------------------------------------------------
# Per-directory agent loop
# ---------------------------------------------------------------------------

_DIR_SYSTEM_PROMPT = """\
You are an expert analyst investigating a SINGLE directory on a file system.
Do NOT assume the type of content before investigating. Discover what this
directory contains from what you find.

## Your Task
Investigate the directory: {dir_path}
(relative to target: {dir_rel})

You must:
1. Read the important files in THIS directory (not subdirectories)
2. For each file you read, call write_cache to save a summary
3. Call write_cache for the directory itself with a synthesis
4. Call submit_report with a 1-3 sentence summary

## Tools
parse_structure gives you the skeleton of a file. It does NOT replace \
reading the file. Use parse_structure first to understand structure, then \
use read_file if you need to verify intent, check for anomalies, or \
understand content that structure cannot capture (comments, documentation, \
data files, config values). A file where structure and content appear to \
contradict each other is always worth reading in full.

Use the think tool when choosing which file or directory to investigate \
next — before starting a new file or switching investigation direction. \
Do NOT call think before every individual tool call in a sequence.

Use the checkpoint tool after completing investigation of a meaningful \
cluster of files. Not after every file — once or twice per directory \
loop at most.

Use the flag tool immediately when you find something notable, \
surprising, or concerning. Severity guide:
  info     = interesting but not problematic
  concern  = worth addressing
  critical = likely broken or dangerous

## Step Numbering
Number your investigation steps as you go. Before starting each new \
file cluster or phase transition, output:
Step N: <what you are doing and why>
Output this as plain text before tool calls, not as a tool call itself.

## Efficiency Rules
- Batch multiple tool calls in a single turn whenever possible
- Skip binary/compiled/generated files (.pyc, .class, .o, .min.js, etc.)
- Skip files >100KB unless uniquely important
- Prioritize: README, index, main, config, schema, manifest files
- For source files: try parse_structure first, then read_file if needed
- If read_file returns truncated content, use a larger max_bytes or
  run_command('tail ...') — NEVER retry the identical call
- You have only {max_turns} turns — be efficient

## Cache Schemas
File: {{path, relative_path, size_bytes, category, summary, notable,
  notable_reason, cached_at}}
Dir: {{path, relative_path, child_count, summary, dominant_category,
  notable_files, cached_at}}

category values: source, config, data, document, media, archive, unknown

## Context
{context}

## Child Directory Summaries (already investigated)
{child_summaries}"""


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


def _run_dir_loop(client, target, cache, tracker, dir_path, max_turns=14,
                  verbose=False):
    """Run an isolated agent loop for a single directory."""
    dir_rel = os.path.relpath(dir_path, target)
    if dir_rel == ".":
        dir_rel = os.path.basename(target)

    context = _build_dir_context(dir_path)
    child_summaries = _get_child_summaries(dir_path, cache)

    system = _DIR_SYSTEM_PROMPT.format(
        dir_path=dir_path,
        dir_rel=dir_rel,
        max_turns=max_turns,
        context=context,
        child_summaries=child_summaries,
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
                client, system, messages, _DIR_TOOLS, tracker,
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

_SYNTHESIS_SYSTEM_PROMPT = """\
You are an expert analyst synthesizing a final report about a directory tree.
ALL directory summaries are provided below — you do NOT need to call
list_cache or read_cache. Just read the summaries and call submit_report
immediately in your first turn.

Do NOT assume the type of content. Let the summaries speak for themselves.

## Your Goal
Produce two outputs via the submit_report tool:
1. **brief**: A 2-4 sentence summary of what this directory tree is.
2. **detailed**: A thorough breakdown covering purpose, structure, key
   components, technologies, notable patterns, and any concerns.

## Rules
- ALL summaries are below — call submit_report directly
- Be specific — reference actual directory and file names
- Do NOT call list_cache or read_cache

## Target
{target}

## Directory Summaries
{summaries_text}"""


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
                       fresh=False, verbose=False):
    """Orchestrate the multi-pass investigation. Returns (brief, detailed, flags)."""
    investigation_id, is_new = _get_investigation_id(target, fresh=fresh)
    cache = _CacheManager(investigation_id, target)
    tracker = _TokenTracker()

    if is_new:
        cache.write_meta(MODEL, _now_iso())

    print(f"  [AI] Investigation ID: {investigation_id}"
          f"{'' if is_new else ' (resumed)'}", file=sys.stderr)
    print(f"  [AI] Cache: {cache.root}/", file=sys.stderr)

    all_dirs = _discover_directories(target, show_hidden=show_hidden)

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
# Cache cleanup
# ---------------------------------------------------------------------------

def clear_cache():
    """Remove all investigation caches under /tmp/luminos/."""
    import shutil
    if os.path.isdir(CACHE_ROOT):
        shutil.rmtree(CACHE_ROOT)
        print(f"Cleared cache: {CACHE_ROOT}", file=sys.stderr)
    else:
        print(f"No cache to clear ({CACHE_ROOT} does not exist).",
              file=sys.stderr)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def analyze_directory(report, target, verbose_tools=False, fresh=False):
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
        )
    except Exception as e:
        print(f"Warning: AI analysis failed: {e}", file=sys.stderr)
        return "", "", []

    if not brief and not detailed:
        print("  [AI] Warning: agent produced no output.", file=sys.stderr)

    print("  [AI] Investigation complete.", file=sys.stderr)
    return brief, detailed, flags
