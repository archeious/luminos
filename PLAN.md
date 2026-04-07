# Luminos — Evolution Plan

## Core Philosophy

The current design is a **pipeline with AI steps**. Even though it uses an
agent loop, the structure is predetermined:

```
investigate every directory (leaf-first) → synthesize → done
```

The agent executes a fixed sequence. It cannot decide what matters most, cannot
resolve its own uncertainty, cannot go get information it's missing, cannot
adapt its strategy based on what it finds.

The target philosophy is **investigation driven by curiosity**:

```
survey → form hypotheses → investigate to confirm/refute →
resolve uncertainty → update understanding → repeat until satisfied
```

This is how a human engineer actually explores an unfamiliar codebase or file
collection. The agent should decide *what it needs to know* and *how to find
it out* — not execute a predetermined checklist.

Every feature in this plan should be evaluated against that principle.

---

## Part 1: Uncertainty as a First-Class Concept

### The core loop

The agent explicitly tracks confidence at each step. Low confidence is not
noted and moved past — it triggers a resolution strategy.

```
observe something
    → assess confidence
    → if high: cache and continue
    → if low: choose resolution strategy
        → read more local files
        → search externally (web, package registry, docs)
        → ask the user
        → flag as genuinely unknowable with explicit reasoning
    → update understanding
    → continue
```

This should be reflected in the dir loop prompt, the synthesis prompt, and the
refinement prompt. "I don't know" is never an acceptable terminal state if
there are resolution strategies available.

### Confidence tracking in cache entries

Add a `confidence` field (0.0–1.0) to both file and dir cache entries. The
agent sets this when writing cache. Low-confidence entries are candidates for
refinement-pass investigation.

File cache schema addition:
```
confidence: float        # 0.0–1.0, agent's confidence in its summary
confidence_reason: str   # why confidence is low, if below ~0.7
```

The synthesis and refinement passes can use confidence scores to prioritize
what to look at again.

---

## Part 2: Dynamic Domain Detection

### Why not a hardcoded taxonomy

A fixed domain list (code, documents, data, media, mixed) forces content into
predetermined buckets. Edge cases are inevitable: a medical imaging archive,
a legal discovery collection, a CAD project, a music production session, a
Jupyter notebook repo that's half code and half data. Hardcoded domains require
code changes to handle novel content and will always mis-classify ambiguous cases.

More fundamentally: the AI is good at recognizing what something is. Using
rule-based file-type ratios to gate its behavior is fighting the tool's
strengths.

### Survey pass (replaces hardcoded detection)

Before dir loops begin, a lightweight survey pass runs:

**Input**: file type distribution, tree structure (top 2 levels), total counts

**Task**: the survey agent answers three questions:
1. What is this? (plain language description, no forced taxonomy)
2. What analytical approach would be most useful?
3. Which available tools are relevant and which can be skipped?

**Output** (`submit_survey` tool):
```python
{
    "description": str,          # "a Python web service with Postgres migrations"
    "approach": str,             # how to investigate — what to prioritize, what to skip
    "relevant_tools": [str],     # tools worth using for this content
    "skip_tools": [str],         # tools not useful (e.g. parse_structure for a journal)
    "domain_notes": str,         # anything unusual the dir loops should know
    "confidence": float,         # how clear the signal was
}
```

**Max turns**: 3 — this is a lightweight orientation pass, not a deep investigation.

This output is injected into the dir loop system prompt as context. The dir
loops know what they're looking at before they start. They can also deviate if
they find something the survey missed.

### Tools are always available, AI selects what's relevant

Rather than gating tools by domain, every tool is offered with a clear
description of what it's for. The AI simply won't call `parse_structure` on
a `.xlsx` file because the description says it works on source files.

This also means new tools are automatically available to all future domains
without any profile configuration.

### What stays rule-based

The file type distribution summary fed into the survey prompt is still computed
from `filetypes.py` — this is cheap and provides useful signal. The difference
is that the AI interprets it rather than a lookup table.

---

## Part 3: External Knowledge Tools

### The resolution strategy toolkit

When the agent encounters something it doesn't understand, it has options beyond
"read more local files." These are resolution strategies for specific kinds of
uncertainty.

**`web_search(query) → results`**

Use when: unfamiliar library, file format, API, framework, toolchain, naming
convention that doesn't resolve from local files alone.

