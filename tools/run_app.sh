#!/bin/bash
# Run the desktop app using only this project's virtual environment and key.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY_FILE="$ROOT/cache/elevenlabs_api_key"
if [[ -f "$KEY_FILE" ]]; then
    IFS= read -r ELEVENLABS_API_KEY < "$KEY_FILE" || true
    export ELEVENLABS_API_KEY
fi
exec "$ROOT/.venv/bin/python" "$ROOT/main.py"
