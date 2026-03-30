# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running Luminos

```bash
# Basic scan
python3 luminos.py <target_directory>

# With AI analysis (requires ANTHROPIC_API_KEY env var)
python3 luminos.py --ai <target_directory>

# JSON output to file
python3 luminos.py --json -o report.json <target_directory>

# Watch mode (re-scans every 30s, shows diffs)
python3 luminos.py --watch <target_directory>
```

There is no build step, no test suite, and no linter configured.

## Architecture

The base tool is a zero-dependency Python CLI (stdlib only). The `--ai` flag requires optional pip packages installed in a venv. The entry point `luminos.py` defines `scan()` which orchestrates all analysis modules and returns a report dict, and `main()` which handles argument parsing and output routing.

Each analysis capability lives in its own module under `luminos_lib/`:

| Module | Purpose | External commands used |
|---|---|---|
| `tree.py` | Recursive directory tree with file sizes | None (uses `os`) |
| `filetypes.py` | Classifies files into 7 categories (source, config, data, media, document, archive, unknown) | `file --brief` |
| `code.py` | Language detection, LOC counting, large file flagging | `wc -l` |
| `recency.py` | Finds N most recently modified files | `find -printf` |
| `disk.py` | Per-directory disk usage | `du -b` |
| `report.py` | Formats the report dict as human-readable terminal output | None |
| `ai.py` | Multi-pass agentic directory analysis via Claude API (streaming, token counting, caching) | Requires `anthropic`, `tree-sitter`, `python-magic` |
| `capabilities.py` | Optional dependency detection, cache cleanup | None |
| `watch.py` | Continuous monitoring loop with snapshot diffing | None (re-uses `filetypes.classify_files`) |

**Data flow:** `scan()` builds a report dict → optional `analyze_directory()` adds AI fields → `format_report()` or `json.dumps()` produces output.

## Optional Dependencies (--ai flag only)

The base tool requires zero pip packages. The `--ai` flag requires:

```bash
# One-time setup
bash setup_env.sh

# Or manually:
python3 -m venv ~/luminos-env
source ~/luminos-env/bin/activate
pip install anthropic tree-sitter tree-sitter-python \
            tree-sitter-javascript tree-sitter-rust \
            tree-sitter-go python-magic
```

Check current status with `python3 luminos.py --install-extras`.

Always activate the venv before using `--ai`:
```bash
source ~/luminos-env/bin/activate
python3 luminos.py --ai <target_directory>
```

## Key Constraints

- **Base tool: no pip dependencies.** The base scan (tree, file types, code, disk, recency, report, watch) uses only stdlib and GNU coreutils. It must always work on a bare Python 3 install.
- **AI deps are gated.** The `anthropic`, `tree-sitter`, and `python-magic` packages are imported lazily, only when `--ai` is used. Missing packages produce a clear error with the install command.
- **Subprocess for OS tools.** Line counting, file detection, disk usage, and recency all shell out to GNU coreutils. Do not reimplement these in pure Python.
- **AI is opt-in.** The `--ai` flag gates all Claude API calls. Without it (or without `ANTHROPIC_API_KEY`), the tool must produce a complete report with no errors.
- **Graceful degradation everywhere.** Permission denied, subprocess timeouts, missing API key — all handled without crashing.

## Git Workflow

Every change starts on a branch. Nothing goes directly to main.

### Branch naming

Create a branch before starting any work:

```bash
git checkout -b <type>/<short-description>
```

Branch type matches the commit prefix:

| Type | Use |
|---|---|
| `feat/` | New feature or capability |
| `fix/` | Bug fix |
| `refactor/` | Restructure without behavior change |
| `chore/` | Tooling, config, documentation |
| `test/` | Tests |

Examples:
```
feat/venv-setup-script
fix/token-budget-early-exit
refactor/capabilities-module
chore/update-claude-md
```

### Commit messages

Format: `<type>: <short description>`

```
feat: add parse_structure tool via tree-sitter
fix: flush cache on context budget early exit
refactor: extract token tracking into separate class
chore: update CLAUDE.md with git workflow
```

One commit per logical unit of work, not one per file.

### Merge procedure

When the task is complete:

```bash
git checkout main
git merge --no-ff <branch> -m "merge: <description>"
git branch -d <branch>
```

The `--no-ff` flag preserves branch history in the log even after merge. Delete the branch after merging to keep the branch list clean.
