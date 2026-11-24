#!/bin/sh
# One status pull. Usage: ./run.sh [--no-push] [--no-pull] [--set KEY=VALUE ...]
# Reads UV from config.local.env and runs run.py in the locked env of this folder.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
LOCAL="$HERE/config.local.env"
if [ ! -f "$LOCAL" ]; then
  echo "missing $LOCAL (copy config.local.env.example and fill it in)" >&2
  exit 2
fi
UV=$(sed -n 's/^UV=//p' "$LOCAL" | tail -n 1)
[ -n "$UV" ] || UV=uv
cd "$HERE"
exec "$UV" run --locked --quiet python run.py "$@"
