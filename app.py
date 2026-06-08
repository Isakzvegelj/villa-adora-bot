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
        "description": "Look up hotel information. Call this for ANY factual question about the hotel. Choose the most specific topic: 'rooms' for room types/sizes, 'bar' for cocktails/drinks/aperitivos, 'restaurant' for dining/chef/menu, 'wine' for wine list/pairing, 'breakfast' for morning meal/dietary needs, 'experiences' for activities/things to do/nearby, 'location' for address/directions, 'parking' for car parking, 'pets' for animals, 'policies' for rules, 'amenities' for room facilities, 'contact' for phone/email, 'shuttle' for airport transfer and transport.",
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
                        "restaurant",
                        "wine",
                        "bar",
                        "late_check_in",
                        "late_check_out",
                        "shuttle",
                    ],
                },
                "question": {"type": "string"},
            },
            "required": ["topic", "question"],
        },
    },
}

book_shuttle_function = {
    "type": "function",
    "function": {
        "name": "book_shuttle",
        "description": "Book a shuttle service for the guest. Collect all required details before calling.",
        "parameters": {
            "type": "object",
            "properties": {
                "guest_name": {"type": "string", "description": "Name of the guest"},
                "pickup_location": {"type": "string", "description": "Where to pick up the guest (e.g. 'Ljubljana airport', 'Bled town center', 'train station')"},
                "dropoff_location": {"type": "string", "description": "Where to drop off (usually 'Villa Adora Bled')"},
                "date": {"type": "string", "description": "Date of shuttle in YYYY-MM-DD format"},
                "time": {"type": "string", "description": "Pickup time (e.g. '14:00')"},
                "passengers": {"type": "integer", "description": "Number of passengers", "default": 1},
                "notes": {"type": "string", "description": "Any special requests or notes"},
            },
            "required": ["guest_name", "pickup_location", "date", "time"],
        },
    },
}

