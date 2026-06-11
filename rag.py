import json
import os
import re
from collections import Counter
import math
from pathlib import Path

CORPUS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rag_corpus.jsonl")


def _load_corpus():
    docs = []
    if not os.path.exists(CORPUS_PATH):
        return docs
    with open(CORPUS_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                text = entry.get("text", "")
                if text:
                    docs.append(text)
            except json.JSONDecodeError:
                continue
    return docs


def _tokenize(text):
    return re.findall(r'\b[a-zA-Z]{2,}\b', text.lower())


def _tf_idf(query, documents, top_k=2):
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    doc_count = len(documents)
    idf = {}
    for token in set(query_tokens):
        df = sum(1 for doc in documents if token in _tokenize(doc))
        idf[token] = math.log((doc_count + 1) / (df + 1)) + 1

    scores = []
    for doc in documents:
        doc_tokens = _tokenize(doc)
        if not doc_tokens:
            continue
        tf = Counter(doc_tokens)
        score = sum(tf.get(token, 0) * idf.get(token, 0) for token in query_tokens)
        if score > 0:
            scores.append((score, doc))

    scores.sort(key=lambda x: x[0], reverse=True)
    return [doc for _, doc in scores[:top_k]]


def retrieve(query: str, top_k: int = 2) -> list[str]:
    docs = _load_corpus()
    if not docs:
        return []
    results = _tf_idf(query, docs, top_k=top_k)
    return results


def build_corpus():
    """Rebuild the RAG corpus from hotel_data.py and knowledge_base.md."""
    import importlib.util

    corpus_entries = []

    # Load hotel_data
    spec = importlib.util.spec_from_file_location("hotel_data", os.path.join(os.path.dirname(os.path.abspath(__file__)), "hotel_data.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load hotel_data.py")
    hotel_mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(hotel_mod)  # type: ignore[union-attr]
        h = hotel_mod.hotel_info

        corpus_entries.append({"source": "hotel_data.py", "text": f"Hotel name: {h['name']}. {h['tagline']}"})
        corpus_entries.append({"source": "hotel_data.py", "text": f"Location: {h['location']['address']}. {h['location']['description']}"})
        corpus_entries.append({"source": "hotel_data.py", "text": f"Phone: {h['location']['phone']}. Email: {h['location']['email']}"})

        for key, room in h.get("rooms", {}).items():
            price_str = f" Price: €{room['price']}/night." if room.get("price") else ""
            corpus_entries.append({
                "source": "hotel_data.py",
                "text": f"Room: {room['name']}. Size: {room.get('size_sqm', 'N/A')} m². Capacity: {room.get('capacity', 2)} guests.{price_str} Features: {', '.join(room.get('features', []))}. Description: {room.get('description', '')}"
            })

        corpus_entries.append({"source": "hotel_data.py", "text": f"Policies: Check-in: {h['policies']['check_in']}. Check-out: {h['policies']['check_out']}. Breakfast: {h['policies']['breakfast']}. Parking: {h['policies']['parking']}. WiFi: {h['policies']['wifi']}. Pets: {h['policies']['pets']}. Children: {h['policies']['children']}. Smoking: {h['policies']['smoking']}. Cancellation: {h['policies']['cancellation']}. Payment: {h['policies']['payment']}."})

        dining = h.get("dining", {})
        restaurant = dining.get("restaurant", {})
        corpus_entries.append({"source": "hotel_data.py", "text": f"Restaurant: {restaurant.get('name', 'Adora Pop Up Restaurant')}. {restaurant.get('description', '')} Hours: Lunch {restaurant.get('hours', {}).get('lunch', 'Tue-Sun')}, Dinner {restaurant.get('hours', {}).get('dinner', 'Tue-Sun')}, Brunch {restaurant.get('hours', {}).get('brunch', 'Thu-Sat')}. Phone: {restaurant.get('phone', '+386 40 558 158')}. Email: {restaurant.get('email', 'evita.vilebled@gmail.com')}"})

        corpus_entries.append({"source": "hotel_data.py", "text": f"Bar: {dining.get('bar', 'Cocktails and aperitivos on terrace')}"})
        corpus_entries.append({"source": "hotel_data.py", "text": f"Breakfast: {dining.get('breakfast', {}).get('description', 'Served 8-10 AM, €22/person')}. Dietary options: Vegan, vegetarian, gluten-free available on request."})

        for exp in h.get("experiences", []):
            corpus_entries.append({"source": "hotel_data.py", "text": f"Activity: {exp}"})

    except Exception as e:
        print(f"Error loading hotel_data: {e}")

    # Load knowledge_base.md
    kb_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base.md")
    if os.path.exists(kb_path):
        with open(kb_path, "r") as f:
            kb_content = f.read()
        # Split into chunks
        sections = kb_content.split("\n\n")
        for section in sections:
            section = section.strip()
            if section and len(section) > 30:
                corpus_entries.append({"source": "knowledge_base.md", "text": section[:500]})

    with open(CORPUS_PATH, "w") as f:
        for entry in corpus_entries:
            f.write(json.dumps(entry) + "\n")

    print(f"Built corpus with {len(corpus_entries)} entries")
    return Path(CORPUS_PATH)
