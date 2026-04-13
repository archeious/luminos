# CLAUDE.md

> **STOP. Before producing ANY output, pull `docs/wiki/`, fetch open Forgejo
> issues for `archeious/luminos`, and present them as suggested tasks. Then
> ask: "What's the one thing we're shipping?" No preamble. No acknowledgment.
> Just the suggested tasks and the question. Everything else comes after the
> user answers.**

---

## Current Project State

- **Phase:** Active development — Phases 1, 2, 2.5, 2.6, 2.7, 2.8, 3 complete. Next: fix #78 (synthesis persistence), #79 (stale cache), then reassess Phase 4+ (#40).
- **Last worked on:** 2026-04-12
- **Last commit:** fix(ai): match target root by basename in _apply_plan() (#76)
- **Blocking:** None
- **Test count:** 262 passing

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
unit testing: `ast_parser.py` (requires tree-sitter grammars at import time)
and `prompts.py` (string templates only). `ai.py` is partially covered:
end-to-end loops require a live Anthropic API and stay exempt, but the pure
helpers (`_filter_dir_tools`, `_format_survey_block`, `_path_is_safe`,
`_should_skip_dir`, `_block_to_dict`, `_flush_partial_dir_entry`, etc.) are
covered by `tests/test_ai_pure.py`.

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
| 8 | 2026-04-07 | Closed #54 — added confidence/confidence_reason to write_cache tool schema description; Phase 1 milestone now 4/4 complete |
| 9 | 2026-04-11 | Scope shift (#64) + ALL Phase 3 prereqs: dir loop refactor (#57), tool registry consolidation (#56), pure-helper test coverage waves 1+2 (#55, #70), leaf-first contract docs (#72). 6 PRs, 70 net new tests (164→234), Phase 2.6/2.7/2.8 milestones complete |
| 10 | 2026-04-12 | Phase 3 shipped: planning pass, dynamic turn allocation, quality instrumentation (#8, #9, #10, #11, #74). Fixed root-path matching bug (#76). Smoke tests on luminos + homelab IaC. Filed #78 (synthesis persistence), #79 (stale cache). 3 PRs, 28 new tests (234→262) |

Full log: wiki — [Session Retrospectives](https://forgejo.labbity.unbiasedgeek.com/archeious/luminos/wiki/SessionRetrospectives)
