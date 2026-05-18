from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.schemas.embeddings import DenseVector, EmbeddingResult, SparseVector
from app.services.embedders.bge_m3 import BgeM3Embedder


@pytest.fixture
def embedder():
    """Create a BgeM3Embedder with lazy loading (model not loaded until embed() is called)."""
    return BgeM3Embedder(device="cpu", batch_size=2)


def test_bge_m3_embedder_produces_correct_count(embedder):
    """Embedding N texts should produce N EmbeddingResult objects."""
    ids = [uuid4() for _ in range(3)]
    texts = [
        "This is the first test sentence for embedding.",
        "Here is another sentence with different content.",
        "A third sentence to verify batch processing works.",
    ]
    results = embedder.embed(chunk_ids=ids, texts=texts)
    assert len(results) == 3


def test_bge_m3_embedder_dense_dimension(embedder):
    """Dense vectors should be 1024-dimensional (BGE-M3 default)."""
    chunk_id = uuid4()
    results = embedder.embed(chunk_ids=[chunk_id], texts=["Test sentence for dimension check."])
    assert len(results) == 1
    assert results[0].dense.dimension == 1024
    assert len(results[0].dense.values) == 1024


def test_bge_m3_embedder_sparse_non_empty(embedder):
    """Sparse vectors should have non-empty indices and values."""
    chunk_id = uuid4()
    results = embedder.embed(chunk_ids=[chunk_id], texts=["A meaningful sentence with real words."])
    assert len(results) == 1
    assert len(results[0].sparse.indices) > 0
    assert len(results[0].sparse.values) > 0
    assert len(results[0].sparse.indices) == len(results[0].sparse.values)


def test_bge_m3_embedder_chunk_ids_preserved(embedder):
    """Each EmbeddingResult should carry the chunk_id it was requested for."""
    ids = [uuid4() for _ in range(2)]
    texts = ["First chunk text.", "Second chunk text."]
    results = embedder.embed(chunk_ids=ids, texts=texts)
    assert results[0].chunk_id == ids[0]
    assert results[1].chunk_id == ids[1]


def test_bge_m3_embedder_deterministic(embedder):
    """Same input should produce same output (model is deterministic at eval time)."""
    chunk_id = uuid4()
    text = "Deterministic embedding test sentence."
    r1 = embedder.embed(chunk_ids=[chunk_id], texts=[text])
    r2 = embedder.embed(chunk_ids=[chunk_id], texts=[text])
    # Dense vectors should be identical
    assert r1[0].dense.values == r2[0].dense.values


def test_bge_m3_embedder_empty_input(embedder):
    """Empty input should return empty list."""
    results = embedder.embed(chunk_ids=[], texts=[])
    assert results == []
