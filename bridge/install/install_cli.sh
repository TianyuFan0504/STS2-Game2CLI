#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TARGET_BIN="${1:-/opt/homebrew/bin/sts2}"

if [[ ! -f "$PROJECT_ROOT/sts2" ]]; then
  echo "sts2 launcher not found at $PROJECT_ROOT/sts2" >&2
  exit 1
fi

mkdir -p "$(dirname "$TARGET_BIN")"
chmod +x "$PROJECT_ROOT/sts2"
ln -sf "$PROJECT_ROOT/sts2" "$TARGET_BIN"

echo "Installed CLI launcher:"
echo "  $TARGET_BIN -> $PROJECT_ROOT/sts2"
