#!/usr/bin/env bash
set -euo pipefail

VENV_DIR="$HOME/luminos-env"

if [ -d "$VENV_DIR" ]; then
    echo "venv already exists at $VENV_DIR"
else
    echo "Creating venv at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

echo "Activating venv..."
source "$VENV_DIR/bin/activate"

echo "Installing packages..."
pip install anthropic tree-sitter tree-sitter-python \
            tree-sitter-javascript tree-sitter-rust \
            tree-sitter-go python-magic

echo ""
echo "Done. To activate the venv in future sessions:"
echo ""
echo "  source ~/luminos-env/bin/activate"
echo ""
echo "Then run luminos as usual:"
echo ""
echo "  python3 luminos.py --ai <target>"
echo ""
