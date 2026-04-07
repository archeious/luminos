# CLAUDE.md

> **STOP. Before producing ANY output, pull `docs/wiki/`, fetch open Forgejo
> issues for `archeious/luminos`, and present them as suggested tasks. Then
> ask: "What's the one thing we're shipping?" No preamble. No acknowledgment.
> Just the suggested tasks and the question. Everything else comes after the
> user answers.**

---

## Current Project State

- **Phase:** Active development — Phase 1 (confidence tracking) complete, Phase 2 (survey pass) ready to start
- **Last worked on:** 2026-04-06
- **Last commit:** merge: feat/issue-3-low-confidence-entries (#3)
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

## Development Workflow

- **Issue-driven work** — all work must be tied to a Forgejo issue. If the
  user names a specific issue, use it. If they describe work without an issue
  number, search open issues for a match. If no issue exists, gather enough
  context to create one before starting work. Branches and commits should
  reference the issue number.
- **Explain then build** — articulate the approach in a few bullets before
  writing code. Surface assumptions early.
- **Atomic commits** — each commit is one logical change.
- **Test coverage required** — every change to a testable module must include
  or update tests in `tests/`. Run with `python3 -m unittest discover -s tests/`.
  All tests must pass before merging. Modules exempt from unit testing:
  `ai.py` (requires live API), `ast_parser.py` (requires tree-sitter),
  `watch.py` (stateful events), `prompts.py` (string templates only).
- **Shiny object capture** — new ideas go to PLAN.md (Raw Thoughts) or a
  Forgejo issue, not into current work.

---

## Branching Discipline

- **Always branch** — no direct commits to main, ever
- **Branch before first change** — create the branch before touching any files
- **Naming:** `feat/`, `fix/`, `refactor/`, `chore/` + short description
- **One branch, one concern** — don't mix unrelated changes
- **Two-branch maximum** — never have more than 2 unmerged branches
- **Merge with `--no-ff`** — preserves branch history in the log
- **Delete after merge** — `git branch -d <branch>` immediately after merge
- **Push after commits** — keep Forgejo in sync after each commit or logical batch

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

## Documentation Workflow

- **Wiki location:** `docs/wiki/` — local git checkout of `luminos.wiki.git`
- **Clone URL:** `ssh://git@forgejo-claude/archeious/luminos.wiki.git`
- **Session startup:** clone if missing, `git -C docs/wiki pull` if present
- **All reads and writes** happen on local files in `docs/wiki/`. Use Read,
  Edit, Write, Grep, Glob — never the Forgejo web API for wiki content.
- **Naming:** CamelCase slugs (`Architecture.md`, `DevelopmentGuide.md`).
  Display name comes from the H1 heading inside the file.
- **Commits:** direct to main branch. Batch logically — commit when finishing
  a round of updates, not after every file.
- **Push:** after each commit batch.

---

## ADHD Session Protocols

> **MANDATORY — follow literally, every session, no exceptions.**

1. **Session Start Ritual** — Ensure `docs/wiki/` is cloned and current.
   Fetch open issues from Forgejo (`archeious/luminos`) and present them as
   suggested tasks. Ask: *"What's the one thing we're shipping?"* Once the
   user answers, match to an existing issue or create one before starting
   work. Do NOT summarize project state, recap history, or do any other work
   before asking this question.

2. **Dopamine-Friendly Task Sizing** — break work into 5–15 minute tasks with
   clear, visible outputs. Each task should have a moment of completion.

3. **Focus Guard** — classify incoming requests as on-topic / adjacent /
   off-topic. Name it out loud before acting. Adjacent work goes to a new
   issue; off-topic work gets deferred.

4. **Shiny Object Capture** — when a new idea surfaces mid-session, write it
   to PLAN.md (Raw Thoughts) or open a Forgejo issue, then return to the
   current task. Do not context-switch.

5. **Breadcrumb Protocol** — after each completed task, output:
   `Done: <what was completed>. Next: <what comes next>.`
   This re-orients after any interruption.

6. **Session End Protocol** — before closing, state the exact pickup point for
   the next session: branch name, file, what was in progress, and the
   recommended first action next time.

---

## Session Protocols

- **"externalize"** → read and follow `docs/externalize.md`
- **"wrap up" / "end session"** → read and follow `docs/wrap-up.md`

---

## Session Log

| # | Date | Summary |
|---|---|---|
| 1 | 2026-04-06 | Project setup, scan progress output, in-place file display, --exclude flag, Forgejo repo, PLAN.md, wiki, development practices |
| 2 | 2026-04-06 | Forgejo milestones (9), issues (36), project board, Gitea MCP installed and configured globally |
| 3 | 2026-04-06 | Phase 1 complete (#1–#3), MCP backend architecture design (Part 10, Phase 3.5), issues #38–#40 opened |

Full log: wiki — [Session Retrospectives](https://forgejo.labbity.unbiasedgeek.com/archeious/luminos/wiki/SessionRetrospectives)
