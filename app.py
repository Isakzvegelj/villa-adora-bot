import os
import subprocess
import json
from openai import OpenAI
from database import add_booking, init_db
from hotel_data import hotel_info
import sqlite3
from flask import Flask, render_template, request, jsonify
try:
    from rag import retrieve as rag_retrieve
    _RAG_AVAILABLE = True
except ImportError:
    _RAG_AVAILABLE = False

init_db()

def _load_api_key() -> str:
    env_key = (os.environ.get("LLM_API_KEY") or "").strip()
    if env_key:
        return env_key
    for service in ("openrouter-api-key", "LLM_API_KEY"):
        try:
            value = subprocess.check_output(
                ["security", "find-generic-password", "-s", service, "-w"],
                stderr=subprocess.DEVNULL,
            ).decode("utf-8", "ignore").strip()
            if value:
                return value
        except subprocess.CalledProcessError:
            pass
    return ""

api_key = _load_api_key()
if not api_key:
    raise SystemExit(
        "No OpenRouter API key found. Set LLM_API_KEY in env, or store with: "
        "security add-generic-password -a <user> -s openrouter-api-key -w '<key>'"
    )

def make_client() -> OpenAI:
    return OpenAI(
        api_key=api_key,
        base_url=os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
    )

client = make_client()
MODEL = os.environ.get("LLM_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

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
                        "payment",
                        "children",
                        "smoking",
                        "contact",
                        "general",
                    ],
                },
                "question": {"type": "string"},
            },
            "required": ["topic", "question"],
        },
    },
}


def fix_spacing(text):
    """Fix common LLM spacing issues."""
    import re
    # Replace all unicode whitespace variants with normal space
    text = re.sub(r'[\u2000-\u200b\u202f\u205f\u00a0\u2011\u2012\u2013\u2014]', ' ', text)
    # Fix missing space between word and number: "from14:00" -> "from 14:00"
    text = re.sub(r'([a-zA-Z])(\d)', r'\1 \2', text)
    # Fix missing space between number and word: "11.What" -> "11. What"
    text = re.sub(r'(\d)([A-Z])', r'\1 \2', text)
    # Fix missing space after punctuation: "word.Word" -> "word. Word"
    text = re.sub(r'([.!?])([A-Z])', r'\1 \2', text)
    # Fix missing space after comma: "word,word" -> "word, word"
    text = re.sub(r',([a-zA-Z])', r', \1', text)
    # Fix missing space after colon: "word:word" -> "word: word"
    text = re.sub(r':([a-zA-Z])', r': \1', text)
    # Fix run-on words: lowercase followed by uppercase with no space
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    # Fix multiple spaces
    text = re.sub(r'  +', ' ', text)
    return text.strip()


