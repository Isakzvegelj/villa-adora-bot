import os
import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
CORPUS_PATH = PROJECT_DIR / "rag_corpus.jsonl"


def test_corpus_live():
    assert CORPUS_PATH.exists(), "rag_corpus.jsonl missing"
    lines = [line.strip() for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 5, f"corpus too small: {len(lines)}"
    docs = [__import__("json").loads(line) for line in lines]
    assert all("text" in doc and "source" in doc for doc in docs)


@pytest.mark.parametrize(
    "query",
    ["breakfast", "pets", "check-in", "lakeside room", "parking"],
)
def test_retriever_returns_relevant(query):
    from rag import retrieve

    results = retrieve(query=query, top_k=3)
    assert results, f"no results for query: {query}"
    text_block = " ".join(results).lower()
    expected_terms = {"breakfast", "pets", "check-in", "check in", "parking", "lake", "room"}
    assert any(term in text_block for term in expected_terms), (
        f"retrieved chunks irrelevant to query: {query}"
    )


def test_chunks_include_source_documents():
    from rag import build_corpus
    path = build_corpus()
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines
    assert any("hotel_data.py" in line for line in lines)
