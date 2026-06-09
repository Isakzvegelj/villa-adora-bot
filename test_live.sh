#!/bin/bash
BASE="https://villa-adora-bot-r00l.onrender.com/api/chat"
PASS=0
FAIL=0

ask() {
    local name="$1"
    local msg="$2"
    
    echo -n "[$name] "
    RESP=$(curl -s -X POST "$BASE" -H 'Content-Type: application/json' --data-binary "{\"message\": \"$msg\"}" --max-time 90 2>&1)
    
    if [ $? -ne 0 ] || [ -z "$RESP" ]; then
        echo "ERROR: No response"
        FAIL=$((FAIL+1))
        return
    fi
    
    # Save response to temp file for python parsing
    echo "$RESP" > /tmp/bot_resp.json
    CONTENT=$(python3 -c "import sys,json; d=json.load(open('/tmp/bot_resp.json')); print(d['replies'][0]['content'])" 2>&1)
    
    if [ $? -ne 0 ]; then
        echo "ERROR: Parse failed - $CONTENT"
        FAIL=$((FAIL+1))
        return
    fi
    
    LEN=${#CONTENT}
    ISSUES=""
    
    # Check ends with question
    if ! echo "$CONTENT" | grep -qE '\?$'; then
        ISSUES="${ISSUES}no_question "
    fi
    
    # Check tech leaks
    if echo "$CONTENT" | grep -qiE '(database|sql|flask|python|api|endpoint|json|server|function|code)'; then
        ISSUES="${ISSUES}tech_leak "
    fi
    
    # Check too short
    if [ "$LEN" -lt 50 ]; then
        ISSUES="${ISSUES}too_short "
    fi
    
    # Check cut off
    if echo "$CONTENT" | grep -qE '\.\.\.$'; then
        ISSUES="${ISSUES}cut_off "
    fi
    
    if [ -z "$ISSUES" ]; then
        echo "OK (len=$LEN)"
        PASS=$((PASS+1))
    else
        echo "FAIL: $ISSUES (len=$LEN)"
        FAIL=$((FAIL+1))
    fi
    
    echo "  -> ${CONTENT:0:120}"
    echo ""
    sleep 1
}

echo "=== BASIC INFO TESTS ==="
ask "rooms" "What rooms do you have available?"
ask "checkin" "What are your check-in and check-out times?"
ask "parking" "Do you have parking?"
ask "pets" "Can I bring my dog?"
ask "breakfast" "Do you serve breakfast?"
ask "restaurant" "Tell me about your restaurant"
ask "wine" "Do you have local wine?"
ask "bar" "Do you have a bar?"
ask "location" "Where are you located?"
ask "activities" "What activities are nearby?"
ask "booking" "How do I make a booking?"
ask "late_checkin" "Can I check in late at night?"
ask "late_checkout" "Can I check out late?"
ask "vegan" "Do you have vegan options?"
ask "gluten_free" "Is there gluten-free food?"

echo ""
echo "=== MULTILINGUAL TESTS ==="
ask "slovenian" "Kakšne so vaše sobe?"
ask "german" "Welche Zimmer haben Sie?"
ask "italian" "Quali camere avete?"
ask "french" "Quelles chambres avez-vous?"
ask "spanish" "Which rooms do you have?"

echo ""
echo "=== SUMMARY ==="
echo "Passed: $PASS"
echo "Failed: $FAIL"