def build_system_prompt() -> str:
    return (
        "You are Luka, the friendly digital concierge at Villa Adora Bled — a small luxury hotel on the shore of Lake Bled, Slovenia.\n\n"
        "PERSONALITY:\n"
        "- Warm, helpful, and professional. Like a real concierge who genuinely cares.\n"
        "- Keep responses concise (2-3 sentences max) but always friendly.\n"
        "- ALWAYS end your response with a follow-up question to keep the guest engaged. Never give a bare answer without a question.\n"
        "- Use a natural, conversational tone. Not robotic.\n\n"
        "HOTEL FACTS (use these, never invent):\n"
        "- Check-in: 14:00-21:00 | Check-out: 07:00-11:00\n"
        "- Late check-in: Available on request! Contact reception to arrange. We accommodate late arrivals with advance notice. Just tell us your expected arrival time.\n"
        "- Late check-out: Available on request, subject to availability. Additional fees may apply. Contact reception to arrange.\n"
        "- If guest asks about arriving late or checking out late, reassure them it's possible and ask for their preferred time.\n"
        "- Breakfast: €22/person, fresh pastries, bread, local products\n"
        "- Parking: Free private parking on-site\n"
        "- WiFi: Complimentary high-speed throughout\n"
        "- Pets: Allowed on request (contact for details/fees)\n"
        "- Cancellation: Varies by room type, contact for specifics\n"
        "- Payment: Visa, MasterCard accepted\n"
        "- Children welcome. Non-smoking property. Main guest 18+.\n"
        "- Address: Cesta svobode 35, 4260 Bled, Slovenia\n"
        "- Phone: +386 51 603 858\n\n"
        "ROOMS:\n"
        "- Princess Suite: €250/night, 55m², lake view from tower, queen bed\n"
        "- Luxury Suite: €270/night, lake view, elegant decor\n"
        "- Penthouse Suite: €300/night, 60m², 2 floors, king bed, breathtaking views\n"
        "- Swan Suite: €370/night, lake view, luxury furnishings\n"
        "- Island Suite: €380/night, 65m², 2 bedrooms, sleeps 4, island view\n"
        "- Prestige Suite: €420/night, 72m², ground floor, terrace, lake view\n\n"
        "EXPERIENCES NEARBY:\n"
        "- Hiking around Lake Bled, Bled Castle (5 min), row to Bled Island\n"
        "- Straza cable car (1 min walk), Vintgar Gorge (2.4 km)\n"
        "- Horse riding, fishing, mini golf\n\n"
        "BOOKING FLOW:\n"
        "- When guest wants to book, ask: name → check-in date → check-out date → room preference (one at a time)\n"
        "- After collecting all details, summarize and ask 'Would you like me to confirm this booking?'\n"
        "- Only call book_room() after guest confirms yes.\n\n"
        "RULES:\n"
        "- Answer ALL common questions DIRECTLY from the facts above. Do NOT use tools for simple queries.\n"
        "- Questions about: check-in/out times, rooms, breakfast, parking, WiFi, pets, location, experiences, policies — ANSWER DIRECTLY, do not call any tool.\n"
        "- IMPORTANT: When someone asks 'when is check in' or 'what time is check-out', answer immediately: 'Check-in is from 14:00 to 21:00. Check-out is by 07:00 to 11:00.' Do NOT ask for booking details.\n"
        "- IMPORTANT: When someone asks about rooms, answer directly with the room list from the facts above. Do NOT call a tool.\n"
        "- Only use query_hotel_info() for very specific questions that need detailed lookup.\n"
        "- Only use book_room() when the guest explicitly wants to make a booking and has confirmed.\n"
        "- Never ask for booking reference, reservation ID, or guest name unless you are in the booking flow.\n"
        "- If you don't know something, say 'Let me check with the manager on that.'\n"
        "- Always end with a follow-up question. Never give a bare answer without a question.\n"
        "- Keep responses to 2-3 sentences plus a closing question.\n"
    )


def format_rag_context(docs: list[str]) -> str:
    lines = []
    for doc in docs:
        text = doc.strip()
        if text:
            lines.append(text)
    return "\n\n".join(lines)


def maybe_retrieve_hotel_facts(query: str, max_facts: int = 2) -> list[str]:
    if not _RAG_AVAILABLE:
        return []
    try:
        return rag_retrieve(query=query, top_k=max_facts)
    except Exception:
        return []


def apply_rag_to_messages(messages: list[dict], user_query: str) -> list[dict]:
    if not user_query.strip():
        return messages
    context_docs = maybe_retrieve_hotel_facts(user_query)
    if not context_docs:
        return messages
    rag_msg = {
        "role": "system",
        "content": f"HOTEL_KNOWLEDGE_BLOCK:\n\n{format_rag_context(context_docs)}\n\nUse only the facts above when answering.",
    }
    # Insert just before the last user turn if available.
    last_user_idx = None
    for idx in range(len(messages) - 1, -1, -1):
        if messages[idx].get("role") == "user":
            last_user_idx = idx
            break
    if last_user_idx is None:
        return messages + [rag_msg]
    return messages[:last_user_idx] + [rag_msg] + messages[last_user_idx:]


