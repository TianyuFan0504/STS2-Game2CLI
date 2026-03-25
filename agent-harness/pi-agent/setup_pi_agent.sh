#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_ROOT="$ROOT/agent-harness/pi-agent/runtime"

if ! command -v npm >/dev/null 2>&1; then
  echo "[setup] npm not found in PATH." >&2
  exit 1
fi

if [[ ! -f "$RUNTIME_ROOT/package.json" ]]; then
  echo "[setup] runtime package.json not found at $RUNTIME_ROOT/package.json" >&2
  exit 1
fi

cd "$RUNTIME_ROOT"
npm install
