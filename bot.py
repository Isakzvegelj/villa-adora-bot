import ollama
import json
import os
from database import add_booking, init_db
from hotel_data import hotel_info

init_db()

# ============ Function Schemas ============

book_room_function = {
    "type": "function",
    "function": {
        "name": "book_room",
        "description": "Book a hotel room.",
        "parameters": {
            "type": "object",
            "properties": {
                "guest_name": {"type": "string"},
                "check_in": {"type": "string", "description": "YYYY-MM-DD"},
                "check_out": {"type": "string", "description": "YYYY-MM-DD"},
                "room_name": {"type": "string"}
            },
            "required": ["guest_name", "check_in", "check_out", "room_name"],
        },
    },
}

query_hotel_info_function = {
    "type": "function",
    "function": {
        "name": "query_hotel_info",
        "description": "Look up hotel information.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "enum": [
                        "rooms",
                        "policies",
                        "amenities",
                        "location",
                        "experiences",
                        "breakfast",
                        "parking",
                        "wifi",
                        "pets",
                        "cancellation",
                        "general",
                    ],
                },
                "question": {"type": "string"},
            },
            "required": ["topic", "question"],
        },
    },
}

# ============ Minimal System Prompt ============

def build_system_prompt():
    h = hotel_info
    rooms = "\n".join([f"• {r['name']}: {r['price']} EUR" for r in h['rooms'].values()])
    p = h['policies']
    return f"""Luka @ {h['name']}. LOC: {h['location']['address']} | {h['location']['phone']}.

CHECK-IN: {p['check_in']} | CHECK-OUT: {p['check_out']}
BREAKFAST: {p['breakfast']} | PARKING: {p['parking']} | WiFi: {p['wifi']} | Pets: {p['pets']}

ROOMS:
{rooms}

RULES: Only use facts above. Unknown → "I'll check with manager."
Booking: ask name, check-in, check-out, room (one at a time). Restate, ask "Confirm? yes/no". Call book_room() only on 'yes'. Keep replies short."""

system_prompt = build_system_prompt()

def get_hotel_info_response(topic, question):
    h = hotel_info
    q = question.lower()
    
    if topic == "rooms" or "room" in q or "suite" in q:
        for room in h['rooms'].values():
            if any(word in q for word in room['name'].lower().split()):
                return f"{room['name']}: {room['price']} EUR/night. {room['description']}"
        return "\n".join([f"• {r['name']}: {r['price']} EUR" for r in h['rooms'].values()])
    elif topic == "policies":
        return f"Check-in: {h['policies']['check_in']}. Check-out: {h['policies']['check_out']}"
    elif topic in ["breakfast","parking","wifi","pets","cancellation"]:
        return h['policies'][topic]
    elif topic == "location":
        return f"{h['name']}, {h['location']['address']}. Tel: {h['location']['phone']}"
    else:
        return h['location']['description']

# ============ Chat Loop ============

def chat():
    messages = [{"role": "system", "content": system_prompt}]
    pending = None
    
    print(f"\n🏔️  {hotel_info['name']} — Luka\n")
    
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in ['exit','quit','bye']:
            print(f"Luka: Thank you. 👋\n")
            break
        
        # Confirmation handling (skip Ollama)
        if pending:
            if user_input.lower() in ['yes','y','confirm']:
                add_booking(pending['guest_name'], pending['room_name'], pending['check_in'], pending['check_out'])
                print(f"Luka: ✅ Confirmed! See you soon.\n")
                pending = None
                continue
            elif user_input.lower() in ['no','n','cancel']:
                print("Luka: Canceled.\n")
                pending = None
                continue
            else:
                print("Luka: Reply 'yes' or 'no'.\n")
                continue
        
        messages.append({"role": "user", "content": user_input})
        
        try:
            options = {"num_predict": 100}
            if "llama3.1" in os.environ.get("OLLAMA_MODEL", ""):
                options["num_ctx"] = 4096
            response = ollama.chat(
                model='llama3.2:3b',  # Fast
                messages=messages,
                tools=[book_room_function, query_hotel_info_function],
                options=options,
            )
            
            msg = response['message']
            messages.append(msg)
            
            if 'tool_calls' in msg:
                for tc in msg['tool_calls']:
                    fn = tc['function']['name']
                    raw_args = tc['function']['arguments']
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    
                    if fn == 'book_room':
                        pending = args
                        print(f"Luka: Confirm: {args['guest_name']} | {args['check_in']} → {args['check_out']} | {args['room_name']}? (yes/no)")
                    elif fn == 'query_hotel_info':
                        ans = get_hotel_info_response(args['topic'], args['question'])
                        print(f"Luka: {ans}")
                        messages.append({"role": "tool", "content": ans})
            else:
                print(f"Luka: {msg['content']}\n")
                
        except Exception as e:
            print(f"Luka: Error {e}\n")

if __name__ == "__main__":
    chat()