request_human_agent_function = {
    "type": "function",
    "function": {
        "name": "request_human_agent",
        "description": "Transfer the guest to a human agent. Use when: guest is frustrated, explicitly asks for a human, has a complex complaint, or the bot cannot resolve the issue.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why the guest needs a human agent"},
                "guest_name": {"type": "string", "description": "Name of the guest if known"},
                "summary": {"type": "string", "description": "Brief summary of the issue"},
            },
            "required": ["reason"],
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
    # Fix "from 8 10 AM" -> "from 8-10 AM" (missing dash in time ranges)
    text = re.sub(r'from (\d{1,2}) (\d{1,2}) (AM|PM)', r'from \1-\2 \3', text, flags=re.IGNORECASE)
    # Fix run-on words: lowercase followed by uppercase with no space
    # But be careful not to break intentional camelCase or common patterns
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    # Fix common all-lowercase merged words from LLM output
    text = re.sub(r'\bbutthe\b', 'but the', text, flags=re.IGNORECASE)
    text = re.sub(r'\bandthe\b', 'and the', text, flags=re.IGNORECASE)
    text = re.sub(r'\bforthe\b', 'for the', text, flags=re.IGNORECASE)
    text = re.sub(r'\btothe\b', 'to the', text, flags=re.IGNORECASE)
    text = re.sub(r'\bonthe\b', 'on the', text, flags=re.IGNORECASE)
    text = re.sub(r'\batthe\b', 'at the', text, flags=re.IGNORECASE)
    text = re.sub(r'\bthisis\b', 'this is', text, flags=re.IGNORECASE)
    text = re.sub(r'\bthatis\b', 'that is', text, flags=re.IGNORECASE)
    text = re.sub(r'\bwhatis\b', 'what is', text, flags=re.IGNORECASE)
    text = re.sub(r'\bhowto\b', 'how to', text, flags=re.IGNORECASE)
    text = re.sub(r'\bthereis\b', 'there is', text, flags=re.IGNORECASE)
    text = re.sub(r'\bhereis\b', 'here is', text, flags=re.IGNORECASE)
    text = re.sub(r'\bcani\b', 'can I', text)
    text = re.sub(r'\bdoyou\b', 'do you', text, flags=re.IGNORECASE)
    text = re.sub(r'\bareyou\b', 'are you', text, flags=re.IGNORECASE)
    text = re.sub(r'\bwouldyou\b', 'would you', text, flags=re.IGNORECASE)
    text = re.sub(r'\bcouldyou\b', 'could you', text, flags=re.IGNORECASE)
    text = re.sub(r'\bhaveyou\b', 'have you', text, flags=re.IGNORECASE)
    text = re.sub(r'\bisit\b', 'is it', text, flags=re.IGNORECASE)
    text = re.sub(r'\bitis\b', 'it is', text, flags=re.IGNORECASE)
    text = re.sub(r'\bweare\b', 'we are', text, flags=re.IGNORECASE)
    text = re.sub(r'\byouare\b', 'you are', text, flags=re.IGNORECASE)
    text = re.sub(r'\btheyare\b', 'they are', text, flags=re.IGNORECASE)
    # Fix common LLM spacing glitches
    text = re.sub(r'\bWi Fi\b', 'WiFi', text)
    text = re.sub(r'\barriveat\b', 'arrive at', text, flags=re.IGNORECASE)
    text = re.sub(r'\binhouse\b', 'in-house', text, flags=re.IGNORECASE)
    text = re.sub(r'\bcheckout\b', 'check-out', text, flags=re.IGNORECASE)
    text = re.sub(r'\bcheckin\b', 'check-in', text, flags=re.IGNORECASE)
    text = re.sub(r'\blatecheck\b(?!out|in|[- ])', 'late check', text, flags=re.IGNORECASE)
    text = re.sub(r'\blatecheckout\b', 'late check-out', text, flags=re.IGNORECASE)
    text = re.sub(r'\blatecheckin\b', 'late check-in', text, flags=re.IGNORECASE)
    text = re.sub(r'\blatecheck-out\b', 'late check-out', text, flags=re.IGNORECASE)
    text = re.sub(r'\blatecheck-in\b', 'late check-in', text, flags=re.IGNORECASE)
    text = re.sub(r'\babar\b', 'a bar', text, flags=re.IGNORECASE)
    text = re.sub(r'\blakeview\b', 'lake view', text, flags=re.IGNORECASE)
    text = re.sub(r'\bfreeWiFi\b', 'free WiFi', text, flags=re.IGNORECASE)
    text = re.sub(r'\balate\b', 'a late', text, flags=re.IGNORECASE)
    text = re.sub(r'\bhelpyou\b', 'help you', text, flags=re.IGNORECASE)
    text = re.sub(r'\bveganoptions\b', 'vegan options', text, flags=re.IGNORECASE)
    text = re.sub(r'\bnon-smoking\b', 'non-smoking', text, flags=re.IGNORECASE)
    text = re.sub(r'\barrangea\b', 'arrange a', text, flags=re.IGNORECASE)
    text = re.sub(r'\bcanoffer\b', 'can offer', text, flags=re.IGNORECASE)
    text = re.sub(r'\btheviews\b', 'the views', text, flags=re.IGNORECASE)
    text = re.sub(r'\bguestcan\b', 'guest can', text, flags=re.IGNORECASE)
    text = re.sub(r'\bwealso\b', 'we also', text, flags=re.IGNORECASE)
    text = re.sub(r'\bwehave\b', 'we have', text, flags=re.IGNORECASE)
    text = re.sub(r'\bwedon\b', "we don", text, flags=re.IGNORECASE)
    text = re.sub(r'\btheviews\b', 'the views', text, flags=re.IGNORECASE)
    text = re.sub(r'\byoucan\b', 'you can', text, flags=re.IGNORECASE)
    text = re.sub(r'\bweoffer\b', 'we offer', text, flags=re.IGNORECASE)
    text = re.sub(r'\bIcan\b', 'I can', text, flags=re.IGNORECASE)
    text = re.sub(r'\bweare\b', 'we are', text, flags=re.IGNORECASE)
    text = re.sub(r'\bthebest\b', 'the best', text, flags=re.IGNORECASE)
    text = re.sub(r'\bthemost\b', 'the most', text, flags=re.IGNORECASE)
    text = re.sub(r'\bnousavons\b', 'nous avons', text, flags=re.IGNORECASE)
    text = re.sub(r'\bdeschambres\b', 'des chambres', text, flags=re.IGNORECASE)
    text = re.sub(r'\bilya\b', 'il y a', text, flags=re.IGNORECASE)
    text = re.sub(r'\bmercibeaucoup\b', 'merci beaucoup', text, flags=re.IGNORECASE)
    text = re.sub(r'\bgraziemolto\b', 'grazie molto', text, flags=re.IGNORECASE)
    text = re.sub(r'\bperfavore\b', 'per favore', text, flags=re.IGNORECASE)
    text = re.sub(r'\bsehrguten\b', 'sehr guten', text, flags=re.IGNORECASE)
    text = re.sub(r'\bvielendank\b', 'vielen Dank', text, flags=re.IGNORECASE)
    text = re.sub(r'\bhabenzimmer\b', 'haben Zimmer', text, flags=re.IGNORECASE)
    text = re.sub(r'\bmolto\b', ' molto', text, flags=re.IGNORECASE)
    text = re.sub(r'\bprosim\b', ' prosim', text, flags=re.IGNORECASE)
    text = re.sub(r'\bimate\b', ' imate', text, flags=re.IGNORECASE)
    text = re.sub(r'\bhvala\b', ' hvala', text, flags=re.IGNORECASE)
    text = re.sub(r'\bzdravo\b', ' zdravo', text, flags=re.IGNORECASE)
    # Fix missing space/question mark before question words: "today are you" -> "today? Are you"
    text = re.sub(r'(today|there|here|so|and|but|yes|no|great|perfect|wonderful|sorry)\s+(are you|do you|would you|can you|will you|is it|can I|shall I|should I|have you|did you|were you)\s', r'\1? \2 ', text, flags=re.IGNORECASE)
    # Fix missing space after period before "The" or other common words
    text = re.sub(r'\.(The|We|Our|You|It|I|For|And|But|Or|If|When|How|What|Where|Yes|No|Please|Thank)', r'. \1', text)
    # Fix missing space after period in other languages
    text = re.sub(r'\.(Il|La|Le|Les|Un|Une|El|Los|Las|Der|Die|Das|Ein|Una|Lo|Gli)', r'. \1', text)
    # Fix missing space before parentheses
    text = re.sub(r'([a-zA-Z])\(', r' \1 (', text)
    # Fix multiple spaces
    text = re.sub(r'  +', ' ', text)
    return text.strip()


