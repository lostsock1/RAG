from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.retrieval.base import RetrievalHit
from app.services.retrieval.reranker import StubReranker


def test_stub_reranker_preserves_input_order_and_scores() -> None:
    hits = [
        RetrievalHit(document_id="doc-1", chunk_id="chunk-a", score=1.0, text="A"),
        RetrievalHit(document_id="doc-1", chunk_id="chunk-b", score=0.5, text="B"),
    ]

    results = StubReranker().rerank(query="hello", hits=hits, top_k=2)

    assert [hit.chunk_id for hit in results] == ["chunk-a", "chunk-b"]
    assert [hit.score for hit in results] == [1.0, 0.5]
