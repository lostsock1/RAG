from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.schemas.chunks import Chunk
from app.schemas.embeddings import DenseVector, EmbeddingResult, SparseVector
from app.services.indexers.base import VectorIndexer, LexicalIndexer
from app.services.indexers.stub import StubVectorIndexer, StubLexicalIndexer


def _make_chunk(document_id=None, chunk_index=0, chunk_id=None):
    return Chunk(
        id=chunk_id or uuid4(),
        document_id=document_id or uuid4(),
        unit_type="paragraph",
        heading_path=[],
        page_start=1,
        page_end=1,
        text="test chunk text",
        parent_id=None,
        chunk_index=chunk_index,
    )


def _make_embedding(chunk_id):
    return EmbeddingResult(
        chunk_id=chunk_id,
        dense=DenseVector(values=[0.1, 0.2], dimension=2),
        sparse=SparseVector(indices=[0], values=[1.0]),
    )


def test_vector_indexer_protocol_exists():
    assert hasattr(VectorIndexer, "upsert")


def test_lexical_indexer_protocol_exists():
    assert hasattr(LexicalIndexer, "upsert")


def test_stub_vector_indexer_accepts_chunks_and_embeddings():
    doc_id = uuid4()
    chunk = _make_chunk(doc_id)
    embedding = _make_embedding(chunk.id if hasattr(chunk, 'id') else uuid4())
    indexer = StubVectorIndexer()
    # Should not raise
    indexer.upsert(chunks=[chunk], embeddings=[embedding], acl_metadata={"tenant_id": str(uuid4()), "group_ids": []})


def test_stub_lexical_indexer_accepts_chunks():
    doc_id = uuid4()
    chunk = _make_chunk(doc_id)
    indexer = StubLexicalIndexer()
    indexer.upsert(chunks=[chunk], acl_metadata={"tenant_id": str(uuid4()), "group_ids": []})


def test_stub_vector_indexer_tracks_upserted_count():
    indexer = StubVectorIndexer()
    doc_id = uuid4()
    chunks = [_make_chunk(doc_id, i) for i in range(3)]
    embeddings = [_make_embedding(uuid4()) for _ in range(3)]
    indexer.upsert(chunks=chunks, embeddings=embeddings, acl_metadata={"tenant_id": str(uuid4()), "group_ids": []})
    assert indexer.upserted_count == 3


def test_stub_lexical_indexer_tracks_upserted_count():
    indexer = StubLexicalIndexer()
    doc_id = uuid4()
    chunks = [_make_chunk(doc_id, i) for i in range(3)]
    indexer.upsert(chunks=chunks, acl_metadata={"tenant_id": str(uuid4()), "group_ids": []})
    assert indexer.upserted_count == 3