def clean_response(text):
    """Remove model reasoning/chain-of-thought text from responses."""
    import re as _re
    # Remove any leaked tool definitions or JSON schemas
    text = _re.sub(r'<tools>.*?</tools>', '', text, flags=_re.DOTALL | _re.IGNORECASE)
    text = _re.sub(r'\{.*?"description".*?"name".*?"parameters".*?\}', '', text, flags=_re.DOTALL)
    # Remove any remaining JSON-like blocks that look like tool definitions
    text = _re.sub(r'\{.*?"type":\s*"object".*?"properties".*?\}', '', text, flags=_re.DOTALL)
    # Remove trailing incomplete tags or JSON (e.g. "</" or '{"key":' at the end)
    text = _re.sub(r'[<\[][\w:/]*$', '', text)
    text = _re.sub(r'\{"[^"]*":?\s*$', '', text)
    # Remove trailing incomplete sentences (ending with comma or conjunction)
    text = _re.sub(r',\s*$', '.', text)
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
        "LANGUAGE (CRITICAL — THIS IS THE MOST IMPORTANT RULE):\n"
        "- You MUST detect the guest's language from their message and respond ENTIRELY in that same language.\n"
        "- Supported languages: English, Slovenian (Slovenščina), German (Deutsch), Italian (Italiano), French (Français), Spanish (Español), Croatian (Hrvatski), Serbian (Srpski).\n"
        "- When a tool returns English information, you MUST translate it to the guest's language. This is NON-NEGOTIABLE.\n"
        "- Example: If guest writes in Slovenian and the tool returns 'We have 7 beautiful suites', you must respond with 'Imamo 7 čudovitih apartmajev' — NOT the English text.\n"
        "- If the guest writes in German, respond in German. If in French, respond in French. ALWAYS match the guest's language.\n"
        "- Keep the same warm, concise style regardless of language.\n"
        "- NEVER switch to English mid-response unless the guest wrote in English.\n\n"
        "STYLE:\n"
        "Be warm, concise, and conversational — like a real human concierge.\n"
        "Keep responses to 2-3 sentences max for simple answers. For listings (rooms, experiences), use bullet points.\n"
        "Always end with a follow-up question to keep the guest engaged.\n"
        "NEVER mention technical details: no databases, APIs, SQLite, Flask, Ollama, RAG, tools, or internal systems.\n"
        "NEVER mention room prices unless the guest specifically asks about pricing.\n"
        "If asked how booking works, simply say: 'I can help you book! Just tell me your name, dates, and preferred room.'\n"
        "If asked about weather, say: 'I don't have real-time weather data, but I'd recommend checking a weather app for the latest forecast. Bled has beautiful summers and snowy winters!'\n"
        "- ALWAYS use the query_hotel_info tool for factual questions (rooms, policies, location, parking, pets, breakfast, restaurant, bar, wine, activities, etc.) — do NOT answer from your own knowledge, use the tool to get accurate data.\n\n"
        "RESPONSE QUALITY:\n"
        "- Ensure proper spacing between words. Avoid run-on words like 'wewe' or 'abar'.\n"
        "- Never output raw dictionary values or technical data structures.\n"
        "- Give ONE cohesive answer — don't send multiple separate replies unless each is clearly distinct.\n"
        "- If you don't know something, say so warmly and suggest contacting the hotel directly.\n"
        "- MANDATORY: You MUST call query_hotel_info for ALL factual questions about the hotel. NEVER answer factual questions from your own knowledge — always use the tool to get accurate, up-to-date information. This includes: rooms, check-in/out, breakfast, restaurant, bar, wine, parking, pets, location, activities, policies, amenities, contact info, shuttle, and pricing.\n\n"
        "KEY FACTS:\n"
        "- Check-in: 14:00-23:00 | Check-out: 07:00-11:00\n"
        "- Late check-in/out: Available on request, contact reception\n"
        "- Breakfast: €22/person, served 8-10 AM. Vegan, vegetarian, gluten-free options available on request.\n"
        "- Restaurant: Adora Pop Up Restaurant — creative Slovenian cuisine with French, Italian, and international influences by Chef Domen Demšar. Lunch/dinner Tue-Sun, brunch Thu-Sat. Terrace with best lake views in Bled. Tasting menu ~€65/person, wine pairing ~€35/person. Reservations: +386 40 558 158 or evita.vilebled@gmail.com\n"
        "- Wine list: curated Slovenian and international wines by in-house expert\n"
        "- Bar: cocktails and aperitivos daily on terrace with panoramic lake views\n"
        "- Shuttle service available — airport transfer, local transport, custom routes. Book directly in this chat. Ljubljana airport ~€60, Bled town center ~€15.\n"
        "- Free parking and WiFi (8 parking spots in front of the hotel)\n"
        "- Pets allowed on request — €35 per pet per night\n"
        "- Quiet hours: 22:00-07:00 | Parties/events not allowed\n"
        "- Address: Cesta svobode 35, Bled, Slovenia\n"
        "- Phone: +386 51 603 858\n\n"
        "ROOMS: Princess Suite (55 m², tower view), Luxury Suite (lake view), Penthouse Suite (60 m², 2 floors), Swan Suite, Island Suite (sleeps 4, 65 m²), Prestige Suite (72 m², ground floor), Castle Suite — all with lake views.\n\n"
        "NEVER do:\n"
        "- Mention databases, code, APIs, or technical systems\n"
        "- Mention prices unless asked\n"
        "- Ask for booking reference or reservation ID\n"
        "- Give bare answers without a follow-up question\n"
        "- Send multiple separate replies to a single question\n"
        "- If guest is frustrated, unsatisfied, or explicitly asks for a human, use request_human_agent() to transfer them\n"
        "- If you cannot answer a question well, offer to connect the guest with a human agent\n"
        "- Shuttle bookings: use book_shuttle() when guest wants to book a shuttle. Ask for: name, pickup location, date, time, passengers.\n"
        "- Human agent: use request_human_agent() when guest needs human help. Always offer this as an option if the guest seems unhappy.\n"
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


