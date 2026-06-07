import os
import subprocess
import json
import re
from openai import OpenAI
from database import add_booking, init_db, add_calendar_event, get_all_calendar_events
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
MODEL = os.environ.get("LLM_MODEL", "anthropic/claude-sonnet-4")

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
    # But be careful not to break intentional camelCase or common patterns
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    # Fix common LLM spacing glitches
    text = re.sub(r'\bwewelcome\b', 'we welcome', text, flags=re.IGNORECASE)
    text = re.sub(r'\barriveat\b', 'arrive at', text, flags=re.IGNORECASE)
    text = re.sub(r'\binhouse\b', 'in-house', text, flags=re.IGNORECASE)
    text = re.sub(r'\bcheckout\b', 'check-out', text, flags=re.IGNORECASE)
    text = re.sub(r'\bcheckin\b', 'check-in', text, flags=re.IGNORECASE)
    text = re.sub(r'\babar\b', 'a bar', text, flags=re.IGNORECASE)
    text = re.sub(r'\blakeview\b', 'lake view', text, flags=re.IGNORECASE)
    text = re.sub(r'\bfreeWiFi\b', 'free WiFi', text, flags=re.IGNORECASE)
    text = re.sub(r'\bnon-smoking\b', 'non-smoking', text, flags=re.IGNORECASE)
    # Fix missing space after period before "The" or other common words
    text = re.sub(r'\.(The|We|Our|You|It|I|For|And|But|Or|If|When|How|What|Where|Yes|No|Please|Thank)', r'. \1', text)
    # Fix missing space before parentheses
    text = re.sub(r'([a-zA-Z])\(', r'\1 (', text)
    # Fix multiple spaces
    text = re.sub(r'  +', ' ', text)
    return text.strip()


def clean_response(text):
    """Remove model reasoning/chain-of-thought text from responses."""
    # If the text contains what looks like reasoning followed by a final answer,
    # extract only the final answer portion
    # Common patterns: "Thus:", "Therefore:", "So we can say:", "Let's craft:"
    # Also handle cases where the model outputs reasoning in quotes
    lines = text.split('\n')
    
    # If the response is very long and contains reasoning markers, trim it
    reasoning_markers = [
        "we need to respond:", "according to the rules:", "so we can say:",
        "let's craft:", "thus:", "therefore:", "i should", "we should",
        "the guest says", "they already gave", "we can confirm",
        "end with a follow-up", "i've noted your"
    ]
    
    # Check if the text has reasoning mixed in
    has_reasoning = any(marker in text.lower() for marker in reasoning_markers)
    
    if has_reasoning and len(text) > 200:
        # Try to find the actual response after reasoning
        # Look for the last substantial sentence that sounds like a response
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i].strip()
            if line and len(line) > 20 and not any(m in line.lower() for m in reasoning_markers):
                # Found a clean line, return from here
                return '\n'.join(lines[i:]).strip()
    
    return text


def extract_time_from_message(message):
    """Extract time from a natural language message like 'I'll arrive at 10pm' or 'around 22:30'."""
    # Match patterns like "10pm", "10 pm", "10:30pm", "22:30", "10:00 PM", "at 10", "around 10pm"
    patterns = [
        r'(?:at|around|about|by|before|after)\s+(\d{1,2}):?(\d{2})?\s*(am|pm|AM|PM)?',
        r'(\d{1,2}):(\d{2})\s*(am|pm|AM|PM)?',
        r'(\d{1,2})\s*(am|pm|AM|PM)',
        r'(?:at|around|about|by|before|after)\s+(\d{1,2})\s*(am|pm|AM|PM)?',
    ]
    msg_lower = message.lower()
    for pattern in patterns:
        match = re.search(pattern, msg_lower)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            ampm = match.group(3) if len(match.groups()) >= 3 and match.group(3) else None
            if ampm:
                ampm = ampm.lower()
                if ampm == 'pm' and hour < 12:
                    hour += 12
                elif ampm == 'am' and hour == 12:
                    hour = 0
            return f"{hour:02d}:{minute:02d}"
    return None