def get_hotel_info_response(topic, question):
    h = hotel_info
    q = question.lower()

    # Map common synonyms to topics
    topic_aliases = {
        "check_in": ["check in", "checkin", "arrival", "arrive", "check-in", "late check in", "late arrival"],
        "check_out": ["check out", "checkout", "departure", "depart", "check-out", "late check out", "late departure"],
        "rooms": ["room", "suite", "bed", "accommodation", "stay", "sleep"],
        "policies": ["policy", "rule", "regulation"],
        "amenities": ["amenity", "facility", "feature", "service", "perk"],
        "location": ["location", "address", "where", "direction", "map", "find", "located"],
        "experiences": ["experience", "activity", "thing to do", "attraction", "sight", "visit", "tour", "hike", "swim"],
        "breakfast": ["breakfast", "food", "eat", "dining", "restaurant", "meal"],
        "parking": ["parking", "park", "car"],
        "wifi": ["wifi", "wi-fi", "internet", "wireless"],
        "pets": ["pet", "dog", "cat", "animal"],
        "cancellation": ["cancel", "refund", "cancellation"],
        "payment": ["payment", "pay", "card", "visa", "mastercard", "cash"],
        "children": ["child", "kid", "baby", "family", "toddler"],
        "smoking": ["smoke", "smoking", "cigarette"],
        "late_check_in": ["late check in", "late checkin", "late arrival", "arrive late", "after hours check in", "night check in"],
        "late_check_out": ["late check out", "late checkout", "late departure", "leave late", "after hours check out"],
        "contact": ["contact", "phone", "email", "call", "reach"],
        "general": ["general", "info", "information", "about", "tell me"],
    }

    # Detect actual topic from question if topic is generic
    actual_topic = topic
    if topic in ("general", "policies"):
        for t, aliases in topic_aliases.items():
            if any(a in q for a in aliases):
                actual_topic = t
                break

    # Check-in / Check-out
    if actual_topic in ("check_in", "check_out"):
        # Check if asking about late arrival/departure
        if any(word in q for word in ["late", "later", "after", "early", "before", "outside"]):
            if actual_topic == "check_in" or "late" in q or "arrival" in q or "arrive" in q:
                return (
                    f"Our standard check-in is {h['policies']['check_in']}, but late check-in is available on request! "
                    f"Just contact our reception to arrange. We can accommodate late arrivals with advance notice. "
                    f"What time were you planning to arrive?"
                )
            else:
                return (
                    f"Our standard check-out is {h['policies']['check_out']}, but late check-out is available on request! "
                    f"It's subject to availability and additional fees may apply. Contact reception to arrange. "
                    f"What time would you like to check out?"
                )
        return (
            f"Check-in is from {h['policies']['check_in']}, and check-out is between {h['policies']['check_out']}. "
            f"Late check-in or check-out can also be arranged on request — just let us know your plans! "
            f"Would you like help with a reservation?"
        )

    # Late check-in / check-out specific
    if actual_topic in ("late_check_in", "late_check_out"):
        if actual_topic == "late_check_in":
            return (
                f"Late check-in is absolutely possible! Our standard window is {h['policies']['check_in']}, "
                f"but we can accommodate late arrivals on request. Just contact our reception in advance "
                f"and we'll make sure everything is ready for you. What time were you planning to arrive?"
            )
        else:
            return (
                f"Late check-out is available on request, subject to availability. Additional fees may apply. "
                f"Our standard check-out is {h['policies']['check_out']}. "
                f"What time would you like to check out? I can note your preference."
            )

    # Rooms
    if actual_topic == "rooms":
        for room in h["rooms"].values():
            if any(word in q for word in room["name"].lower().split()):
                features = ", ".join(room.get("features", [])[:3])
                return (
                    f"{room['name']} — {room['price']} EUR/night. {room['description']} "
                    f"Features: {features}. "
                    f"Would you like to book this suite or see other options?"
                )
        lines = ["We have 6 beautiful room options for you:"]
        for r in h["rooms"].values():
            size = f", {r['size_sqm']}m²" if r.get("size_sqm") else ""
            cap = f", sleeps {r['capacity']}" if r.get("capacity") else ""
            feat = ", ".join(r.get("features", [])[:2])
            lines.append(f"• {r['name']}: €{r['price']}/night{size}{cap} — {feat}")
        lines.append("\nWhich one catches your eye? I can tell you more about any of them!")
        return "\n".join(lines)

    # Policies
    if actual_topic == "policies":
        return (
            f"Check-in: {h['policies']['check_in']}. Check-out: {h['policies']['check_out']}. "
            f"Breakfast is €22/person. Free parking and WiFi. Pets allowed on request. "
            f"Is there a specific policy you'd like to know more about?"
        )

    # Breakfast
    if actual_topic == "breakfast":
        return (
            f"{h['policies']['breakfast']} "
            f"Shall I add breakfast to your booking, or would you like to know about local restaurants too?"
        )

    # Parking
    if actual_topic == "parking":
        return (
            f"{h['policies']['parking']} "
            f"Will you be driving to Bled, or would you like tips on public transport?"
        )

    # WiFi
    if actual_topic == "wifi":
        return (
            f"{h['policies']['wifi']} "
            f"Anything else you'd like to know about our amenities?"
        )

    # Pets
    if actual_topic == "pets":
        return (
            f"{h['policies']['pets']} "
            f"Are you planning to bring a furry friend along?"
        )

    # Cancellation
    if actual_topic == "cancellation":
        return (
            f"{h['policies']['cancellation']} "
            f"Would you like me to note any special conditions for your booking?"
        )

    # Payment
    if actual_topic == "payment":
        return (
            f"{h['policies']['payment']} "
            f"Would you like to proceed with a booking?"
        )

    # Children
    if actual_topic == "children":
        return (
            f"{h['policies']['children']} "
            f"Traveling with family? I can help find the best room for everyone!"
        )

    # Smoking
    if actual_topic == "smoking":
        return (
            f"{h['policies']['smoking']} "
            f"Is there anything else I can help you with?"
        )

    # Location
    if actual_topic == "location":
        return (
            f"We're at {h['location']['address']}. "
            f"{h['location']['description']} "
            f"Phone: {h['location']['phone']}. "
            f"Would you like directions or tips on getting here?"
        )

    # Experiences
    if actual_topic == "experiences":
        return (
            f"There's so much to do! Popular options: {', '.join(h['experiences'][:5])}. "
            f"Would you like more details on any of these, or shall I help with booking activities?"
        )

    # Contact
    if actual_topic == "contact":
        return (
            f"You reach us at {h['location']['phone']} or {h['location']['email']}. "
            f"Or just keep chatting with me — I'm here to help! What else would you like to know?"
        )

    # Amenities
    if actual_topic == "amenities":
        return (
            f"We offer: {', '.join(h['amenities'][:8])}. "
            f"Would you like the full list, or is there something specific you're looking for?"
        )

    # Fallback
    return (
        f"Villa Adora Bled is a heritage-protected villa from 1878, converted into a luxury design hotel "
        f"right on Lake Bled. We have 6 unique suites with panoramic lake views. "
        f"What would you like to know — rooms, booking, or things to do in Bled?"
    )


