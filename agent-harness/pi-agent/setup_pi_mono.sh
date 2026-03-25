#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
echo "[setup] setup_pi_mono.sh is deprecated; installing the pinned pi runtime instead."
exec bash "$ROOT/agent-harness/pi-agent/setup_pi_agent.sh" "$@"