def _detect_language(message: str) -> str:
    """Simple language detection based on common words and character patterns.
    Uses word-boundary matching and scoring to avoid false positives."""
    msg = " " + message.lower().strip() + " "
    
    # Character-based detection for languages with unique characters
    # Only use characters that are unambiguous for a single language
    has_diacritics = {
        'š': 'sl', 'č': 'sl', 'ž': 'sl',  # Slovenian/Croatian (unambiguous)
        'đ': 'hr',  # Croatian/Serbian (unambiguous)
        'ß': 'de',  # German (unambiguous)
        'ñ': 'es',  # Spanish (unambiguous)
    }
    
    # Count diacritics per language
    lang_scores = {}
    for char, lang in has_diacritics.items():
        if char in msg:
            lang_scores[lang] = lang_scores.get(lang, 0) + 1
    
    # If Slovenian-specific characters found, likely Slovenian
    if any(c in msg for c in ['š', 'č', 'ž']):
        slovenian_markers = [" imate ", " kakšen ", " kako ", " lahko ", " želim ", " prosim ", " hvala ", " pozdravljeni ", " dober dan ", " zdravo ", " sobe ", " soba "]
        if any(w in msg for w in slovenian_markers):
            return "Slovenian"
        # Even without specific words, š/č/ž strongly suggest Slovenian/Croatian
        if 'đ' in msg or 'ć' in msg:
            return "Croatian"
        return "Slovenian"
    
    # If strong diacritic signal, return that language
    if lang_scores:
        best_lang = max(lang_scores, key=lang_scores.get)
        lang_map = {'de': 'German', 'fr': 'French', 'es': 'Spanish', 'it': 'Italian', 'hr': 'Croatian', 'sl': 'Slovenian'}
        if lang_scores[best_lang] >= 2:  # Need at least 2 diacritics
            return lang_map.get(best_lang, 'English')
    
    # Multi-word phrases that are highly distinctive per language
    # These are phrases that would NOT appear in English
    # Uses word-boundary matching via regex for robustness
    distinctive_phrases = {
        "German": [
            " guten tag ", " guten morgen ", " guten abend ", " vielen danke ",
            " auf wiedersehen ", " wie geht ", " haben sie ", " ich möchte ",
            " können wir ", " ich hätte ", " buchung ", " zimmer ", " frühstück ",
            " parkplatz ", " haustier ", " abreise ", " anreise ", " wunderbar "
        ],
        "French": [
            " bonjour ", " bonsoir ", " merci beaucoup ", " s'il vous plaît ",
            " je voudrais ", " avez-vous ", " nous avons ", " les chambres ",
            " petit déjeuner ", " au revoir ", " bienvenue ", " c'est magnifique ",
            " je suis ", " vous êtes ", " quelles ", " quelle ",
            " suis-je ", " êtes-vous ", " réservez ", " réservé ",
            " chambre ", " combien ", " comment ", " excusez ",
            " madame ", " monsieur ", " enchanté "
        ],
        "Italian": [
            " buongiorno ", " buonasera ", " grazie mille ", " per favore ",
            " vorrei ", " avete ", " prenotazione ", " colazione ", " ristorante ",
            " arrivederci ", " benvenuto ", " magnifico ", " bellissimo ", " camere ",
            " camera ", " albergo ", " parcheggio ", " pranzo ", " cena ",
            " buona notte ", " quanto costa ", " camere disponibili ",
            " una camera ", " due camere ", " il camera ", " la camera ",
            " il ristorante ", " il parcheggio ", " la colazione ",
            " posso ", " potrei ", " grazie ", " prego "
        ],
        "Spanish": [
            " buenos días ", " buenas tardes ", " muchas gracias ", " por favor ",
            " quisiera ", " tienen ", " habitaciones ", " desayuno ", " restaurante ",
            " bienvenido ", " hasta luego ", " magnífico ", " perfecto "
        ],
        "Slovenian": [
            " pozdravljeni ", " hvala lepo ", " prosim vas ", " kako ste ",
            " dober dan ", " lahko noč ", " nasvidenje ", " rezervacija ", " zajtrk ",
            " imate ", " sobe ", " soba ", " koliko ", " stane ", " najvišja ",
            " najvecja ", " lahko ", " zelim ", " prosim ", " hvala ",
            " zdravo ", " nasvidenje ", " kje ", " kdaj ", " zakaj ", " kako ",
            " brezplacen ", " brezplačen ", " wifi ", " restoran ", " jedilnik ",
            " pijača ", " pijaca ", " sobe ", " apartma ", " apartmajev ",
            " prenočišče ", " prenocisce ", " hotel ", " gostilna ",
            " ali ", " zelo ", " dobro ", " slabo ", " lepo ", " cudovito ",
            " odlicno ", " odlično ", " super ", " hvala ", " prosim ",
            " da ", " ne ", " ja ", " prosim ", " oprostite "
        ],
    }
    
    # Score each language by counting matching distinctive phrases
    # Use word-level matching: check both original and punctuation-stripped versions
    import re as _re
    msg_clean = _re.sub(r'[^\w\s]', ' ', msg)
    scores = {}
    for lang, phrases in distinctive_phrases.items():
        score = 0
        for p in phrases:
            if p in msg or p in " " + msg_clean + " ":
                score += 1
            else:
                # Also try matching: strip the spaces from phrase and check if all words appear
                phrase_words = p.strip().split()
                if len(phrase_words) == 1:
                    # Single word phrase — check word boundary match
                    # Handle plurals: "chambre" should match "chambres"
                    pw = phrase_words[0]
                    # Check if word appears as prefix of any word in msg
                    for w in msg_clean.split():
                        if w.startswith(pw) or pw.startswith(w):
                            if len(pw) >= 4 and len(w) >= 4:  # Avoid short word false matches
                                score += 1
                                break
                            elif pw == w:  # Exact match for short words
                                score += 1
                                break
                elif len(phrase_words) >= 2:
                    # Multi-word phrase: check if all words appear in order (with fuzzy matching)
                    clean_words = msg_clean.split()
                    phrase_stems = [w[:4] for w in phrase_words]  # Use 4-char stems
                    for i in range(len(clean_words) - len(phrase_words) + 1):
                        match = True
                        for j, ps in enumerate(phrase_stems):
                            if not clean_words[i+j].startswith(ps):
                                match = False
                                break
                        if match:
                            score += 1
                            break
        if score > 0:
            scores[lang] = score

    if scores:
        best_lang = max(scores, key=scores.get)
        # Slovenian needs at least 2 matches to avoid false positives
        # (many Slovenian words without diacritics overlap with other languages)
        min_scores = {"Slovenian": 2, "German": 1, "French": 1, "Italian": 1, "Spanish": 1}
        if scores[best_lang] >= min_scores.get(best_lang, 1):
            return best_lang

    return "English"


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
        "rooms": ["room", "suite", "bed", "accommodation", "stay", "sleep", "price", "prices", "cost", "rate", "rates", "how much"],
        "policies": ["policy", "rule", "regulation"],
        "amenities": ["amenity", "facility", "feature", "service", "perk"],
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
        "shuttle": ["shuttle", "airport transfer", "airport shuttle", "book shuttle", "shuttle booking", "airport pickup", "shuttle service"],
        "general": ["general", "info", "information", "about", "tell me"],
        "location": ["location", "address", "where", "direction", "map", "find", "located", "get to", "how do i get", "how to get", "directions to", "transport to", "travel to"],
        "experiences": ["experience", "activity", "thing to do", "attraction", "sight", "visit", "tour", "hike", "swim", "activities", "nearby", "around", "do here", "what to", "day trip", "day trips", "excursion"],
    }

    # Detect actual topic from question if topic is generic
    actual_topic = topic
    if topic in ("general", "policies"):
        for t, aliases in topic_aliases.items():
            if any(a in q for a in aliases):
                actual_topic = t
                break

    # Override: dietary questions should always go to breakfast/dining
    if actual_topic not in ("breakfast",) and any(word in q for word in ["vegan", "vegetarian", "gluten", "allergy", "allergies", "dietary", "diet", "restriction", "celiac", "lactose", "intolerant"]):
        actual_topic = "breakfast"

    # Override: room price questions should always go to rooms (not payment)
    if actual_topic == "payment" and any(word in q for word in ["room", "suite", "accommodation"]):
        actual_topic = "rooms"

    # Override: if topic is general and question mentions room/suite + price, redirect to rooms
    if actual_topic == "general" and any(word in q for word in ["room", "suite"]) and any(word in q for word in ["price", "prices", "cost", "rate", "rates", "how much"]):
        actual_topic = "rooms"

    # Check-in / Check-out
    if actual_topic in ("check_in", "check_out"):
        # Check if asking about late arrival/departure
        if any(word in q for word in ["late", "later", "after", "early", "before", "outside"]):
            if actual_topic == "check_out" or "depart" in q or "check out" in q or "checkout" in q or "leave" in q:
                return (
                    f"Our standard check-out is {h['policies']['check_out']}, but late check-out is available on request! "
                    f"It's subject to availability and additional fees may apply. Contact reception to arrange. "
                    f"What time would you like to check out?"
                )
            else:
                return (
                    f"Our standard check-in is {h['policies']['check_in']}, but late check-in is available on request! "
                    f"Just contact our reception to arrange. We can accommodate late arrivals with advance notice. "
                    f"What time were you planning to arrive?"
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
        # Check if asking about pricing
        is_price_query = any(word in q for word in ["price", "prices", "cost", "how much", "rate", "rates", "expensive", "cheap", "affordable", "cheapest", "pricing", "€", "eur", "euro"])
        
        # Check if asking about a specific room
        for room in h["rooms"].values():
            name_lower = room["name"].lower()
            common_words = {"suite", "the", "and"}
            distinctive_words = [w for w in name_lower.split() if w not in common_words and len(w) > 2]
            if distinctive_words and all(word in q for word in distinctive_words):
                features = ", ".join(room.get("features", [])[:3])
                price_str = f" — €{room['price']}/night" if room.get("price") else ""
                return (
                    f"{room['name']}{price_str}. {room['description']} "
                    f"Features: {features}. "
                    f"Would you like to book this suite or see other options?"
                )
        
        if is_price_query:
            # Show rooms with prices
            lines = ["Here are our suites with nightly rates:"]
            for r in h["rooms"].values():
                size = f", {r['size_sqm']} m²" if r.get("size_sqm") else ""
                cap = f", sleeps {r['capacity']}" if r.get("capacity") else ""
                price = f"€{r['price']}/night" if r.get("price") else "Price on request"
                lines.append(f"• **{r['name']}** — {price}{size}{cap}")
            lines.append("Would you like to book one of these, or do you need more details about a specific suite?")
        else:
            lines = ["We have 7 beautiful suites, all with stunning lake views:"]
            for r in h["rooms"].values():
                size = f", {r['size_sqm']} m²" if r.get("size_sqm") else ""
                cap = f", sleeps {r['capacity']}" if r.get("capacity") else ""
                feat = ", ".join(r.get("features", [])[:2])
                lines.append(f"• **{r['name']}**{size}{cap} — {feat}")
            lines.append("Which one catches your eye? I can start a booking for you — just tell me your name and dates!")
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
            f"It's the perfect spot for sunset drinks! The terrace has arguably the best views in Bled. "
            f"Would you like me to reserve a table for dinner, or shall I tell you about our pop-up dining events?"
        )

    # Parking
    if actual_topic == "parking":
        return (
            f"Yes! {h['policies']['parking']}. "
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
            f"Pets are welcome on request for €35 per pet per night. "
            f"Just let us know when you book and we'll make the arrangements! "
            f"Are you planning to bring a furry friend along?"
        )

    # Cancellation
    if actual_topic == "cancellation":
        return (
            f"Direct bookings enjoy free cancellation up to 48 hours before arrival. "
            f"For third-party bookings, the provider's cancellation policy applies. "
            f"If you have any questions about your specific booking terms, "
            f"feel free to contact us at +386 51 603 858. We're happy to help!"
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

    # Shuttle
    if actual_topic == "shuttle":
        return (
            f"We offer a convenient shuttle service for our guests! "
            f"Airport transfers from Ljubljana are approximately €60, "
            f"and local transport to Bled town center is around €15. "
            f"Custom routes are also available. "
            f"I can book a shuttle for you directly — just tell me your name, "
            f"pickup location, date, and preferred time. "
            f"Would you like to arrange a transfer?"
        )

    # Experiences
    if actual_topic == "experiences":
        return (
            f"There's so much to do around Bled! Here are some highlights:\n"
            f"• Row to Bled Island & visit the Church of the Assumption\n"
            f"• Swimming, paddleboarding, kayaking, and boat tours on the lake\n"
            f"• Vintgar Gorge walk (2.4 km away)\n"
            f"• Bled Castle visit (30 min walk)\n"
            f"• 6 km lakeside walking path & 15 signposted hikes\n"
            f"• Day trips to Lake Bohinj, Ljubljana, Postojna Cave\n"
            f"• In-room massage, garden evenings with wine\n"
            f"Would you like more details on any of these?"
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
            f"We also offer Villa Pomona — a luxury design boutique villa retreat. "
            f"It's located on the most picturesque street in Bled, just a 3-minute walk from the lake and town center. "
            f"The villa features 3 spacious bedrooms with ensuite bathrooms, a swimming pool with pool house, sauna, and a sprawling garden. "
            f"Additional services include a private chef, daily cleaning, massage, yoga, and personal coaching. "
            f"It's perfect for families, friends, or small groups seeking a private retreat. "
            f"Would you like more details or to make an inquiry?"
        )

    # Fallback
    return (
        f"Villa Adora Bled is a heritage-protected villa from 1878, converted into a luxury design hotel "
        f"right on Lake Bled. We have 7 unique suites with panoramic lake views. "
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

    # Trim conversation to last 6 messages to reduce latency
    if len(messages) > 8:
        messages = [messages[0]] + messages[-6:]
        sessions[session_id] = messages

    messages.append({"role": "user", "content": user_message})

    # Detect language and prepare language-specific handling
    detected_lang = _detect_language(user_message)
    is_non_english = detected_lang != "English"

    try:
        # For non-English messages, we use a single-call approach:
        # 1. Retrieve relevant hotel facts via RAG
        # 2. Inject them as a system message with language instruction
        # 3. Let the LLM respond directly (no forced tool call, no second LLM call)
        # This avoids the timeout from the two-call pattern (tool call + translation).
        lang_messages = list(messages)
        if is_non_english:
            # Get relevant hotel data via RAG
            rag_docs = maybe_retrieve_hotel_facts(user_message, max_facts=3)
            # Build a strong language instruction
            lang_instruction = (
                f"CRITICAL LANGUAGE INSTRUCTION: The guest is writing in {detected_lang}. "
                f"You MUST respond ENTIRELY in {detected_lang}. "
                f"Translate ALL information to {detected_lang}. "
                f"Do NOT use English except for proper nouns (like 'Lake Bled', 'Villa Adora'). "
                f"Be warm, concise, and end with a follow-up question in {detected_lang}. "
                f"REMEMBER: The guest cannot understand English. Every word must be in {detected_lang}."
            )
            if rag_docs:
                rag_context = format_rag_context(rag_docs)
                lang_messages.append({
                    "role": "system",
                    "content": f"HOTEL DATA:\n\n{rag_context}\n\n{lang_instruction}"
                })
            else:
                lang_messages.append({
                    "role": "system",
                    "content": lang_instruction
                })
        
        # For non-English messages, exclude query_hotel_info tool since we provide
        # hotel data via RAG context. This prevents the LLM from calling the tool
        # and getting English responses. Keep booking/shuttle tools available.
        if is_non_english:
            available_tools = [book_room_function, book_shuttle_function, request_human_agent_function]
            # Add a forceful language instruction as a user message right before the actual user message
            # This is more likely to be followed than a system message
            lang_prefix = (
                f"[SYSTEM OVERRIDE: You MUST respond in {detected_lang}. "
                f"Translate ALL information to {detected_lang}. "
                f"The guest only understands {detected_lang}. "
                f"Respond ENTIRELY in {detected_lang}. "
                f"End with a follow-up question in {detected_lang}.]"
            )
            # Insert language instruction as a system message right before the user's message
            lang_messages.insert(-1, {
                "role": "system",
                "content": lang_prefix
            })
        else:
            available_tools = [book_room_function, query_hotel_info_function, book_shuttle_function, request_human_agent_function]
        
        tool_params = {
            "model": MODEL,
            "messages": lang_messages,
            "tools": available_tools,
            "temperature": 0.5,
            "max_tokens": 1200,
            "timeout": 50,
        }
        tool_params["tool_choice"] = "auto"
        
        response = client.chat.completions.create(**tool_params)
        choice = response.choices[0] if response.choices else None
        if choice is None:
            return jsonify({"replies": [{"type": "text", "content": "No response from model."}]}), 500

        msg = choice.message
        content = fix_spacing(getattr(msg, "content", None) or "")
        tool_calls = getattr(msg, "tool_calls", None) or []

        # Build assistant message with properly formatted tool_calls (including id and type)
        assistant_msg = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id if hasattr(tc, "id") else tc.get("id", f"call_{i}"),
                    "type": "function",
                    "function": {
                        "name": tc.function.name if hasattr(tc.function, "name") else tc.get("function", {}).get("name"),
                        "arguments": tc.function.arguments if hasattr(tc.function, "arguments") else tc.get("function", {}).get("arguments"),
                    }
                }
                for i, tc in enumerate(tool_calls)
            ]
        messages.append(assistant_msg)
        replies = []
        for i, tc in enumerate(tool_calls):
            tc_id = tc.id if hasattr(tc, "id") else tc.get("id", f"call_{i}")
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
            tool_reply = None
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
                        # Note: We do NOT add calendar confirmation to the guest response —
                        # that's an internal detail. The guest just gets a warm confirmation.

                tool_reply = answer
                # Send tool response directly — for non-English messages, the LLM
                # should have already responded based on RAG context above.
                # If the LLM still called the tool, send the English response as fallback.
                replies.append({"type": "text", "content": answer})
            elif fn == "book_shuttle":
                # Save shuttle booking to database
                from database import add_shuttle_booking
                add_shuttle_booking(
                    session_id=session_id,
                    guest_name=args.get("guest_name", "Guest"),
                    pickup_location=args.get("pickup_location", ""),
                    dropoff_location=args.get("dropoff_location", "Villa Adora Bled"),
                    date=args.get("date", ""),
                    time=args.get("time", ""),
                    passengers=args.get("passengers", 1),
                    notes=args.get("notes", ""),
                )
                tool_reply = (
                    f"Shuttle booked for {args.get('guest_name', 'the guest')}! "
                    f"Pickup: {args.get('pickup_location', 'TBD')} on {args.get('date', 'TBD')} at {args.get('time', 'TBD')}. "
                    f"Passengers: {args.get('passengers', 1)}. "
                    f"Our team will confirm shortly. Is there anything else I can help you with?"
                )
                replies.append({"type": "text", "content": tool_reply})
            elif fn == "request_human_agent":
                # Log the human agent request
                from database import add_human_agent_request
                add_human_agent_request(
                    session_id=session_id,
                    reason=args.get("reason", "Guest requested human agent"),
                    guest_name=args.get("guest_name", "Guest"),
                    summary=args.get("summary", ""),
                )
                tool_reply = (
                    f"I understand you'd like to speak with a human agent. "
                    f"I've notified our reception team — they'll be with you shortly. "
                    f"You can also call us directly at +386 51 603 858. "
                    f"Thank you for your patience!"
                )
                replies.append({"type": "text", "content": tool_reply})
            # Append tool response message with proper tool_call_id
            if tool_reply is not None:
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": tool_reply})

        # Note: No second LLM call needed anymore.
        # Non-English messages use RAG context + language instruction in a single call.

        if not replies:
            # Fallback: if model returned empty content, try to answer directly
            if tool_calls:
                # Try to answer from hotel data directly
                fallback = get_hotel_info_response("general", user_message)
                replies.append({"type": "text", "content": fallback})
            else:
                # LLM didn't call any tool — check if this is a factual question
                # that should have used query_hotel_info
                factual_keywords = [
                    "room", "suite", "check", "breakfast", "restaurant", "bar",
                    "wine", "parking", "pet", "dog", "cat", "location", "address",
                    "where", "activity", "activities", "wifi", "internet", "shuttle",
                    "transfer", "policy", "cancel", "payment", "price", "cost",
                    "hour", "time", "contact", "phone", "email", "direction",
                    "nearby", "around", "do here", "vegan", "vegetarian", "gluten",
                    "dietary", "allergy", "amenity", "facility", "service", "book",
                    "reservation", "available", "offer", "have", "provide"
                ]
                # Non-English factual keywords (Slovenian, German, French, Italian, Spanish)
                non_english_factual = [
                    # Slovenian
                    "soba", "sobe", "zajtrk", "restavracija", "vin", "pijača",
                    "parkir", "pes", "macka", "lokacija", "naslov", "kjer", "kje",
                    "aktivnost", "wifi", "internet", "transfer", "politika",
                    "preklic", "plačilo", "cena", "ura", "čas", "kontakt",
                    "telefon", "email", "smer", "bližina", "vegetarijansko",
                    "brez glutena", "alergija", "udobje", "storitev", "rezervacija",
                    "razpoložljiv", "ponudba", "imeti", "koliko", "stane", "najvišja",
                    "najvecja", "najdražja", "najcenejša",
                    # German
                    "zimmer", "frühstück", "restaurant", "wein", "parkplatz",
                    "haustier", "adresse", "wo", "aktivität", "internet",
                    "transfer", "stornierung", "zahlung", "preis", "kosten",
                    "zeit", "kontakt", "telefon", "richtung", "vegetarisch",
                    "glutenfrei", "allergie", "buchung", "verfügbar",
                    # French
                    "chambre", "petit déjeuner", "restaurant", "vin", "parking",
                    "animal", "adresse", "où", "activité", "internet",
                    "transfert", "annulation", "paiement", "prix", "coût",
                    "heure", "contact", "téléphone", "direction", "végétarien",
                    "sans gluten", "allergie", "réservation", "disponible",
                    # Italian
                    "camera", "colazione", "ristorante", "vino", "parcheggio",
                    "animale", "indirizzo", "dove", "attività", "internet",
                    "trasferimento", "cancellazione", "pagamento", "prezzo",
                    "costo", "ora", "contatto", "telefono", "direzione",
                    "vegetariano", "senza glutine", "allergia", "prenotazione",
                    "disponibile",
                    # Spanish
                    "habitación", "desayuno", "restaurante", "vino", "aparcamiento",
                    "mascota", "dirección", "donde", "actividad", "internet",
                    "transferencia", "cancelación", "pago", "precio", "costo",
                    "hora", "contacto", "teléfono", "dirección", "vegetariano",
                    "sin gluten", "alergia", "reserva", "disponible",
                ]
                msg_lower = user_message.lower()
                is_factual = any(kw in msg_lower for kw in factual_keywords)
                is_factual_non_eng = any(kw in msg_lower for kw in non_english_factual)
                if is_factual or is_factual_non_eng:
                    # LLM didn't use tool for factual question — get data ourselves
                    fallback = get_hotel_info_response("general", user_message)
                    # For room/suite/price questions, always use fallback since LLM data may be wrong
                    is_room_query = any(kw in msg_lower for kw in ["room", "suite", "price", "cost", "how much", "rate"])
                    if is_room_query or len(content.strip()) < 100:
                        # For non-English, the fallback is English — we need to indicate translation needed
                        if is_non_english:
                            # The LLM should have translated, but if it didn't, use fallback
                            # The response will be in English but the guest needs their language
                            # Best effort: include the fallback data
                            replies.append({"type": "text", "content": fallback})
                        else:
                            replies.append({"type": "text", "content": fallback})
                    else:
                        # For non-English factual questions, check if LLM actually translated
                        if is_factual_non_eng and detected_lang != "English":
                            has_non_ascii = any(ord(c) > 127 for c in content)
                            if not has_non_ascii:
                                # LLM responded in English to a non-English factual question
                                # Use the fallback (at least it's factually correct)
                                replies.append({"type": "text", "content": fallback})
                            else:
                                replies.append({"type": "text", "content": content})
                        else:
                            replies.append({"type": "text", "content": content})
                else:
                    replies.append({"type": "text", "content": content})

        # Check if guest mentioned a late check-in or check-out time in this message
        # and save to calendar for hotel staff awareness (only if not already handled by tool)
        msg_lower = user_message.lower()
        is_late_checkin = any(word in msg_lower for word in ["late check-in", "late checkin", "arrive late", "late arrival", "arriving late", "late at", "arrive at", "get in late", "coming late", "late check in"])
        is_late_checkout = any(word in msg_lower for word in ["late check-out", "late checkout", "late check out", "check out late", "later checkout"])
        # Check if calendar event was already added by the tool handler above
        # Simple approach: just save the event (idempotent) — no duplicate check needed
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
                # Internal-only: calendar event saved. Do NOT append to guest response.
            else:
                # Guest mentioned late check-in/out but no specific time found — ask for it
                if replies and "what time would you like" not in replies[-1]["content"].lower():
                    replies[-1]["content"] += " What time would you like? Let me know and I'll pass it along."

        # Clean up any model reasoning text from responses
        for reply in replies:
            if reply.get("type") == "text" and reply.get("content"):
                reply["content"] = clean_response(reply["content"])
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
        import traceback
        traceback.print_exc()
        return jsonify({"replies": [{"type": "text", "content": "I'm sorry, I'm having trouble connecting right now. Please try again in a moment, or call us at +386 51 603 858. Is there anything else I can help with?"}]}), 200


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