Query construction should be evidence-based:
- Seeing `import dramatiq` → `"dramatiq python task queue library"`
- Finding `.avro` files → `"apache avro file format schema"`
- Spotting unfamiliar config key → `"<framework> <key> configuration"`

Results are summarized before injection into context. Raw search results are
not passed directly — a lightweight extraction pulls the relevant 2-3 sentences.

Budget: configurable max searches per session (default: 10). Logged in report.

**`fetch_url(url) → content`**

Use when: a local file references a URL that would explain what the project is
(e.g. a README links to documentation, a config references a schema URL, a
package.json has a homepage field).

Constrained to read-only fetches. Content truncated to relevant sections.
Budget: configurable (default: 5 per session).

**`package_lookup(name, ecosystem) → metadata`**

Use when: an import or dependency declaration references an unfamiliar package.

Queries package registries (PyPI, npm, crates.io, pkg.go.dev) for:
- Package description
- Version in use vs latest
- Known security advisories (if available)
- License

This is more targeted than web search and returns structured data. Particularly
useful for security-relevant analysis.

Budget: generous (default: 30) since queries are cheap and targeted.

**`ask_user(question) → answer`**  *(interactive mode only)*

Use when: uncertainty cannot be resolved by any other means.

Examples:
- "I found 40 files with `.xyz` extension I don't recognize — what format is this?"
- "There are two entry points (server.py and worker.py) — which is the primary one?"
- "This directory appears to contain personal data — should I analyze it or skip it?"

Only triggered when other resolution strategies have been tried or are clearly
not applicable. Gated behind an `--interactive` flag since it blocks execution.

### All external tools are opt-in

`--no-external` flag disables all network tools (web_search, fetch_url,
package_lookup). Default behavior TBD — arguably external lookups should be
opt-in rather than opt-out given privacy considerations (see Concerns).

---

## Part 4: Investigation Planning

### Survey → plan → execute

Currently: every directory is processed in leaf-first order with equal
resource allocation. A 2-file directory gets the same max_turns as a 50-file
one.

Better: after the survey pass, a planning step decides where to invest depth.

**Planning pass** (`submit_plan` tool):

Input: survey output + full directory tree

Output:
```python
{
    "priority_dirs": [           # investigate these deeply
        {"path": str, "reason": str, "suggested_turns": int}
    ],
    "shallow_dirs": [            # quick pass only
        {"path": str, "reason": str}
    ],
    "skip_dirs": [               # skip entirely (generated, vendored, etc.)
        {"path": str, "reason": str}
    ],
    "investigation_order": str,  # "leaf-first" | "priority-first" | "breadth-first"
    "notes": str,                # anything else the investigation should know
}
```

The orchestrator uses this plan to allocate turns per directory and set
investigation order. The plan is also saved to cache so resumed investigations
can follow the same strategy.

### Dynamic turn allocation

Replace fixed `max_turns=14` per directory with a global turn budget the agent
manages. The planning pass allocates turns to directories based on apparent
complexity. The agent can request additional turns mid-investigation if it hits
something unexpectedly complex.

A simple model:
- Global budget = `base_turns_per_dir * dir_count` (e.g. 10 * 20 = 200)
- Planning pass distributes: priority dirs get 15-20, shallow dirs get 5, skip dirs get 0
- Agent can "borrow" turns from its own budget if it needs more
- If budget runs low, a warning is injected into the prompt

---

## Part 5: Scale-Tiered Synthesis

### Why tiers are still needed

Even with better investigation planning and agentic depth control, the synthesis
input problem remains: 300 directory summaries cannot be meaningfully synthesized
in one shot. The output is either truncated, loses fidelity, or both.

Tier classification based on post-loop measurements:

| Tier | dir_count | file_count | Synthesis approach |
|---|---|---|---|
| `small` | < 5 | < 30 | Feed per-file cache entries directly |
| `medium` | 5–30 | 30–300 | Dir summaries (current approach) |
| `large` | 31–150 | 301–1500 | Multi-level synthesis |
| `xlarge` | > 150 | > 1500 | Multi-level + subsystem grouping |

Thresholds configurable via CLI flags or config file.

### Small tier: per-file summaries

File cache entries are the most granular, most grounded signal in the system —
written while the AI was actually reading files. For small targets they fit
comfortably in the synthesis context window and produce a richer output than
dir summaries.

### Multi-level synthesis (large/xlarge)

