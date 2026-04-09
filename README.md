# Luminos

A file system intelligence tool. Scans a directory and produces a reconnaissance report that tells you what the directory is, what's in it, and what might be worth your attention.

Luminos has two modes. The **base mode** is a single Python file that uses only the standard library and GNU coreutils. No pip install, no virtual environment, no dependencies to audit. The **`--ai` mode** runs a multi-pass agentic investigation against the [Claude API](https://www.anthropic.com/api) to reason about what the project actually does and flag anything that looks off. AI mode is opt-in and is the only path that requires pip-installable packages.

## Why

Most "repo explorer" tools answer one question: "what files are here?" Luminos is built around a harder question: "what is this, and should I be worried about any of it?"

The base scan gives you the mechanical answer: directory tree, file classification across seven categories, language breakdown with line counts, recently modified files, disk usage, and the largest files. That is usually enough for a quick "what is this" look.

The AI mode goes further. It runs an isolated investigation per directory, leaves-first, with a small toolbelt (read files, run whitelisted coreutils commands, write cache entries) and a per-directory context budget. Each directory gets its own summary, and a final synthesis pass reads only the directory-level cache entries to produce a whole-project verdict. Findings are flagged with a severity level (`critical`, `concern`, or `info`) so the important stuff floats to the top.

## Features

- **Zero dependencies in base mode.** Runs on bare Python 3 plus the GNU coreutils you already have.
- **Graceful degradation everywhere.** Permission denied, subprocess timeouts, missing API key, missing optional packages: all handled without crashing the scan.
- **Directory tree.** Visual tree with configurable depth and exclude patterns.
- **File classification.** Files bucketed into seven categories (code, config, docs, data, media, binary, other) via `file(1)` magic.
- **Language detection and LOC counting.** Which languages are present, how many lines of code per language.
- **Recently modified files.** Surface the files most likely to reflect current activity.
- **Disk usage.** Per-directory disk usage with top offenders called out.
- **Watch mode.** Re-scan every 30 seconds and show diffs.
- **JSON output.** Pipe reports to other tools or save for comparison.
- **AI investigation (opt-in).** Multi-pass, leaves-first agentic analysis via Claude, with an investigation cache so repeat runs are cheap.
- **Severity-ranked flags.** Findings are sorted so `critical` items are the first thing you see.

## Installation

### Base mode

No installation required. Clone and run.

```bash
git clone https://github.com/archeious/luminos.git
cd luminos
python3 luminos.py <target>
```

Works on any system with Python 3 and standard GNU coreutils (`wc`, `file`, `grep`, `head`, `tail`, `stat`, `du`, `find`).

### AI mode

AI mode needs a few pip-installable packages. The project ships a helper script that creates a dedicated virtual environment and installs them:

```bash
./setup_env.sh
source ~/luminos-env/bin/activate
```

The packages installed are `anthropic`, `tree-sitter`, a handful of tree-sitter language grammars, and `python-magic`.

You also need an Anthropic API key exported as an environment variable:

```bash
export ANTHROPIC_API_KEY=your-key-here
```

Check which optional dependencies are present:

```bash
python3 luminos.py --install-extras
```

## Usage

### Base scan

```bash
python3 luminos.py /path/to/project
```

### AI scan

```bash
python3 luminos.py --ai /path/to/project
```

### Common flags

```bash
# Deeper tree, include hidden files, exclude build and vendor dirs
python3 luminos.py -d 8 -a -x .git -x node_modules -x vendor /path/to/project

# JSON output to a file
python3 luminos.py --json -o report.json /path/to/project

# Watch mode (re-scan every 30s, show diffs)
python3 luminos.py --watch /path/to/project

# Force a fresh AI investigation, ignoring the cache
python3 luminos.py --ai --fresh /path/to/project

# Clear the AI investigation cache
python3 luminos.py --clear-cache
```

Run `python3 luminos.py --help` for the full flag list.

## How AI mode works

A short version of what happens when you pass `--ai`:

1. **Discover** every directory under the target.
2. **Sort leaves-first** so the deepest directories are investigated before their parents.
3. **Run an isolated agent loop per directory** with a max of 10 turns each. The agent has a small toolbelt: read files, run whitelisted coreutils commands (`wc`, `file`, `grep`, `head`, `tail`, `stat`, `du`, `find`), and write cache entries.
4. **Cache everything.** Each file and directory summary is written to `/tmp/luminos/` so that subsequent runs on the same target don't burn tokens re-deriving things that haven't changed.
5. **Context budget guard.** Per-turn `input_tokens` is watched against a budget (currently 70% of the model's context window) so a rogue directory can't blow the context and silently degrade quality.
6. **Final synthesis pass** reads only the directory-level cache entries (not the raw files) to produce a project-level summary and the severity-ranked flags.

## Development

Run the test suite:

```bash
python3 -m unittest discover -s tests/
```

Modules that are intentionally not unit tested and why:

- `luminos_lib/ai.py`: requires a live Anthropic API, tested in practice
- `luminos_lib/ast_parser.py`: requires tree-sitter grammars installed
- `luminos_lib/watch.py`: stateful event loop, tested manually
- `luminos_lib/prompts.py`: string templates only

## License

Apache License 2.0. See [`LICENSE`](LICENSE) for the full text.

## Source of truth

The canonical home for this project is the [Forgejo repository](https://forgejo.labbity.unbiasedgeek.com/archeious/luminos). The GitHub copy is a read-only mirror, pushed automatically from Forgejo. Issues, pull requests, and the project wiki live on Forgejo.
