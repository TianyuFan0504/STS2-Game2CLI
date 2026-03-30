#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STS2_REPO_BIN="$ROOT/sts2"
PI_RUNTIME_ROOT="$ROOT/agent-harness/pi-agent/runtime"
PI_SETUP_SCRIPT="$ROOT/agent-harness/pi-agent/setup_pi_agent.sh"
BASE_PROMPT_FILE="$ROOT/agent-harness/pi-agent/base-prompt.md"
SKILL_PATH="$ROOT/agent-harness/skills"
APPEND_PROMPT_FILE="$ROOT/agent-harness/pi-agent/append-system-prompt.md"
EVENT_PARSER="$ROOT/agent-harness/pi-agent/stream_pi_events.py"
ENV_FILE="${STS2CLI_ENV_FILE:-$ROOT/.env}"
LOG_ROOT="$ROOT/logs/pi-agent"
SESSION_ID="$(date +%Y%m%d-%H%M%S)"
SESSION_DIR="$LOG_ROOT/$SESSION_ID"
ITERATIONS_DIR="$SESSION_DIR/iterations"
MESSAGE_FILE="$SESSION_DIR/runtime_prompt.md"
RUNNER_LOG="$SESSION_DIR/runner.log"

mkdir -p "$ITERATIONS_DIR"
ln -sfn "$SESSION_DIR" "$LOG_ROOT/latest"

export PATH="$ROOT:/opt/homebrew/bin:${PATH}"
export STS2CLI_ROOT="$ROOT"
export STS2CLI_SESSION_DIR="$SESSION_DIR"
export PI_CODING_AGENT_DIR="${PI_CODING_AGENT_DIR:-$ROOT/.agents/pi-home}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

mkdir -p "$PI_CODING_AGENT_DIR"

PI_PACKAGE_NAME="${PI_PACKAGE_NAME:-@mariozechner/pi-coding-agent}"
PI_PACKAGE_VERSION="${PI_PACKAGE_VERSION:-0.62.0}"
PI_BIN_DEFAULT="$PI_RUNTIME_ROOT/node_modules/.bin/pi"
PI_BIN_VALUE="${PI_BIN:-$PI_BIN_DEFAULT}"

derive_api_key_env() {
  case "${1:-}" in
    openrouter) echo "OPENROUTER_API_KEY" ;;
    openai) echo "OPENAI_API_KEY" ;;
    anthropic) echo "ANTHROPIC_API_KEY" ;;
    google) echo "GEMINI_API_KEY" ;;
    groq) echo "GROQ_API_KEY" ;;
    cerebras) echo "CEREBRAS_API_KEY" ;;
    xai) echo "XAI_API_KEY" ;;
    mistral) echo "MISTRAL_API_KEY" ;;
    zai) echo "ZAI_API_KEY" ;;
    huggingface) echo "HF_TOKEN" ;;
    kimi-coding) echo "KIMI_API_KEY" ;;
    minimax) echo "MINIMAX_API_KEY" ;;
    minimax-cn) echo "MINIMAX_CN_API_KEY" ;;
    vercel-ai-gateway) echo "AI_GATEWAY_API_KEY" ;;
    *) echo "" ;;
  esac
}

has_flag() {
  local flag="$1"
  shift
  for arg in "$@"; do
    if [[ "$arg" == "$flag" ]]; then
      return 0
    fi
  done
  return 1
}

PI_PROVIDER_DEFAULT="${PI_PROVIDER:-openrouter}"
PI_MODEL_DEFAULT="${PI_MODEL:-auto}"
PI_BASE_URL_VALUE="${PI_BASE_URL:-}"
PI_API_KEY_ENV_VALUE="${PI_API_KEY_ENV:-$(derive_api_key_env "$PI_PROVIDER_DEFAULT")}"
MODELS_JSON_PATH="$PI_CODING_AGENT_DIR/models.json"

