#!/bin/bash
set -e
cd "$(dirname "$0")"

OPENAI_API_KEY="$(security find-generic-password -a isakzvegelj -s openrouter-api-key -w)"
export OPENAI_API_KEY
export LLM_BASE_URL="${LLM_BASE_URL:-https://openrouter.ai/api/v1}"
export LLM_MODEL="${LLM_MODEL:-openai/gpt-oss-120b:free}"

if [ -z "$OPENAI_API_KEY" ]; then
  echo "OpenRouter API key not found in Keychain. Store it first:" >&2
  echo '  security add-generic-password -a isakzvegelj -s openrouter-api-key -w "YOUR_KEY"' >&2
  exit 1
fi

chmod +x run.sh 2>/dev/null || true
.venv/bin/python app.py &
FLASK_PID=$!
sleep 2
cloudflared tunnel --url http://localhost:5173
