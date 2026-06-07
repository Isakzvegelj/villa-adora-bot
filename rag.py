import re, math, json
from collections import Counter
from pathlib import Path

_TOKEN = re.compile(r"[A-Za-z0-9_]+")


def _tokenize(text: str):
    return [t.lower() for t in _TOKEN.findall(text)]


def _chunk_text(source: str, text: str, chunk_size: int = 120, overlap: int = 40):
    words = text.split()
    if not words:
        return []
    chunks = []
    start = 0
    n = len(words)
    while start < n:
        end = min(start + chunk_size, n)
        segment = " ".join(words[start:end])
        chunks.append({"source": source, "text": segment})
        start = end - overlap
        if start >= n - 1 or end >= n:
            break
    return chunks


def build_corpus() -> Path:
    root = Path(__file__).resolve().parent
    out_path = root / "rag_corpus.jsonl"
    # Files/directories to exclude from RAG
    exclude_files = {"rag_corpus.jsonl", "speed_test.py", "test_db.py"}
    exclude_dirs = {"_vendor", "__pycache__", ".venv", ".venv424", ".pytest_cache", "tests", "openai_local_backup"}
    with out_path.open("w", encoding="utf-8") as fh:
        # Index hotel_data.py
        hotel_text = json.dumps(
            __import__("hotel_data", fromlist=["hotel_info"]).hotel_info,
            ensure_ascii=False,
            indent=2,
        )
        for chunk in _chunk_text("hotel_data.py", hotel_text):
            chunk["id"] = f"{chunk['source']}:{len(chunk['text'].split())}"
            fh.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        # Index knowledge_base.md and other markdown files
        for p in sorted(root.glob("**/*.md")):
            if p.name in exclude_files or any(d in p.parts for d in exclude_dirs):
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            if text.strip():
                for chunk in _chunk_text(str(p.relative_to(root)), text):
                    chunk["id"] = f"{chunk['source']}:{len(chunk['text'].split())}"
                    fh.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        # Index .txt files (but not test files)
        for p in sorted(root.glob("**/*.txt")):
            if p.name in exclude_files or any(d in p.parts for d in exclude_dirs):
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            if text.strip():
                for chunk in _chunk_text(str(p.relative_to(root)), text):
                    chunk["id"] = f"{chunk['source']}:{len(chunk['text'].split())}"
                    fh.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    return out_path


class TfidfIndex:
    def __init__(self):
        self.docs: list[dict] = []
        self.term_doc_freq: Counter = Counter()
        self.n_docs = 0

    def add(self, doc: dict):
        self.docs.append(doc)
        tokens = set(_tokenize(doc["text"]))
        for t in tokens:
            self.term_doc_freq[t] += 1
        self.n_docs += 1

    def query(self, q: str, top_k: int = 3):
        q_tokens = _tokenize(q)
        scores = [0.0] * self.n_docs
        for t in q_tokens:
            df = self.term_doc_freq.get(t)
            if not df:
                continue
            idf = math.log((self.n_docs + 1) / (df + 1.0)) + 1.0
            tokens = [_tokenize(d["text"]) for d in self.docs]
            for i, toks in enumerate(tokens):
                if toks:
                    tf = toks.count(t)
                    scores[i] += tf * idf
        ranked = sorted(
            ((s, d) for s, d in zip(scores, self.docs) if s > 0),
            key=lambda x: x[0],
            reverse=True,
        )
        return [d for _, d in ranked[:top_k]]


def build_index_from_corpus(corpus_path: str = "") -> TfidfIndex:
    root = Path(__file__).resolve().parent
    corpus_path = Path(corpus_path) if corpus_path else root / "rag_corpus.jsonl"
    idx = TfidfIndex()
    with corpus_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            doc = json.loads(line)
            idx.add(doc)
    return idx


def retrieve(query: str, top_k: int = 3) -> list[str]:
    idx = build_index_from_corpus()
    results = idx.query(query, top_k=top_k)
    return [doc["text"] for doc in results]
