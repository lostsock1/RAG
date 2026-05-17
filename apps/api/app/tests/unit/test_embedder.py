from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.schemas.embeddings import DenseVector, SparseVector, EmbeddingResult
from app.services.embedders.base import Embedder
from app.services.embedders.stub import StubEmbedder


def test_dense_vector_schema():
    dv = DenseVector(values=[0.1, 0.2, 0.3], dimension=3)
    assert dv.dimension == 3
    assert len(dv.values) == 3


def test_sparse_vector_schema():
    sv = SparseVector(indices=[0, 5, 10], values=[0.5, 0.3, 0.2])
    assert len(sv.indices) == 3


def test_embedding_result_schema():
    result = EmbeddingResult(
        chunk_id=uuid4(),
        dense=DenseVector(values=[0.1, 0.2], dimension=2),
        sparse=SparseVector(indices=[0, 1], values=[0.5, 0.5]),
    )
    assert result.dense.dimension == 2
    assert result.sparse.indices == [0, 1]


def test_stub_embedder_returns_results():
    chunk_ids = [uuid4(), uuid4()]
    texts = ["hello world", "foo bar"]
    embedder = StubEmbedder(dimension=8)
    results = embedder.embed(chunk_ids=chunk_ids, texts=texts)
    assert len(results) == 2
    assert results[0].dense.dimension == 8
    assert results[0].chunk_id == chunk_ids[0]


def test_stub_embedder_deterministic():
    """Same input produces same output."""
    chunk_ids = [uuid4()]
    texts = ["test"]
    embedder = StubEmbedder(dimension=4)
    r1 = embedder.embed(chunk_ids=chunk_ids, texts=texts)
    r2 = embedder.embed(chunk_ids=chunk_ids, texts=texts)
    assert r1[0].dense.values == r2[0].dense.values


def test_stub_embedder_empty_input():
    embedder = StubEmbedder(dimension=4)
    results = embedder.embed(chunk_ids=[], texts=[])
    assert results == []


def test_embedder_protocol_exists():
    assert hasattr(Embedder, "embed")
