# CLAUDE.md

> **STOP. Before producing ANY output, pull `docs/wiki/`, fetch open Forgejo
> issues for `archeious/luminos`, and present them as suggested tasks. Then
> ask: "What's the one thing we're shipping?" No preamble. No acknowledgment.
> Just the suggested tasks and the question. Everything else comes after the
> user answers.**

---

## Current Project State

- **Phase:** Active development — Phase 2 + 2.5 complete; documentation deep dive complete (#53); Phase 3 (investigation planning) ready to start
- **Last worked on:** 2026-04-06
- **Last commit:** merge: docs/issue-53-onboarding-internals (#53)
- **Blocking:** None

---

## Project Overview

Luminos is a file system intelligence tool — a zero-dependency Python CLI that
scans a directory and produces a reconnaissance report. With `--ai` it runs a
multi-pass agentic investigation via the Claude API.

---

## Module Map

| Module | Purpose |
|---|---|
| `luminos.py` | Entry point — arg parsing, scan(), main() |
| `luminos_lib/ai.py` | Multi-pass agentic analysis via Claude API |
| `luminos_lib/ast_parser.py` | tree-sitter code structure parsing |
| `luminos_lib/cache.py` | Investigation cache management |
| `luminos_lib/capabilities.py` | Optional dep detection, cache cleanup |
| `luminos_lib/code.py` | Language detection, LOC counting |
| `luminos_lib/disk.py` | Per-directory disk usage |
| `luminos_lib/filetypes.py` | File classification (7 categories) |
| `luminos_lib/prompts.py` | AI system prompt templates |
| `luminos_lib/recency.py` | Recently modified files |
| `luminos_lib/report.py` | Terminal report formatter |
| `luminos_lib/tree.py` | Directory tree visualization |
| `luminos_lib/watch.py` | Watch mode with snapshot diffing |

Details: wiki — [Architecture](https://forgejo.labbity.unbiasedgeek.com/archeious/luminos/wiki/Architecture) | [Development Guide](https://forgejo.labbity.unbiasedgeek.com/archeious/luminos/wiki/DevelopmentGuide)

---

## Key Constraints

- **Base tool: no pip dependencies.** tree, filetypes, code, disk, recency,
  report, watch use only stdlib and GNU coreutils. Must always work on bare Python 3.
- **AI deps are lazy.** `anthropic`, `tree-sitter`, `python-magic` imported only
  when `--ai` is used. Missing packages produce a clear install error.
- **Subprocess for OS tools.** LOC counting, file detection, disk usage, and
  recency shell out to GNU coreutils. Do not reimplement in pure Python.
- **Graceful degradation everywhere.** Permission denied, subprocess timeouts,
  missing API key — all handled without crashing.

---

## Running Luminos

```bash
# Base scan
python3 luminos.py <target>

# With AI analysis (requires ANTHROPIC_API_KEY)
source ~/luminos-env/bin/activate
python3 luminos.py --ai <target>

# Common flags
python3 luminos.py -d 8 -a -x .git -x node_modules <target>
python3 luminos.py --json -o report.json <target>
python3 luminos.py --watch <target>
python3 luminos.py --install-extras
```

---

## Project-Specific Test Notes

Run tests with `python3 -m unittest discover -s tests/`. Modules exempt from
unit testing: `ai.py` (requires live API), `ast_parser.py` (requires
tree-sitter), `watch.py` (stateful events), `prompts.py` (string templates
only).

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
| CLI flags | kebab-case | `--clear-cache`, `--install-extras` |
| Private functions | leading underscore | `_run_synthesis` |

---

## Session Log

| # | Date | Summary |
|---|---|---|
| 3 | 2026-04-06 | Phase 1 complete (#1–#3), MCP backend architecture design (Part 10, Phase 3.5), issues #38–#40 opened |
| 4 | 2026-04-06 | Phase 2 + 2.5 complete (#4–#7, #42, #44), filetype classifier rebuild, context budget metric fix, 8 PRs merged, issues #46/#48/#49/#51 opened |
| 5 | 2026-04-06 | Documentation deep dive (#53): new Internals.md code tour, Architecture cache fix, Roadmap replaced with pointer, PLAN.md status snapshot |

Full log: wiki — [Session Retrospectives](https://forgejo.labbity.unbiasedgeek.com/archeious/luminos/wiki/SessionRetrospectives)
