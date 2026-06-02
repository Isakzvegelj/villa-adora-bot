
    python
    from openai import OpenAI
    import json
    import os
    from database import add_booking, init_db
    from hotel_data import hotel_info
    import sqlite3
    from flask import Flask, render_template, request, jsonify
    
    init_db()
    
    client = OpenAI(
        api_key=os.environ.get("LLM_API_KEY", ""),
        base_url=os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
    )
    MODEL = os.environ.get("LLM_MODEL", "meta-llama/llama-4-maverick:free")
    
    book_room_function = {
        "name": "book_room",
        "parameters": {
            "type": "object",
            "properties": {
                "guest_name": {"type": "string"},
                "check_in": {"type": "string", "description": "YYYY-MM-DD"},
                "check_out": {"type": "string", "description": "YYYY-MM-DD"},
                "room_name": {"type": "string"}
            },
            "required": ["guest_name", "check_in", "check_out", "room_name"]
        }
    }
    
    query_hotel_info_function = {
        "name": "query_hotel_info",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "enum": ["rooms","policies","amenities","location","experiences","breakfast","parking","wifi","pets","cancellation","general"]},
                "question": {"type": "string"}
            },
            "required": ["topic", "question"]
        }
    }
    
    def build_system_prompt():
        h = hotel_info
        rooms = "\n".join([f"• {r['name']}: {r['price']} EUR" for r in h['rooms'].values()])
        p = h['policies']
        return f"""Luka @ {h['name']}. {h['tagline']}
    
    DATA:
    Addr: {h['location']['address']} | Tel: {h['location']['phone']}
    Check-in: {p['check_in']} | Check-out: {p['check_out']}
    Breakfast: {p['breakfast']}
    Parking: {p['parking']} | WiFi: {p['wifi']} | Pets: {p['pets']}
    
    ROOMS:
    {rooms}
    
    RULES:
    - Only use facts above. Never invent.
    - Unknown → "Let me check with the manager."
    - Booking: ask name, check-in date, check-out date, room (one by one).
    - Restate, ask "Confirm? yes/no". Call book_room() only on 'yes'.
    - Keep replies <50 words."""
    
    system_prompt = build_system_prompt()
    
    def get_hotel_info_response(topic, question):
        h = hotel_info
        q = question.lower()
        if topic == "rooms" or "room" in q or "suite" in q:
            for room in h['rooms'].values():
                if any(word in q for word in room['name'].lower().split()):
                    return f"{room['name']} — {room['price']} EUR/night. {room['description']}"
            return "\n".join([f"• {r['name']}: {r['price']} EUR/night" for r in h['rooms'].values()])
        elif topic == "policies":
            return f"Check-in: {h['policies']['check_in']}. Check-out: {h['policies']['check_out']}"
        elif topic in ["breakfast","parking","wifi","pets","cancellation","location"]:
            return h['policies'].get(topic, h['location'].get('description', ''))
        elif topic == "location":
            return f"{h['name']}, {h['location']['address']}. Phone: {h['location']['phone']}"
        elif topic == "experiences":
            return "Popular: " + ", ".join(h['experiences'][:5])
        else:
            return h['location']['description']
    
    app = Flask(name)
    sessions = {}
    
    @app.route('/')
    def index():
        return render_template('index.html', hotel=hotel_info, hotel_name=hotel_info['name'])
    
    @app.route('/api/chat', methods=['POST'])
    def api_chat():
        data = request.json
        session_id = data.get('session_id', 'default')
        user_message = data.get('message', '')
        if session_id not in sessions:
            sessions[session_id] = [{"role": "system", "content": system_prompt}]
        messages = sessions[session_id]
        messages.append({"role": "user", "content": user_message})
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=[book_room_function, query_hotel_info_function],
                temperature=0.5,
                max_tokens=200,
            )
            msg = response.choices[0].message
            content = msg.content or ""
            tool_calls = getattr(msg, "tool_calls", None) or []
            assistant_msg = {"role": "assistant", "content": content}
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {"function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in tool_calls
                ]
            messages.append(assistant_msg)
            replies = []
            for tc in tool_calls:
                fn = tc.function.name
                raw_args = tc.function.arguments
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                if fn == 'book_room':
                    room_key = args['room_name'].lower().replace(' ','_')
                    price = hotel_info['rooms'].get(room_key, {}).get('price','')
                    price_str = f" ({price} EUR/night)" if price else ""
                    replies.append({
                        'type': 'confirmation_request',
                        'content': f"Booking Confirmation\n\n• Guest: {args['guest_name']}\n• Check-in: {args['check_in']}\n• Check-out: {args['check_out']}\n• Room: {args['room_name']}{price_str}\n\nReply yes to confirm or no to cancel."
                    })
                    sessions[session_id] = messages + [{"role": "system", "content": f"BOOKING_PENDING: {json.dumps(args)}"}]
                elif fn == 'query_hotel_info':
                    answer = get_hotel_info_response(args['topic'], args['question'])
                    replies.append({'type': 'text', 'content': answer})
                    messages.append({"role": "tool", "content": answer})
            if not replies:
                replies.append({'type': 'text', 'content': content})
            return jsonify({'replies': replies})
        except Exception as e:
            return jsonify({'replies': [{'type': 'text', 'content': f"Error: {str(e)}"}]}), 500
    
    @app.route('/api/confirm', methods=['POST'])
    def api_confirm():
        data = request.json
        session_id = data.get('session_id', 'default')
        confirmed = data.get('confirmed', False)
        messages = sessions.get(session_id, [])
        for i in range(len(messages)-1, -1, -1):
            if messages[i].get('role') == 'system' and 'BOOKING_PENDING' in messages[i].get('content',''):
                pending = json.loads(messages[i]['content'].split(':',1)[1].strip())
                if confirmed:
                    add_booking(pending['guest_name'], pending['room_name'], pending['check_in'], pending['check_out'])
                    response = f"✅ Confirmed for {pending['guest_name']}! Welcome to {hotel_info['name']}."
                else:
                    response = "❌ Canceled."
                messages.pop(i)
                sessions[session_id] = messages
                return jsonify({'reply': {'type':'text','content': response}})
        return jsonify({'reply': {'type':'text','content': "No pending booking."}})
    
    @app.route('/api/bookings', methods=['GET'])
    def api_bookings():
        conn = sqlite3.connect('hotel.db')
        c = conn.cursor()
        c.execute("SELECT * FROM bookings ORDER BY id DESC")
        rows = c.fetchall()
        conn.close()
        return jsonify({'bookings': [{"id":r[0],"guest":r[1],"room":r[2],"check_in":r[3],"check_out":r[4]} for r in rows]})
    
    @app.route('/admin')
    def admin():
        return render_template('admin.html', hotel_name=hotel_info['name'])
    
    if name == 'main':
        print(f"🏔️  {hotel_info['name']} — Fast Mode")
        print("📍 http://localhost:5003 | 📊 /admin")
        app.run(host='0.0.0.0', port=5003, debug=True, threaded=True)
    