```
dir summaries
    ↓  (grouping pass: dirs → subsystems, AI-identified)
subsystem summaries (3–10 groups)
    ↓  (final synthesis)
report
```

The grouping pass is itself agentic: the AI identifies logical subsystems from
dir summaries, not from directory structure. An `auth/` dir and a
`middleware/session/` dir might end up in the same "Authentication" subsystem.

For xlarge:
```
dir summaries
    ↓  (level-1: dirs → subsystems, 10–30 groups)
    ↓  (level-2: subsystems → domains/layers, 3–8 groups)
    ↓  (final synthesis)
```

### Synthesis depth scales with tier

The synthesis prompt receives explicit depth guidance:

- **small**: "Be concise but specific. Reference actual filenames. 2–3 paragraphs."
- **medium**: "Produce a structured breakdown. Cover purpose, components, concerns."
- **large**: "Produce a thorough architectural analysis with section headers. Be specific."
- **xlarge**: "Produce a comprehensive report. Cover architecture, subsystems, interfaces, cross-cutting concerns, and notable anomalies. Reference actual paths."

---

## Part 6: Hypothesis-Driven Synthesis

### Current approach: aggregation

Synthesis currently aggregates dir summaries into a report. It's descriptive:
"here is what I found in each part."

### Better approach: conclusion with evidence

The synthesis agent should:
1. Form an initial hypothesis about the whole from the dir summaries
2. Look for evidence that confirms or refutes it
3. Consider alternative interpretations
4. Produce a conclusion that reflects the reasoning, not just the observations

This produces output like: *"This appears to be a multi-tenant SaaS backend
(hypothesis) — the presence of tenant_id throughout the schema, separate
per-tenant job queues, and the auth middleware's scope validation all support
this (evidence). The monolith structure suggests it hasn't been decomposed into
services yet (alternative consideration)."*

Rather than: *"The auth directory handles authentication. The jobs directory
handles background jobs. The models directory contains database models."*

The `think` tool already supports this pattern — the synthesis prompt should
explicitly instruct hypothesis formation before `submit_report`.

---

## Part 7: Refinement Pass

### Trigger

`--refine` flag. Off by default.

### What it does

After synthesis, the refinement agent receives:
- Current synthesis output (brief + full analysis)
- All dir and file cache entries including confidence scores
- Full investigation toolset including external knowledge tools
- A list of low-confidence cache entries (confidence < 0.7)

It is instructed to:
1. Identify gaps (things not determined from summaries)
2. Identify contradictions (dir summaries that conflict)
3. Identify cross-cutting concerns (patterns spanning multiple dirs)
4. Resolve low-confidence entries
5. Submit an improved report

The refinement agent owns its investigation — it decides what to look at and
in what order, using the full resolution strategy toolkit.

### Multiple passes

`--refine-depth N` runs N refinement passes. Natural stopping condition: the
agent calls `submit_report` without making any file reads or external lookups
(indicates nothing new was found). This can short-circuit before N passes.

### Refinement vs re-investigation

Refinement is targeted — it focuses on specific gaps and uncertainties. It is
not a re-run of the full dir loops. The prompt makes this explicit:
*"Focus on resolving uncertainty, not re-summarizing what is already known."*

---

## Part 8: Report Structure

### Domain-appropriate sections

Instead of fixed `brief` + `detailed` fields, the synthesis produces structured
fields based on what the survey identified. Fields that are absent or empty are
not rendered.

The survey output's `description` shapes what fields are relevant. This is not
a hardcoded domain → schema mapping — the synthesis prompt asks the agent to
populate fields that are relevant to *this specific content* from a superset
of available fields:

```
Available output fields (populate those relevant to this content):
- brief           (always)
- architecture    (software projects)
- components      (software projects, large document collections)
- tech_stack      (software projects)
- entry_points    (software projects, CLI tools)
- datasets        (data collections)
- schema_summary  (data collections, databases)
- period_covered  (financial data, journals, time-series)
- themes          (document collections, journals)
- data_quality    (data collections)
- concerns        (any domain)
- overall_purpose (mixed/composite targets)
```

The report formatter renders populated fields with appropriate headers and
skips unpopulated ones. Small simple targets produce minimal output. Large
complex targets produce full structured reports.

### Progressive output (future)

Rather than one report at the end, stream findings as the investigation
proceeds. The user sees the agent's understanding build in real time. This
converts luminos from a batch tool into an interactive investigation partner.

