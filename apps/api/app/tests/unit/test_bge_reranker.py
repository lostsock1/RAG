"""Tests for BgeRerankerV2M3 (ADR-0014 model) on plain transformers.

Default-suite tests inject deterministic fakes so the ~2.2 GB weights are
never loaded here; real-model behavior is covered by the on-demand eval arm
(tests/eval/test_retrieval_reranker_arm.py).

The plain-transformers implementation is load-bearing: FlagEmbedding 1.4.0's
reranker calls ``tokenizer.prepare_for_model``, which transformers 5.x
removed for slow tokenizers — that path crashes on first rerank under the
pinned stack (2026-06-11 finding).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch", reason="ML stack not installed")

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.retrieval.base import RetrievalHit
from app.services.retrieval.bge_reranker import BgeRerankerV2M3


class _FakeTokenizer:
    def __init__(self) -> None:
        self.calls: list[tuple[list, dict]] = []

    def __call__(self, pairs, **kwargs):
        self.calls.append((list(pairs), kwargs))
        n = len(pairs)
        return {
            "input_ids": torch.ones((n, 4), dtype=torch.long),
            "attention_mask": torch.ones((n, 4), dtype=torch.long),
        }


class _FakeModel:
    """Returns the next ``n`` queued scores as a logits tensor of shape
    (n, 1) — the shape the real single-label sequence-classification head
    produces for relevance scoring."""

    def __init__(self, score_queue: list[float]) -> None:
        self._queue = list(score_queue)
        self.batch_sizes: list[int] = []

    def __call__(self, *, input_ids, attention_mask):
        n = int(input_ids.size(0))
        self.batch_sizes.append(n)
        batch, self._queue = self._queue[:n], self._queue[n:]
        return SimpleNamespace(logits=torch.tensor(batch, dtype=torch.float32).reshape(n, 1))


def _hits(texts: list[str]) -> list[RetrievalHit]:
    return [
        RetrievalHit(
            document_id="doc-1",
            chunk_id=f"chunk-{text.lower()}",
            score=1.0 - index * 0.1,
            text=text,
        )
        for index, text in enumerate(texts)
    ]


def _rigged(scores: list[float], **kwargs) -> tuple[BgeRerankerV2M3, _FakeTokenizer, _FakeModel]:
    reranker = BgeRerankerV2M3(model_name="fake", **kwargs)
    tokenizer = _FakeTokenizer()
    model = _FakeModel(scores)
    reranker._tokenizer = tokenizer
    reranker._model = model
    return reranker, tokenizer, model


def test_bge_reranker_sorts_hits_by_model_score() -> None:
    reranker, tokenizer, _ = _rigged([0.2, 0.9, 0.4])

    results = reranker.rerank(query="q", hits=_hits(["A", "B", "C"]), top_k=2)

    assert [hit.chunk_id for hit in results] == ["chunk-b", "chunk-c"]
    assert [hit.score for hit in results] == pytest.approx([0.9, 0.4])
    assert tokenizer.calls[0][0] == [("q", "A"), ("q", "B"), ("q", "C")]


def test_bge_reranker_tokenizes_with_model_card_recipe() -> None:
    reranker, tokenizer, _ = _rigged([0.1, 0.2], max_length=512)

    reranker.rerank(query="q", hits=_hits(["A", "B"]), top_k=2)

    _, kwargs = tokenizer.calls[0]
    assert kwargs == {
        "padding": True,
        "truncation": True,
        "max_length": 512,
        "return_tensors": "pt",
    }


def test_bge_reranker_batches_pairs_by_batch_size() -> None:
    reranker, _, model = _rigged([0.1, 0.2, 0.3, 0.4, 0.5], batch_size=2)

    results = reranker.rerank(query="q", hits=_hits(["A", "B", "C", "D", "E"]), top_k=5)

    assert model.batch_sizes == [2, 2, 1]
    assert [hit.chunk_id for hit in results] == [
        "chunk-e",
        "chunk-d",
        "chunk-c",
        "chunk-b",
        "chunk-a",
    ]


def test_bge_reranker_empty_hits_short_circuits() -> None:
    reranker = BgeRerankerV2M3(model_name="fake")

    assert reranker.rerank(query="q", hits=[], top_k=5) == []
    assert reranker._model is None


def test_bge_reranker_does_not_import_flagembedding() -> None:
    """Regression guard for the 2026-06-11 finding: FlagEmbedding's reranker
    path is incompatible with transformers 5.x (``prepare_for_model`` was
    removed for slow tokenizers) — the module must not depend on it."""
    import inspect

    from app.services.retrieval import bge_reranker

    source = inspect.getsource(bge_reranker)
    assert "from FlagEmbedding" not in source
    assert "import FlagEmbedding" not in source
