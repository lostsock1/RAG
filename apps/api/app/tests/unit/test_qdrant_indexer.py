from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.schemas.chunks import Chunk
from app.schemas.embeddings import DenseVector, EmbeddingResult, SparseVector
from app.services.indexers.qdrant_indexer import QdrantVectorIndexer


def _make_chunk(document_id=None, chunk_index=0, parent_id=None):
    return Chunk(
        id=uuid4(),
        document_id=document_id or uuid4(),
        unit_type="paragraph",
        heading_path=[],
        page_start=1,
        page_end=1,
        text="test chunk text for qdrant indexing",
        parent_id=parent_id,
        chunk_index=chunk_index,
    )


def _make_embedding(chunk_id):
    return EmbeddingResult(
        chunk_id=chunk_id,
        dense=DenseVector(values=[0.1] * 1024, dimension=1024),
        sparse=SparseVector(indices=[1, 5, 10], values=[0.3, 0.5, 0.2]),
    )


def test_qdrant_indexer_upserts_points():
    """QdrantVectorIndexer.upsert should not raise and should return chunk count."""
    indexer = QdrantVectorIndexer(
        collection_name="test_collection",
        host="localhost",
        port=6333,
        _in_memory=True,  # Use in-memory mode for testing
    )
    doc_id = uuid4()
    parent_id = uuid4()
    chunks = [_make_chunk(doc_id, i, parent_id) for i in range(3)]
    embeddings = [_make_embedding(uuid4()) for _ in range(3)]
    acl = {"tenant_id": str(uuid4()), "owner_user_id": str(uuid4()), "allowed_user_ids": [], "group_ids": [], "allowed_group_ids": [], "visibility": "private", "sensitivity": "internal", "sensitivity_rank": 200, "expires_at": None, "acl_policy_id": str(uuid4()), "acl_policy_version": 1, "allowed_role_ids": [], "allowed_org_unit_ids": [], "allowed_project_ids": []}

    count = indexer.upsert(chunks=chunks, embeddings=embeddings, acl_metadata=acl)
    assert count == 3


def test_qdrant_indexer_empty_upsert():
    """Upserting empty lists should return 0 without error."""
    indexer = QdrantVectorIndexer(
        collection_name="test_empty",
        host="localhost",
        port=6333,
        _in_memory=True,
    )
    count = indexer.upsert(chunks=[], embeddings=[], acl_metadata={"tenant_id": str(uuid4()), "group_ids": []})
    assert count == 0


def test_qdrant_indexer_point_structure():
    """Each upserted point should carry dense + sparse vectors and ACL payload."""
    indexer = QdrantVectorIndexer(
        collection_name="test_structure",
        host="localhost",
        port=6333,
        _in_memory=True,
    )
    doc_id = uuid4()
    parent_id = uuid4()
    chunk = _make_chunk(doc_id, 0, parent_id)
    embedding = _make_embedding(chunk.id)
    acl = {"tenant_id": str(uuid4()), "owner_user_id": str(uuid4()), "allowed_user_ids": ["user-1"], "group_ids": ["group1"], "allowed_group_ids": ["group1"], "visibility": "group", "sensitivity": "confidential", "sensitivity_rank": 300, "expires_at": None, "acl_policy_id": str(uuid4()), "acl_policy_version": 2, "allowed_role_ids": [], "allowed_org_unit_ids": [], "allowed_project_ids": []}

    indexer.upsert(chunks=[chunk], embeddings=[embedding], acl_metadata=acl)

    # Verify internal point structure
    points = indexer._last_upserted_points
    assert len(points) == 1
    p = points[0]
    assert p.payload["tenant_id"] == acl["tenant_id"]
    assert p.payload["group_ids"] == ["group1"]
    assert p.payload["allowed_group_ids"] == ["group1"]
    assert p.payload["allowed_user_ids"] == ["user-1"]
    assert p.payload["visibility"] == "group"
    assert p.payload["sensitivity"] == "confidential"
    assert p.payload["sensitivity_rank"] == 300
    assert p.payload["acl_policy_id"] == acl["acl_policy_id"]
    assert p.payload["acl_policy_version"] == 2
    assert p.payload["allowed_role_ids"] == []
    assert p.payload["document_id"] == str(doc_id)
    assert p.payload["chunk_id"] == str(embedding.chunk_id)
    assert p.payload["chunk_index"] == 0
    assert p.payload["text"] == "test chunk text for qdrant indexing"