@app.route("/api/shuttles", methods=["GET"])
def api_shuttles():
    """Get all shuttle bookings."""
    conn = sqlite3.connect("hotel.db")
    c = conn.cursor()
    c.execute("SELECT * FROM shuttle_bookings ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return jsonify({
        "shuttles": [
            {
                "id": r[0],
                "session_id": r[1],
                "guest_name": r[2],
                "pickup_location": r[3],
                "dropoff_location": r[4],
                "date": r[5],
                "time": r[6],
                "passengers": r[7],
                "notes": r[8],
                "status": r[9],
                "created_at": r[10],
            }
            for r in rows
        ]
    })


@app.route("/api/human-requests", methods=["GET"])
def api_human_requests():
    """Get all human agent requests."""
    conn = sqlite3.connect("hotel.db")
    c = conn.cursor()
    c.execute("SELECT * FROM human_agent_requests ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return jsonify({
        "requests": [
            {
                "id": r[0],
                "session_id": r[1],
                "reason": r[2],
                "guest_name": r[3],
                "summary": r[4],
                "status": r[5],
                "created_at": r[6],
            }
            for r in rows
        ]
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5173))
    print(f"🏔️  {hotel_info['name']} — Fast Mode")
    print(f"📍 http://localhost:{port} | 📊 /admin")
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)
