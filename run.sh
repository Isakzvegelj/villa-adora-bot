#!/bin/bash
set -e
cd "$(dirname "$0")"

export LLM_BASE_URL="${LLM_BASE_URL:-https://openrouter.ai/api/v1}"
export LLM_MODEL="${LLM_MODEL:-google/gemini-2.0-flash-exp:free}"

if [ -z "${OPENAI_API_KEY:-${LLM_API_KEY:-}}" ]; then
  echo "Set OPENAI_API_KEY or LLM_API_KEY first" >&2
  exit 1
fi

export OPENAI_API_KEY="${OPENAI_API_KEY:-${LLM_API_KEY}}"
chmod -f +x run.sh 2>/dev/null || true
.venv/bin/python app.py &
FLASK_PID=$!
sleep 2
cloudflared tunnel --url http://localhost:5003
