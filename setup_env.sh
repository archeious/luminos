#!/usr/bin/env bash
set -euo pipefail

VENV_DIR="$HOME/luminos-env"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -d "$VENV_DIR" ]; then
    echo "venv already exists at $VENV_DIR"
else
    echo "Creating venv at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

echo "Activating venv..."
source "$VENV_DIR/bin/activate"

echo "Installing packages from requirements.txt..."
pip install -r "$SCRIPT_DIR/requirements.txt"

echo ""
echo "Done. To activate the venv in future sessions:"
echo ""
echo "  source ~/luminos-env/bin/activate"
echo ""
echo "Set your Anthropic API key:"
echo ""
echo "  export ANTHROPIC_API_KEY=your-key-here"
echo ""
echo "Then run luminos:"
echo ""
echo "  python3 luminos.py <target>"
echo ""