app = Flask(__name__)
sessions = {}


@app.route("/")
def index():
    return render_template("index.html", hotel=hotel_info, hotel_name=hotel_info["name"])


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.json
    session_id = data.get("session_id", "default")
    user_message = data.get("message", "")
    if not user_message.strip():
        return jsonify({"replies": [{"type": "text", "content": "Empty input."}]})
    if session_id not in sessions:
        sessions[session_id] = [{"role": "system", "content": str(build_system_prompt())}]
    messages = sessions[session_id]
    messages = apply_rag_to_messages(messages, user_message)
    sessions[session_id] = messages
    messages.append({"role": "user", "content": user_message})
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=[book_room_function, query_hotel_info_function],
            temperature=0.7,
            max_tokens=300,
        )
        choice = response.choices[0] if response.choices else None
        if choice is None:
            return jsonify({"replies": [{"type": "text", "content": "No response from model."}]}), 500

        msg = choice.message
        content = fix_spacing(getattr(msg, "content", None) or "")
        tool_calls = getattr(msg, "tool_calls", None) or []
        assistant_msg = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "function": {
                        "name": tc.function.name if hasattr(tc.function, "name") else tc.get("function", {}).get("name"),
                        "arguments": tc.function.arguments if hasattr(tc.function, "arguments") else tc.get("function", {}).get("arguments"),
                    }
                }
                for tc in tool_calls
            ]
        messages.append(assistant_msg)
        replies = []
        for tc in tool_calls:
            fn = (
                tc.function.name
                if hasattr(tc, "function") and hasattr(tc.function, "name")
                else tc.get("function", {}).get("name")
            )
            raw_args = (
                tc.function.arguments
                if hasattr(tc, "function") and hasattr(tc.function, "arguments")
                else tc.get("function", {}).get("arguments")
            )
            if not fn:
                continue
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except (json.JSONDecodeError, TypeError):
                    args = {}
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}
            if not isinstance(args, dict):
                continue
            if fn == "book_room":
                room_key = args["room_name"].lower().replace(" ", "_")
                price = hotel_info["rooms"].get(room_key, {}).get("price", "")
                price_str = f" ({price} EUR/night)" if price else ""
                replies.append(
                    {
                        "type": "confirmation_request",
                        "content": (
                            f"Booking Confirmation\n\n"
                            f"• Guest: {args['guest_name']}\n"
                            f"• Check-in: {args['check_in']}\n"
                            f"• Check-out: {args['check_out']}\n"
                            f"• Room: {args['room_name']}{price_str}\n\n"
                            "Reply yes to confirm or no to cancel."
                        ),
                    }
                )
                sessions[session_id] = messages + [
                    {"role": "system", "content": f"BOOKING_PENDING: {json.dumps(args)}"}
                ]
            elif fn == "query_hotel_info":
                topic = args.get("topic", "general")
                question = args.get("question", user_message)
                answer = get_hotel_info_response(topic, question)
                if not answer or not answer.strip():
                    answer = get_hotel_info_response("general", user_message)
                if not answer or not answer.strip():
                    answer = (
                        "I'd be happy to help with that! Could you tell me more about what you'd like to know? "
                        "I can assist with rooms, check-in times, breakfast, parking, and more."
                    )
                answer = fix_spacing(answer)
                replies.append({"type": "text", "content": answer})
                messages.append({"role": "tool", "content": answer})
        if not replies:
            # Fallback: if model returned empty content, try to answer directly
            if tool_calls:
                # Try to answer from hotel data directly
                fallback = get_hotel_info_response("general", user_message)
                replies.append({"type": "text", "content": fallback})
            else:
                replies.append({"type": "text", "content": content})
        return jsonify({"replies": replies})
    except Exception as e:
        return jsonify({"replies": [{"type": "text", "content": f"Error: {str(e)}"}]}), 500


