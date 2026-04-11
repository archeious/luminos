# Luminos

A file system intelligence tool. Point it at a directory and it runs an agentic Claude investigation that figures out what the directory is, what's in it, and what might be worth your attention.

Luminos is built around a harder question than "what files are here?" It is built around "what is this, and should I be worried about any of it?" To answer that, it runs a multi-pass agentic investigation against the [Claude API](https://www.anthropic.com/api): a survey pass to orient on the target, an isolated dir-loop agent per directory with a small toolbelt (read files, run whitelisted coreutils commands, write cache entries), and a final synthesis pass that produces a project-level verdict with severity-ranked flags.

A lightweight base scan runs first to feed the agent its initial picture of the target. The base scan is not a standalone product, it is the first step of the investigation.

## Features

- **Agentic AI investigation.** Multi-pass, leaves-first analysis via Claude. Survey then dir loops then synthesis.
- **Investigation cache.** Per-file and per-directory summaries are cached under `/tmp/luminos/` so repeat runs on the same target are cheap.
- **Severity-ranked flags.** Findings are sorted so `critical` items are the first thing you see.
- **Context budget guard.** Per-turn `input_tokens` is watched against a budget so a rogue directory can't blow the context and silently degrade quality.
- **Graceful degradation.** Permission denied, subprocess timeouts, missing API key: all handled without crashing.
- **JSON output.** Pipe reports to other tools or save for comparison.

## Installation

Luminos is a normal Python project. Clone, create a venv, and install from `requirements.txt`. The repository ships a helper script that does this for you:

```bash
git clone https://github.com/archeious/luminos.git
cd luminos
./setup_env.sh
source ~/luminos-env/bin/activate
```

Or do it by hand:

```bash
python3 -m venv ~/luminos-env
source ~/luminos-env/bin/activate
pip install -r requirements.txt
```

You also need an Anthropic API key exported as an environment variable:

```bash
export ANTHROPIC_API_KEY=your-key-here
```

The base scan shells out to a handful of GNU coreutils (`wc`, `file`, `grep`, `head`, `tail`, `stat`, `du`, `find`), so you also need those on `$PATH`. They are installed by default on every mainstream Linux distribution and on macOS via Homebrew.

## Usage

```bash
python3 luminos.py /path/to/project
```

That is the whole interface. The investigation runs end to end and prints a report.

### Common flags

```bash
# Deeper tree, include hidden files, exclude build and vendor dirs
python3 luminos.py -d 8 -a -x .git -x node_modules -x vendor /path/to/project

# JSON output to a file
python3 luminos.py --json -o report.json /path/to/project

# Force a fresh investigation, ignoring the cache
python3 luminos.py --fresh /path/to/project

# Clear the investigation cache
python3 luminos.py --clear-cache
```

Run `python3 luminos.py --help` for the full flag list.

## How the investigation works

A short version of what happens on every run:

1. **Base scan.** Builds the directory tree, classifies files into seven categories, counts lines of code, finds large and recently modified files, computes per-directory disk usage. This is the agent's initial picture of the target.
2. **Survey pass.** A short agent loop (max 3 turns) reads the base scan, describes the target in plain language, and decides which investigation tools are relevant. Tiny targets skip the survey.
3. **Dir loops.** Every directory gets its own isolated agent loop, leaves-first, with up to 14 turns. The agent has read-only access to the filesystem and a toolbelt of `read_file`, `list_directory`, `run_command`, `parse_structure`, `write_cache`, `think`, `checkpoint`, `flag`, and `submit_report`.
4. **Cache.** Each file and directory summary is written to `/tmp/luminos/` so subsequent runs on the same target don't re-derive what hasn't changed.
5. **Context budget guard.** Per-turn `input_tokens` is watched against a budget (currently 70% of the model's context window) so a rogue directory can't blow the context window.
6. **Final synthesis.** A short agent loop reads the directory-level cache entries (not the raw files) and produces the project-level brief, the detailed analysis, and the severity-ranked flags.

## Development

Run the test suite:

```bash
python3 -m unittest discover -s tests/
```

Modules that are intentionally not unit tested:

- `luminos_lib/ast_parser.py`: requires tree-sitter grammars installed
- `luminos_lib/prompts.py`: string templates only

`luminos_lib/ai.py` is partially covered. End-to-end agent loops require a live Anthropic API and stay exempt, but pure helpers are tested in `tests/test_ai_pure.py`.

## License

Apache License 2.0. See [`LICENSE`](LICENSE) for the full text.

## Source of truth

The canonical home for this project is the [Forgejo repository](https://forgejo.labbity.unbiasedgeek.com/archeious/luminos). The GitHub copy is a read-only mirror, pushed automatically from Forgejo. Issues, pull requests, and the project wiki live on Forgejo.
