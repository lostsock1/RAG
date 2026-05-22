from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.retrieval.base import RetrievalHit
from app.services.retrieval.bge_reranker import BgeRerankerV2M3


class _FakeCrossEncoder:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    def compute_score(self, pairs, batch_size: int = 8, max_length: int = 512):
        assert pairs == [("q", "A"), ("q", "B"), ("q", "C")]
        assert batch_size == 8
        assert max_length == 512
        return [0.2, 0.9, 0.4]


def test_bge_reranker_sorts_hits_by_model_score(monkeypatch) -> None:
    monkeypatch.setattr("app.services.retrieval.bge_reranker.FlagReranker", _FakeCrossEncoder)
    reranker = BgeRerankerV2M3(model_name="fake", batch_size=8)
    hits = [
        RetrievalHit(document_id="doc-1", chunk_id="chunk-a", score=1.0, text="A"),
        RetrievalHit(document_id="doc-1", chunk_id="chunk-b", score=0.9, text="B"),
        RetrievalHit(document_id="doc-1", chunk_id="chunk-c", score=0.8, text="C"),
    ]

    results = reranker.rerank(query="q", hits=hits, top_k=2)

    assert [hit.chunk_id for hit in results] == ["chunk-b", "chunk-c"]
    assert [hit.score for hit in results] == [0.9, 0.4]