def build_system_prompt() -> str:
    return (
        "You are Luka, a friendly hotel concierge at Villa Adora Bled, a luxury boutique hotel on Lake Bled, Slovenia.\n\n"
        "LANGUAGE:\n"
        "- Detect the guest's language from their message and respond in the SAME language.\n"
        "- Supported languages: English, Slovenian (Slovenščina), German (Deutsch), Italian (Italiano), French (Français), Spanish (Español), Croatian (Hrvatski), Serbian (Srpski), and any other language you can handle.\n"
        "- If the guest writes in Slovenian, respond in Slovenian. If in German, respond in German, etc.\n"
        "- Keep the same warm, concise style regardless of language.\n"
        "- IMPORTANT: When a tool returns English information (like a room list), you MUST translate it to the guest's language before sending.\n\n"
        "STYLE:\n"
        "- Be warm, concise, and conversational — like a real human concierge.\n"
        "- Keep responses to 2-3 sentences max for simple answers. For listings (rooms, experiences), use bullet points.\n"
        "- Always end with a follow-up question to keep the guest engaged.\n"
        "- NEVER mention technical details: no databases, APIs, SQLite, Flask, Ollama, RAG, tools, or internal systems.\n"
        "- NEVER mention room prices unless the guest specifically asks about pricing.\n"
        "- If asked how booking works, simply say: 'I can help you book! Just tell me your name, dates, and preferred room.'\n\n"
        "RESPONSE QUALITY:\n"
        "- Ensure proper spacing between words. Avoid run-on words like 'wewe' or 'abar'.\n"
        "- Never output raw dictionary values or technical data structures.\n"
        "- Give ONE cohesive answer — don't send multiple separate replies unless each is clearly distinct.\n"
        "- If you don't know something, say so warmly and suggest contacting the hotel directly.\n\n"
        "KEY FACTS:\n"
        "- Check-in: 14:00-21:00 | Check-out: 07:00-11:00\n"
        "- Late check-in/out: Available on request, contact reception\n"
        "- Breakfast: €22/person, served 8-10 AM. Vegan, vegetarian, gluten-free options available on request.\n"
        "- Restaurant: Adora Pop Up Restaurant — creative Slovenian cuisine by Chef Domen Demšar. Lunch/dinner Tue-Sun, brunch Thu-Sat. Terrace with best lake views in Bled. Tasting menu ~€65/person, wine pairing ~€35/person. Reservations: +386 40 558 158 or evita.vilebled@gmail.com\n"
        "- Wine list: curated Slovenian and international wines by in-house expert\n"
        "- Bar: cocktails and aperitivos daily on terrace with panoramic lake views\n"
        "- Free parking and WiFi\n"
        "- Pets allowed on request\n"
        "- Address: Cesta svobode 35, Bled, Slovenia\n"
        "- Phone: +386 51 603 858\n\n"
        "ROOMS: Princess Suite (55 m², tower view), Luxury Suite (lake view), Penthouse Suite (60 m², 2 floors), Swan Suite, Island Suite (sleeps 4, 65 m²), Prestige Suite (72 m², ground floor), Castle Suite — all with lake views.\n\n"
        "NEVER do:\n"
        "- Mention databases, code, APIs, or technical systems\n"
        "- Mention prices unless asked\n"
        "- Ask for booking reference or reservation ID\n"
        "- Give bare answers without a follow-up question\n"
        "- Send multiple separate replies to a single question"
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
        "breakfast": ["breakfast", "morning meal", "brunch"],
        "restaurant": ["restaurant", "dining", "dinner", "lunch", "menu", "chef", "domen", "demšar", "demar", "pop up", "pop-up", "terrace dining", "food", "eat", "meal"],
        "wine": ["wine", "wines", "wine list", "wine pairing", "sommelier", "vineyard", "cellar"],
        "bar": ["bar", "cocktail", "cocktails", "aperitivo", "drinks", "mixologist"],
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
                    f"{room['name']} — {room['description']} "
                    f"Features: {features}. "
                    f"Would you like to book this suite or see other options?"
                )
        lines = ["We have 7 beautiful suites, all with stunning lake views:"]
        for r in h["rooms"].values():
            size = f", {r['size_sqm']} m²" if r.get("size_sqm") else ""
            cap = f", sleeps {r['capacity']}" if r.get("capacity") else ""
            feat = ", ".join(r.get("features", [])[:2])
            lines.append(f"• {r['name']}{size}{cap} — {feat}")
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
        b = h.get("dining", {}).get("breakfast", {})
        if isinstance(b, dict):
            dietary = b.get("dietary", {})
            # Check if asking about dietary needs
            if any(word in q for word in ["vegan", "vegetarian", "gluten", "allergy", "allergies", "dietary", "diet", "restriction"]):
                return (
                    f"Breakfast is €22/person, served 8-10 AM in our dining room. "
                    f"We're happy to accommodate dietary needs — just let us know when you book! "
                    f"We offer vegan, vegetarian, and gluten-free options on request, "
                    f"and can handle allergies and other dietary requirements with advance notice. "
                    f"Would you like to add breakfast to your booking?"
                )
            return (
                f"Breakfast is €22/person, served daily 8-10 AM in our dining room with fresh pastries, bread, and local Slovenian products. "
                f"We also offer vegan, vegetarian, and gluten-free options on request. "
                f"Shall I add breakfast to your booking?"
            )
        # Fallback for old string format
        return (
            f"{b} "
            f"Vegan, vegetarian, and gluten-free options are available on request. "
            f"Shall I add breakfast to your booking?"
        )

    # Restaurant
    if actual_topic == "restaurant":
        r = h.get("dining", {}).get("restaurant", {})
        return (
            f"We have the {r.get('name', 'Adora Pop Up Restaurant')} right here at the hotel! "
            f"{r.get('description', 'Creative Slovenian cuisine with stunning lake views.')} "
            f"Hours: Lunch & Dinner {r.get('hours', {}).get('lunch', 'Tue-Sun')}, "
            f"Brunch {r.get('hours', {}).get('brunch', 'Thu-Sat')}. "
            f"The terrace has arguably the best sunset views in Bled. "
            f"Reservations: {r.get('phone', '+386 40 558 158')} or {r.get('email', 'evita.vilebled@gmail.com')}. "
            f"Would you like to make a reservation?"
        )

    # Wine list
    if actual_topic == "wine":
        return (
            f"Our wine list is curated by an in-house wine expert, featuring the best Slovenian wines "
            f"from vineyards near Bled alongside selected international labels. "
            f"Wine pairing is available with our tasting menu (approximately €35/person). "
            f"The tasting menu itself is approximately €65/person. "
            f"For the full current wine list, I'd recommend contacting the restaurant directly at "
            f"+386 40 558 158. Would you like to reserve a table?"
        )

    # Bar
    if actual_topic == "bar":
        return (
            f"Our bar serves elegant cocktails and aperitivos daily on the terrace with panoramic lake views. "
            f"It's the perfect spot for sunset drinks! The terrace is open every day. "
            f"Would you like to know about our pop-up dining events too?"
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

    # Villa Pomona
    if "villa pomona" in q or "pomona" in q:
        vp = h.get("villa_pomona", {})
        return (
            f"We also offer {vp.get('name', 'Villa Pomona')} — {vp.get('type', 'a luxury villa retreat')}. "
            f"Located on {vp.get('location', 'the most picturesque street in Bled')}. "
            f"It features {vp.get('accommodations', {}).get('bedrooms', 3)} bedrooms with ensuite bathrooms, "
            f"a swimming pool, sauna, and garden. "
            f"Perfect for families or groups seeking a private retreat. "
            f"Would you like more details or to make an inquiry?"
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

    # Trim conversation to last 10 messages to avoid token limits
    if len(messages) > 12:
        messages = [messages[0]] + messages[-10:]
        sessions[session_id] = messages

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=[book_room_function, query_hotel_info_function],
            temperature=0.7,
            max_tokens=500,
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

                # If guest provided a specific time for late check-in/out, save to calendar
                if topic in ("late_check_in", "late_check_out", "check_in", "check_out"):
                    extracted_time = extract_time_from_message(user_message)
                    if extracted_time:
                        event_type = "late_check_in" if "check_in" in topic or "arrival" in user_message.lower() else "late_check_out"
                        # Try to get guest name from session messages
                        guest_name = "Guest"
                        for msg in messages:
                            if isinstance(msg, dict) and msg.get("role") == "user":
                                # Simple name extraction — look for patterns like "my name is X" or "I'm X"
                                name_match = re.search(r"(?:my name is|i'm|i am|this is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", msg.get("content", ""), re.IGNORECASE)
                                if name_match:
                                    guest_name = name_match.group(1)
                                    break
                        add_calendar_event(
                            session_id=session_id,
                            event_type=event_type,
                            guest_name=guest_name,
                            time=extracted_time,
                            notes=f"Guest requested {event_type.replace('_', ' ')} at {extracted_time}. Original message: {user_message}"
                        )
                        answer += f" I've noted your {event_type.replace('_', ' ')} time of {extracted_time} in our calendar. "

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

        # Check if guest mentioned a late check-in or check-out time in this message
        # and save to calendar for hotel staff awareness
        msg_lower = user_message.lower()
        is_late_checkin = any(word in msg_lower for word in ["late check-in", "late checkin", "arrive late", "late arrival", "arriving late", "late at", "arrive at", "get in late", "coming late", "late check in"])
        is_late_checkout = any(word in msg_lower for word in ["late check-out", "late checkout", "late check out", "check out late", "later checkout"])
        if is_late_checkin or is_late_checkout:
            extracted_time = extract_time_from_message(user_message)
            if extracted_time:
                event_type = "late_check_in" if is_late_checkin else "late_check_out"
                # Try to get guest name from session messages
                guest_name = "Guest"
                for msg in messages:
                    if isinstance(msg, dict) and msg.get("role") == "user":
                        name_match = re.search(r"(?:my name is|i'm|i am|this is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", msg.get("content", ""), re.IGNORECASE)
                        if name_match:
                            guest_name = name_match.group(1)
                            break
                add_calendar_event(
                    session_id=session_id,
                    event_type=event_type,
                    guest_name=guest_name,
                    time=extracted_time,
                    notes=f"Guest requested {event_type.replace('_', ' ')} at {extracted_time}. Message: {user_message}"
                )
                # Append confirmation to the last reply
                if replies:
                    replies[-1]["content"] += f" I've noted your {event_type.replace('_', ' ')} time of {extracted_time} in our calendar for the hotel staff."
            else:
                # Guest mentioned late check-in/out but no specific time found
                if replies:
                    replies[-1]["content"] += " What time would you like to check out? I can note it in our calendar."

        # Clean up any model reasoning text from responses
        for reply in replies:
            if reply.get("type") == "text" and reply.get("content"):
                reply["content"] = clean_response(reply["content"])
            # If content is empty after cleaning, provide a fallback
            # If content is empty after cleaning, provide a fallback
            if reply.get("type") == "text" and not reply.get("content", "").strip():
                msg_lower = user_message.lower()
                if any(word in msg_lower for word in ["restaurant", "menu", "dining", "chef", "food", "eat", "meal", "wine", "bar", "cocktail"]):
                    reply["content"] = (
                        f"We have the Adora Pop Up Restaurant right here at the hotel! "
                        f"Creative Slovenian cuisine by Chef Domen Demšar, served on the terrace with stunning lake views. "
                        f"Tasting menu ~€65/person, wine pairing ~€35/person. "
                        f"Reservations: +386 40 558 158. Would you like to book a table?"
                    )
                else:
                    reply["content"] = (
                        f"Villa Adora Bled is a luxury boutique hotel on Lake Bled. "
                        f"We have 7 unique suites with lake views, a pop-up restaurant, free parking and WiFi. "
                        f"What would you like to know more about?"
                    )

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


@app.route("/static/images/<path:filename>")
def serve_images(filename):
    """Serve hotel images."""
    import os
    from flask import send_from_directory
    image_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "images")
    return send_from_directory(image_dir, filename)


@app.route("/api/calendar", methods=["GET"])
def api_calendar():
    """Get all calendar events (late check-in/out, etc.)."""
    events = get_all_calendar_events()
    return jsonify({
        "events": [
            {
                "id": e[0],
                "session_id": e[1],
                "event_type": e[2],
                "guest_name": e[3],
                "time": e[4],
                "date": e[5],
                "notes": e[6],
                "created_at": e[7],
            }
            for e in events
        ]
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5173))
    print(f"🏔️  {hotel_info['name']} — Fast Mode")
    print(f"📍 http://localhost:{port} | 📊 /admin")
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)