@app.route("/api/confirm", methods=["POST"])
def api_confirm():
    data = request.json
    session_id = data.get("session_id", "default")
    confirmed = data.get("confirmed", False)
    messages = sessions.get(session_id, [])
    for i in range(len(messages) - 1, -1, -1):
        item = messages[i]
        if not isinstance(item, dict):
            continue
        if item.get("role") == "system" and "BOOKING_PENDING" in item.get("content", ""):
            try:
                pending = json.loads(item.get("content", "").split(":", 1)[1].strip())
            except Exception:
                pending = {}
            if not pending:
                return jsonify({"reply": {"type": "text", "content": "No pending booking."}})
            if confirmed:
                add_booking(
                    pending.get("guest_name", ""),
                    pending.get("room_name", ""),
                    pending.get("check_in", ""),
                    pending.get("check_out", ""),
                )
                response = (
                    f"✅ Confirmed for {pending.get('guest_name', 'guest')}!"
                    f" Welcome to {hotel_info['name']}."
                )
            else:
                response = "❌ Canceled."
            messages.pop(i)
            sessions[session_id] = messages
            return jsonify({"reply": {"type": "text", "content": response}})
    return jsonify({"reply": {"type": "text", "content": "No pending booking."}})


@app.route("/api/bookings", methods=["GET"])
def api_bookings():
    conn = sqlite3.connect("hotel.db")
    c = conn.cursor()
    c.execute("SELECT * FROM bookings ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return jsonify(
        {
            "bookings": [
                {
                    "id": r[0],
                    "guest": r[1],
                    "room": r[2],
                    "check_in": r[3],
                    "check_out": r[4],
                }
                for r in rows
            ]
        }
    )


@app.route("/admin")
def admin():
    return render_template("admin.html", hotel_name=hotel_info["name"])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5173))
    print(f"🏔️  {hotel_info['name']} — Fast Mode")
    print(f"📍 http://localhost:{port} | 📊 /admin")
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)
