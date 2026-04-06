# CLAUDE.md

> Before starting any session: what's the one thing we're shipping today?

---

## Current Project State

- **Phase:** Active development — core pipeline stable, planning and domain intelligence work next
- **Last worked on:** 2026-04-06
- **Last commit:** merge: add -x/--exclude flag for directory exclusion
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

## Git Workflow

Every change starts on a branch. Nothing goes directly to main.

```bash
git checkout -b <type>/<short-description>
# ... work ...
git checkout main
git merge --no-ff <branch> -m "merge: <description>"
git branch -d <branch>
```

| Type | Use |
|---|---|
| `feat/` | New feature |
| `fix/` | Bug fix |
| `refactor/` | No behavior change |
| `chore/` | Tooling, docs, config |

Commit format: `<type>: <short description>`

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

## Documentation

Wiki lives at `docs/wiki/` (gitignored — separate git repo).

```bash
# First time
git clone ssh://git@forgejo-claude/archeious/luminos.wiki.git docs/wiki/
# Returning
git -C docs/wiki pull
```

Wiki: https://forgejo.labbity.unbiasedgeek.com/archeious/luminos/wiki

---

## Session Protocols

See `~/.claude/CLAUDE.md`

---

## Session Log

| Date | Summary |
|---|---|
| 2026-04-06 | Session 1: scan progress output, in-place per-file display, --exclude flag, Forgejo repo, PLAN.md, wiki setup, development practices |

Full log: wiki — [Session Retrospectives](https://forgejo.labbity.unbiasedgeek.com/archeious/luminos/wiki/SessionRetrospectives)