resolve_sts2_bin() {
  local candidate="${STS2_BIN:-}"
  if [[ -n "$candidate" ]]; then
    if [[ "$candidate" == */* ]]; then
      if [[ -x "$candidate" ]]; then
        printf '%s\n' "$candidate"
        return 0
      fi
    else
      local resolved
      resolved="$(command -v "$candidate" || true)"
      if [[ -n "$resolved" ]]; then
        printf '%s\n' "$resolved"
        return 0
      fi
    fi
  fi

  if [[ -x "$STS2_REPO_BIN" ]]; then
    printf '%s\n' "$STS2_REPO_BIN"
    return 0
  fi

  command -v sts2 || true
}

STS2_BIN="$(resolve_sts2_bin)"

if [[ "$PI_BIN_VALUE" == */* ]]; then
  PI_BIN_RESOLVED="$PI_BIN_VALUE"
else
  PI_BIN_RESOLVED="$(command -v "$PI_BIN_VALUE" || true)"
fi

if [[ -z "$PI_BIN_RESOLVED" || ! -x "$PI_BIN_RESOLVED" ]]; then
  echo "[runner] pi runtime is not installed." >&2
  echo "[runner] expected package: $PI_PACKAGE_NAME@$PI_PACKAGE_VERSION" >&2
  echo "[runner] run: bash $PI_SETUP_SCRIPT" >&2
  exit 1
fi

if [[ ! -d "$SKILL_PATH" ]]; then
  echo "[runner] pi skills directory not found at $SKILL_PATH" >&2
  exit 1
fi

if [[ -z "$(find "$SKILL_PATH" -mindepth 2 -maxdepth 2 -name SKILL.md -print -quit)" ]]; then
  echo "[runner] no skills found under $SKILL_PATH" >&2
  exit 1
fi

if [[ ! -f "$APPEND_PROMPT_FILE" ]]; then
  echo "[runner] append-system-prompt file not found at $APPEND_PROMPT_FILE" >&2
  exit 1
fi

if [[ ! -f "$BASE_PROMPT_FILE" ]]; then
  echo "[runner] base prompt file not found at $BASE_PROMPT_FILE" >&2
  exit 1
fi

if [[ ! -f "$EVENT_PARSER" ]]; then
  echo "[runner] event parser not found at $EVENT_PARSER" >&2
  exit 1
fi

if [[ -z "$STS2_BIN" ]]; then
  echo "[runner] sts2 command not found. Checked STS2_BIN, repo-local $STS2_REPO_BIN, and PATH." >&2
  exit 1
fi

if [[ -n "$PI_BASE_URL_VALUE" ]]; then
  if [[ -z "$PI_API_KEY_ENV_VALUE" ]]; then
    echo "[runner] PI_API_KEY_ENV is required when PI_BASE_URL is set." >&2
    exit 1
  fi

  cat >"$MODELS_JSON_PATH" <<EOF
{
  "providers": {
    "$PI_PROVIDER_DEFAULT": {
      "baseUrl": "$PI_BASE_URL_VALUE",
      "apiKey": "$PI_API_KEY_ENV_VALUE"
    }
  }
}
EOF
fi

if ! "$STS2_BIN" state >/dev/null 2>&1; then
  echo "[runner] sts2 bridge is not ready. Open the game, load the bridge plugin, and make sure 'sts2 state' works." >&2
  exit 1
fi

{
  cat "$BASE_PROMPT_FILE"
  cat <<EOF

- During each invocation, make forward progress until you reach a stable pause point after resolving obvious follow-up actions.
EOF
} >"$MESSAGE_FILE"

{
  echo "[runner] root: $ROOT"
  echo "[runner] pi_runtime_root: $PI_RUNTIME_ROOT"
  echo "[runner] pi_package: $PI_PACKAGE_NAME@$PI_PACKAGE_VERSION"
  echo "[runner] pi_bin: $PI_BIN_RESOLVED"
  echo "[runner] event_parser: $EVENT_PARSER"
  echo "[runner] env_file: $ENV_FILE"
  echo "[runner] pi_agent_dir: $PI_CODING_AGENT_DIR"
  echo "[runner] skill_path: $SKILL_PATH"
  echo "[runner] sts2_bin: $STS2_BIN"
  echo "[runner] provider_default: $PI_PROVIDER_DEFAULT"
  echo "[runner] model_default: $PI_MODEL_DEFAULT"
  if [[ -n "$PI_BASE_URL_VALUE" ]]; then
    echo "[runner] models_json: $MODELS_JSON_PATH"
    echo "[runner] provider_override_base_url: $PI_BASE_URL_VALUE"
    echo "[runner] provider_override_api_key_env: $PI_API_KEY_ENV_VALUE"
  fi
  echo "[runner] session: $SESSION_DIR"
  echo "[runner] started_at: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "[runner] stop with Ctrl+C"
} | tee -a "$RUNNER_LOG"

cleanup() {
  echo "[runner] stopped_at: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$RUNNER_LOG"
}
trap cleanup EXIT

iteration=1
consecutive_failures=0

while true; do
  iter_name="$(printf '%04d' "$iteration")"
  iter_dir="$ITERATIONS_DIR/$iter_name"
  iter_raw="$iter_dir/pi.raw.jsonl"
  iter_log="$iter_dir/pi.log"

  mkdir -p "$iter_dir"

  {
    echo
    echo "[runner] iteration $iter_name at $(date '+%Y-%m-%d %H:%M:%S')"
  } | tee -a "$RUNNER_LOG"

  provider_args=()
  if ! has_flag "--provider" "$@"; then
    provider_args+=(--provider "$PI_PROVIDER_DEFAULT")
  fi
  if ! has_flag "--model" "$@"; then
    model_args=(--model "$PI_MODEL_DEFAULT")
  else
    model_args=()
  fi

  set +e
  cd "$ROOT"
  "$PI_BIN_RESOLVED" \
    --print \
    --mode json \
    --no-session \
    --no-extensions \
    --no-prompt-templates \
    --no-themes \
    --no-skills \
    --skill "$SKILL_PATH" \
    --append-system-prompt "$APPEND_PROMPT_FILE" \
    --tools read,bash,grep,find,ls \
    "${provider_args[@]}" \
    "${model_args[@]}" \
    "$@" \
    "$(cat "$MESSAGE_FILE")" \
    2>&1 | tee "$iter_raw" | python3 "$EVENT_PARSER" | tee "$iter_log" | tee -a "$RUNNER_LOG"
  cmd_status=${PIPESTATUS[0]}
  set -e

  if [[ "$cmd_status" -ne 0 ]]; then
    consecutive_failures=$((consecutive_failures + 1))
    echo "[runner] pi invocation failed with exit code $cmd_status (consecutive failures: $consecutive_failures)." | tee -a "$RUNNER_LOG"
    if [[ "$consecutive_failures" -ge 5 ]]; then
      echo "[runner] stopping after 5 consecutive failures." | tee -a "$RUNNER_LOG"
      exit 1
    fi
    sleep 5
  else
    consecutive_failures=0
    sleep 1
  fi

  iteration=$((iteration + 1))
done
