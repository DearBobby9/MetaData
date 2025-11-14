#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
REQ_FILE="$ROOT_DIR/requirements.txt"

echo "[run.sh] Working directory: $ROOT_DIR"

if [ ! -d "$VENV_DIR" ]; then
  echo "[run.sh] Creating virtual environment at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

if [ -f "$REQ_FILE" ]; then
  echo "[run.sh] Installing dependencies from $REQ_FILE"
  pip install -r "$REQ_FILE"
else
  echo "[run.sh] ERROR: requirements.txt not found" >&2
  exit 1
fi

if [ ! -f "$ROOT_DIR/.env" ] && [ -f "$ROOT_DIR/config.example.env" ]; then
  cp "$ROOT_DIR/config.example.env" "$ROOT_DIR/.env"
  echo "[run.sh] Created .env from config.example.env (remember to edit CROSSREF_MAILTO)"
fi

echo "[run.sh] Launching FastAPI server at http://127.0.0.1:8000"
exec python "$ROOT_DIR/main.py" serve
