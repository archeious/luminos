# CLAUDE.md

> **STOP. Before producing ANY output, pull `docs/wiki/`, fetch open Forgejo
> issues for `archeious/luminos`, and present them as suggested tasks. Then
> ask: "What's the one thing we're shipping?" No preamble. No acknowledgment.
> Just the suggested tasks and the question. Everything else comes after the
> user answers.**

---

## Current Project State

- **Phase:** Active development — Phase 1 + 2 + 2.5 complete; Phase 3 (investigation planning) ready to start
- **Last worked on:** 2026-04-07
- **Last commit:** merge: fix/issue-54-write-cache-tool-desc
- **Blocking:** None

---

## Project Overview

Luminos is a file system intelligence tool. Point it at a directory and it
runs a multi-pass agentic investigation via the Claude API: a survey pass,
isolated dir-loop agents per directory, and a synthesis pass that produces a
project-level verdict with severity-ranked flags. A lightweight base scan
runs first to feed the agent its initial picture of the target.

---

## Module Map

| Module | Purpose |
|---|---|
| `luminos.py` | Entry point — arg parsing, scan(), main() |
| `luminos_lib/ai.py` | Multi-pass agentic analysis via Claude API |
| `luminos_lib/ast_parser.py` | tree-sitter code structure parsing |
| `luminos_lib/cache.py` | Investigation cache management (incl. clear_cache) |
| `luminos_lib/code.py` | Language detection, LOC counting |
| `luminos_lib/disk.py` | Per-directory disk usage |
| `luminos_lib/filetypes.py` | File classification (7 categories) |
| `luminos_lib/prompts.py` | AI system prompt templates |
| `luminos_lib/recency.py` | Recently modified files |
| `luminos_lib/report.py` | Terminal report formatter |
| `luminos_lib/tree.py` | Directory tree visualization |

Details: wiki — [Architecture](https://forgejo.labbity.unbiasedgeek.com/archeious/luminos/wiki/Architecture) | [Development Guide](https://forgejo.labbity.unbiasedgeek.com/archeious/luminos/wiki/DevelopmentGuide)

---

## Key Constraints

- **AI investigation is the product.** The base scan exists to feed the agent.
  There is no `--ai` flag and no `--no-ai` mode. AI runs unconditionally on
  every invocation.
- **Anthropic API key is required.** If `ANTHROPIC_API_KEY` is unset, luminos
  exits cleanly (exit 0) with a one-line hint instead of running.
- **Dependencies installed via `requirements.txt`.** anthropic, tree-sitter +
  grammars, and python-magic are normal pip dependencies, not lazy imports.
  `setup_env.sh` creates a venv and installs them.
- **Subprocess for OS tools.** LOC counting, file detection, disk usage, and
  recency shell out to GNU coreutils. Do not reimplement in pure Python.
- **Graceful degradation everywhere.** Permission denied, subprocess timeouts,
  individual dir-loop failures — all handled without crashing the run.

---

## Running Luminos

```bash
# Activate the venv (one-time setup: ./setup_env.sh)
source ~/luminos-env/bin/activate
export ANTHROPIC_API_KEY=your-key-here

# Run an investigation
python3 luminos.py <target>

# Common flags
python3 luminos.py -d 8 -a -x .git -x node_modules <target>
python3 luminos.py --json -o report.json <target>
python3 luminos.py --fresh <target>
python3 luminos.py --clear-cache
```

---

## Project-Specific Test Notes

Run tests with `python3 -m unittest discover -s tests/`. Modules exempt from
unit testing: `ai.py` (requires live API), `ast_parser.py` (requires
tree-sitter grammars at import time), `prompts.py` (string templates only).

(Development workflow, branching discipline, and session protocols live in
`~/.claude/CLAUDE.md`.)

---

## Naming Conventions

| Context | Convention | Example |
|---|---|---|
| Functions / variables | snake_case | `classify_files`, `dir_path` |
| Classes | PascalCase | `_TokenTracker`, `_CacheManager` |
| Constants | UPPER_SNAKE_CASE | `MAX_CONTEXT`, `CACHE_ROOT` |
| Module files | snake_case | `ast_parser.py` |
| CLI flags | kebab-case | `--clear-cache`, `--fresh` |
| Private functions | leading underscore | `_run_synthesis` |

---

## Session Log

| # | Date | Summary |
|---|---|---|
| 6 | 2026-04-07 | Extracted shared workflow/branching/protocols from project CLAUDE.md to global `~/.claude/CLAUDE.md`; moved externalize.md and wrap-up.md to `~/.claude/protocols/` |
| 7 | 2026-04-07 | Phase 1 audit — closed #1 (only #54 remains); gitea MCP credential overhaul: dedicated `claude-code` Forgejo user, admin on luminos, write+delete verified end-to-end |
| 8 | 2026-04-07 | Closed #54 — added confidence/confidence_reason to write_cache tool schema description; Phase 1 milestone now 4/4 complete |

Full log: wiki — [Session Retrospectives](https://forgejo.labbity.unbiasedgeek.com/archeious/luminos/wiki/SessionRetrospectives)