Requires a streaming-aware output layer — significant architectural change,
probably not Phase 1.

---

## Part 9: Parallel Investigation

### For large targets

Multiple dir-loop agents investigate different subsystems concurrently, then
report to a coordinator. The coordinator synthesizes their findings and
identifies cross-cutting concerns.

This requires:
- A coordinator agent that owns the investigation plan
- Worker agents scoped to subsystems
- A shared cache that workers write to concurrently (needs locking or
  append-only design)
- A merge step in the coordinator before synthesis

Significant complexity. Probably deferred until single-agent investigation
quality is high. The main benefit is speed, not quality — worth revisiting when
the investigation quality ceiling has been reached.

---

## Part 10: MCP Backend Abstraction

### Why

The investigation loop (survey → plan → investigate → synthesize) is
generic. The filesystem-specific parts — how to list a directory, read
a file, parse structure — are an implementation detail. Abstracting
the backend via MCP decouples the two and makes luminos extensible to
any exploration target: websites, wikis, databases, running processes.

This pivot also serves the project's learning goal. Migrating working
code into an agentic framework is a common and painful real-world task.
Building it clean from the start teaches the pattern; migrating teaches
*why* the pattern exists. The migration pain is intentional.

### The model

Each exploration target is an MCP server. Luminos is an MCP client.
The investigation loop connects to a server at startup, discovers its
tools, passes them to the Anthropic API, and forwards tool calls to
the server at runtime.

```
luminos (MCP client)
    ↓  connects to
filesystem MCP server  |  process MCP server  |  wiki MCP server  |  ...
    ↓  exposes tools
read_file, list_dir, parse_structure, ...
    ↓  passed to
Anthropic API (agent calls them)
    ↓  forwarded back to
MCP server (executes, returns result)
```

The filesystem MCP server is the default. `--mcp <uri>` selects
an alternative server.

### What changes

- `ai.py` tool dispatch: instead of calling local Python functions,
  forward to the connected MCP server
- Tool definitions: dynamically discovered from the server via
  `tools/list`, not hardcoded in `ai.py`
- New `luminos_lib/mcp_client.py`: thin MCP client (stdio transport)
- New `luminos_mcp/filesystem.py`: MCP server wrapping existing
  filesystem tools (`read_file`, `list_dir`, `parse_structure`,
  `run_command`, `stat_file`)
- `--mcp` CLI flag for selecting a non-default server

### What does not change

Cache storage, confidence tracking, survey/planning/synthesis passes,
token tracking, cost reporting, all prompts. None of these know or
care what backend provided the data.

### Known tensions

**The tree assumption.** The investigation loop assumes hierarchical
containers. Non-filesystem backends (websites, processes) must present
a virtual tree or the traversal model breaks. This is the MCP server's
problem to solve, not luminos's — but it is real design work.

**Tool count.** If multiple MCP servers are connected simultaneously
(filesystem + web search + package lookup), tool count grows. More
tools degrades agent decision quality. Keep each server focused.

**The filesystem backend is a demotion.** Currently filesystem
investigation is native — zero overhead. Making it an MCP server adds
process-launch overhead. Acceptable given API call latency already
dominates, but worth knowing.

**Phase 4 becomes MCP servers.** After the pivot, web_search,
fetch_url, and package_lookup are natural candidates to implement as
MCP servers rather than hardcoded Python functions. Phase 4 and the
MCP pattern reinforce each other.

### Timing

After Phase 3, before Phase 4. At that point survey + planning +
dir loops + synthesis are all working with filesystem assumptions
baked in — enough surface area to make the migration instructive
without 9 phases of rework.

---

## Implementation Order

### Phase 1 — Confidence tracking
- Add `confidence` + `confidence_reason` to cache schemas
- Update dir loop prompt to set confidence when writing cache
- No behavior change yet — just instrumentation

