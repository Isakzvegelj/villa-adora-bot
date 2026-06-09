#!/bin/bash
BASE="https://villa-adora-bot-r00l.onrender.com/api/chat"

get_resp() {
    local msg="$1"
    curl -s -X POST "$BASE" -H 'Content-Type: application/json' --data-binary "{\"message\": \"$msg\"}" --max-time 90 > /tmp/bot_resp.json 2>&1
    python3 -c "import sys,json; d=json.load(open('/tmp/bot_resp.json')); print(d['replies'][0]['content'])" 2>&1
    echo "---END---"
    sleep 1
}

echo "=== late_checkout ==="
get_resp "Can I check out late?"

echo "=== slovenian ==="
get_resp "Kakšne so vaše sobe?"

echo "=== italian ==="
get_resp "Quali camere avete?"

echo "=== french ==="
get_resp "Quelles chambres avez-vous?"

echo "=== spanish ==="
get_resp "Which rooms do you have?"