### Phase 2 — Survey pass
- New `_run_survey()` function in `ai.py`
- `submit_survey` tool definition
- `_SURVEY_SYSTEM_PROMPT` in `prompts.py`
- Wire into `_run_investigation()` before dir loops
- Survey output injected into dir loop system prompt
- **Rebuild filetype classifier (#42)** to remove source-code bias —
  lands after the survey pass is observable end-to-end (#4–#7) and
  before Phase 3 starts depending on survey output for real decisions.
  Until then, the survey prompt carries a Band-Aid warning that the
  histogram is biased toward source code.

### Phase 3 — Investigation planning
- Planning pass after survey, before dir loops
- `submit_plan` tool
- Dynamic turn allocation based on plan
- Dir loop orchestrator updated to follow plan

### Phase 3.5 — MCP backend abstraction (pivot point)
See Part 10 for full design. This phase happens *after* Phase 3 is
working and *before* Phase 4. The goal is to migrate the filesystem
investigation into an MCP server/client model before adding more
backends or external tools.

- Extract filesystem tools (`read_file`, `list_dir`, `parse_structure`,
  `run_command`, `stat_file`) into a standalone MCP server
- Refactor `ai.py` into an MCP client: discover tools dynamically,
  forward tool calls to the server, return results to the agent
- Replace hardcoded tool list in the dir loop with dynamic tool
  discovery from the connected MCP server
- Keep the filesystem MCP server as the default; `--mcp` flag selects
  alternative servers
- No behavior change to the investigation loop — purely structural

**Learning goal:** experience migrating working code into an MCP
architecture. The migration pain is intentional and instructive.

### Phase 4 — External knowledge tools
- `web_search` tool + implementation (requires optional dep: search API client)
- `package_lookup` tool + implementation (HTTP to package registries)
- `fetch_url` tool + implementation
- `--no-external` flag to disable network tools
- Budget tracking and logging

### Phase 5 — Scale-tiered synthesis
- Sizing measurement after dir loops
- Tier classification
- Small tier: switch synthesis input to file cache entries
- Depth instructions in synthesis prompt

### Phase 6 — Multi-level synthesis
- Grouping pass + `submit_grouping` tool
- Final synthesis receives subsystem summaries at large/xlarge tier
- Two-level grouping for xlarge

### Phase 7 — Hypothesis-driven synthesis
- Update synthesis prompt to require hypothesis formation before submit_report
- `think` tool made available in synthesis (currently restricted)

### Phase 8 — Refinement pass
- `--refine` flag + `_run_refinement()`
- Refinement uses confidence scores to prioritize
- `--refine-depth N`

### Phase 9 — Dynamic report structure
- Superset output fields in synthesis submit_report schema
- Report formatter renders populated fields only
- Domain-appropriate section headers

---

## File Map

| File | Changes |
|---|---|
| `luminos_lib/domain.py` | **new** — survey pass, plan pass, profile-free detection |
| `luminos_lib/prompts.py` | survey prompt, planning prompt, refinement prompt, updated dir/synthesis prompts |
| `luminos_lib/ai.py` | survey, planning, external tools, tiered synthesis, multi-level grouping, refinement, confidence-aware cache writes |
| `luminos_lib/cache.py` | confidence fields in schemas, low-confidence query |
| `luminos_lib/report.py` | dynamic field rendering, domain-appropriate sections |
| `luminos.py` | --refine, --no-external, --refine-depth flags; wire survey into scan |
| `luminos_lib/search.py` | **new** — web_search, fetch_url, package_lookup implementations |

No changes needed to: `tree.py`, `filetypes.py`, `code.py`, `recency.py`,
`disk.py`, `capabilities.py`, `watch.py`, `ast_parser.py`

---

## Known Unknowns

**Search API choice**
Web search requires an API (Brave Search, Serper, SerpAPI, DuckDuckGo, etc.).
Each has different pricing, rate limits, result quality, and privacy
implications. Which one to use, whether to require an API key, and what the
fallback is when no key is configured — all undecided. Could support multiple
backends with a configurable preference.

**Package registry coverage**
`package_lookup` needs to handle PyPI, npm, crates.io, pkg.go.dev, Maven,
RubyGems, NuGet at minimum. Each has a different API shape. Coverage gap for
less common ecosystems (Hex for Elixir, Hackage for Haskell, etc.) — the agent
will get no lookup result and must fall back to web search.

**search result summarization**
Raw search results can't be injected directly into context — they're too long
and too noisy. A summarization step is needed. Options: another AI call (adds
latency and cost), regex extraction (fragile), a lightweight extraction
heuristic. The right approach is unclear.

**Turn budget arithmetic**
Dynamic turn allocation sounds clean in theory. In practice: how does the
agent "request more turns"? The orchestrator has to interrupt the loop,
check the global budget, and decide whether to grant more. This requires
mid-loop communication that doesn't exist today. Implementation complexity
is non-trivial.

**Cache invalidation on strategy changes**
If a user re-runs with different flags (--refine, --no-external, new --exclude
list), the existing cache entries may have been produced under a different
investigation strategy. Should they be invalidated? Currently --fresh is the
only mechanism. A smarter approach would store the investigation parameters
in cache metadata and detect mismatches.

**Confidence calibration**
Asking the agent to self-report confidence (0.0–1.0) is only useful if the
numbers are meaningful and consistent. LLMs are known to be poorly calibrated
on confidence. A 0.6 from one run may not mean the same as 0.6 from another.
This may need to be a categorical signal (high/medium/low) rather than numeric
to be reliable in practice.

**Context window growth with external tools**
Each web search result, package lookup, and URL fetch adds to the context
window for that dir loop. For a directory with many unknown dependencies, the
context could grow large enough to trigger the budget early exit. Need to think
about how external tool results are managed in context — perhaps summarized and
discarded from messages after being processed.

**`ask_user` blocking behavior**
Interactive mode with `ask_user` would block execution waiting for input. This
is fine in a terminal session but incompatible with piped output, scripted use,
or running luminos as a subprocess. Needs a clear mode distinction and graceful
degradation when input is not a TTY.

**Survey pass quality on tiny targets**
For a target with 3 files, the survey pass adds an API call that may cost more
than it's worth. There should be a minimum size threshold below which the
survey is skipped and a generic approach is used.

**Parallel investigation complexity**
Concurrent dir-loop agents writing to a shared cache introduces race conditions.
The current `_CacheManager` writes files directly with no locking. This would
need to be addressed before parallel investigation is viable.

---

## Additional Suggestions

**Config file**
Many things that are currently hardcoded (turn budget, tier thresholds, search
budget, confidence threshold for refinement) should be user-configurable without
CLI flags. A `luminos.toml` in the target directory or `~/.config/luminos/`
would allow project-specific and user-specific defaults.

**Structured logging**
The `[AI]` stderr output is useful but informal. A structured log (JSONL file
alongside the cache) would allow post-hoc analysis of investigation quality:
which dirs used the most turns, which triggered web searches, which had low
confidence, where budget pressure hit. This also enables future tooling on top
of luminos investigations.

**Investigation replay**
The cache already stores summaries but not the investigation trace (what the
agent read, in what order, what it decided to skip). Storing the full message
history per directory would allow replaying or auditing an investigation. Cost:
storage. Benefit: debuggability, ability to resume investigations more faithfully.

**Watch mode + incremental investigation**
Watch mode currently re-runs the full base scan on changes. For AI-augmented
watch mode: detect which directories changed, re-investigate only those, and
patch the cache entries. The synthesis would then re-run from the updated cache
without re-investigating unchanged directories.

**Optional PDF and Office document readers**
The data and documents domains would benefit from native content extraction:
- `pdfminer` or `pypdf` for PDF text extraction
- `openpyxl` for Excel schema and sheet enumeration
- `python-docx` for Word document text
These would be optional deps like the existing AI deps, gated behind
`--install-extras`. The agent currently can only see filename and size for
these formats.

**Security-focused analysis mode**
A `--security` flag could tune the investigation toward security-relevant
findings: dependency vulnerability scanning, hardcoded secrets detection,
permission issues, exposed configuration, insecure patterns. The flag would
bias the survey, dir loop prompts, and synthesis toward these concerns and
expand the flags output with severity-ranked security findings.

**Output formats**
The current report is terminal-formatted text or JSON. Additional formats worth
considering:
- Markdown (for saving to wikis, Notion, Obsidian)
- HTML (self-contained report with collapsible sections)
- SARIF (for security findings — integrates with GitHub Code Scanning)

**Model selection**
The model is hardcoded to `claude-sonnet-4-20250514`. The survey and planning
passes are lightweight enough to use a faster/cheaper model (Haiku). The dir
loops and synthesis warrant Sonnet or better. The refinement pass might benefit
from Opus for difficult cases. A `--model` flag and per-pass model configuration
would allow cost/quality tradeoffs.

---

## Concerns

**Cost at scale**
Adding a survey pass, planning pass, external tool lookups, and multiple
refinement passes significantly increases API call count and token consumption.
A large repo run with `--refine` could easily cost several dollars. The current
cost reporting (total tokens at end) may not be sufficient — users need to
understand cost before committing to a long run. Consider a `--estimate` mode
that projects cost from the base scan without running AI.

**Privacy and external lookups**
Web searches and URL fetches send information about the target's contents to
external services. For a personal journal or proprietary codebase this could
be a significant privacy concern. The `--no-external` flag addresses this but
it should probably be the *default* for sensitive-looking content (PII detected
in filenames, etc.), not something the user has to know to enable.

**Prompt injection via file contents**
`read_file` passes raw file contents into the context. A malicious file in the
target directory could contain prompt injection attempts. The current system has
no sanitization. This is an existing concern that grows as the agent gains more
capabilities (web search, URL fetch, package lookup — all of which could
theoretically be manipulated by a crafted file).

**Reliability of self-reported confidence**
The confidence tracking system depends on the agent accurately reporting its
own uncertainty. If the agent is systematically over-confident (which LLMs tend
to be), the refinement pass will never trigger on cases where it's most needed.
The system should have a skeptical prior — low-confidence by default for
unfamiliar file types, missing READMEs, ambiguous structures.

**Investigation quality regression risk**
Each new pass (survey, planning, refinement) adds opportunities for the
investigation to go wrong. A bad survey misleads all subsequent dir loops. A
bad plan wastes turns on shallow directories and skips critical ones. The system
needs quality signals — probably the confidence scores aggregated across the
investigation — to detect when something went wrong and potentially retry.

**Watch mode compatibility**
Several of the planned features (survey pass, planning, external tools) are not
designed for incremental re-use in watch mode. Adding AI capability to watch
mode is a separate design problem that deserves its own thinking.

**Turn budget contention**
If the planning pass allocates turns and the agent borrows from its budget when
it needs more, there's a risk of runaway investigation on unexpectedly complex
directories. Needs a hard ceiling (global max tokens, not just per-dir turns)
as a backstop.

---

## Raw Thoughts

The investigation planning idea is conceptually appealing but has a chicken-and-
egg problem: you need to know what's in the directories to plan how to
investigate them, but you haven't investigated yet. The survey pass helps but
it's shallow. Maybe the first pass through each directory should be a cheap
orientation (list contents, read one file) that feeds the plan before the full
investigation starts. Two-phase dir investigation: orient then investigate.

The hypothesis-driven synthesis is probably the highest leverage change in this
whole plan. The current synthesis produces descriptive output. Hypothesis-driven
synthesis produces analytical output. The prompt change is small but the output
quality difference could be significant.

Web search feels like it should be a last resort, not an early one. The agent
should exhaust local investigation before reaching for external sources. The
prompt should reflect this: "Only search if you cannot determine this from the
files available."

There's a question of whether the survey pass should run before the base scan
or after. After makes sense because the base scan's file_categories is useful
survey input. But the base scan itself could be informed by the survey (e.g.
skip certain directories the survey identified as low-value). Probably the right
answer is: survey runs after base scan but before AI dir loops, using base scan
output as input.

The `ask_user` tool is interesting because it inverts the relationship — the
agent asks the human rather than the other way around. This is powerful but
needs careful constraints. The agent should only ask when it's genuinely stuck,
not as a shortcut to avoid investigation. The prompt should require that other
resolution strategies have been exhausted before asking.

Multi-level synthesis (grouping pass) might produce better results than
expected because the grouping agent has a different task than the dir-loop
agents — it's looking for relationships and patterns across summaries rather
than summarizing individual directories. It might surface architectural insights
that none of the dir loops could see individually.

Package vulnerability lookups are potentially the highest signal-to-noise
external tool — structured data, specific to the files present, directly
actionable. Worth implementing before general web search.

The confidence calibration problem is real but maybe not critical to solve
precisely. Even if 0.6 doesn't mean the same thing every time, entries with
confidence below some threshold will still tend to be the more uncertain ones.
Categorical (high/medium/low) is probably fine for the first implementation.

Progressive output and interactive mode are probably the features that would
most change how luminos *feels* to use. The current UX is: run it, wait, get a
report. Progressive output would make it feel like watching someone explore
the codebase in real time. Worth thinking about the UX before the architecture.

There's a version of this tool that goes well beyond file system analysis —
a general-purpose investigative agent that can be pointed at anything (a
directory, a URL, a database, a running process) and produce an intelligence
report. The current architecture is already pointing in that direction. Worth
keeping that possibility in mind when making structural decisions so we don't
close off that path prematurely.
