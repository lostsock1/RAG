from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.schemas.chunks import Chunk
from app.services.indexers.opensearch_indexer import OpenSearchLexicalIndexer


def _make_chunk(document_id=None, chunk_index=0, parent_id=None):
    return Chunk(
        id=uuid4(),
        document_id=document_id or uuid4(),
        unit_type="paragraph",
        heading_path=["Introduction"],
        page_start=1,
        page_end=1,
        text="This is a test paragraph for OpenSearch BM25 indexing.",
        parent_id=parent_id,
        chunk_index=chunk_index,
    )


def test_opensearch_indexer_upserts_docs():
    """OpenSearchLexicalIndexer.upsert should return chunk count."""
    indexer = OpenSearchLexicalIndexer(
        index_name="test_chunks",
        _mock=True,
    )
    doc_id = uuid4()
    parent_id = uuid4()
    chunks = [_make_chunk(doc_id, i, parent_id) for i in range(3)]
    acl = {"tenant_id": str(uuid4()), "owner_user_id": str(uuid4()), "allowed_user_ids": [], "group_ids": [], "allowed_group_ids": [], "visibility": "private", "sensitivity": "internal", "sensitivity_rank": 200, "expires_at": None, "acl_policy_id": str(uuid4()), "acl_policy_version": 1, "allowed_role_ids": [], "allowed_org_unit_ids": [], "allowed_project_ids": []}

    count = indexer.upsert(chunks=chunks, acl_metadata=acl)
    assert count == 3


def test_opensearch_indexer_empty_upsert():
    """Upserting empty list should return 0."""
    indexer = OpenSearchLexicalIndexer(index_name="test_empty", _mock=True)
    count = indexer.upsert(chunks=[], acl_metadata={"tenant_id": str(uuid4()), "group_ids": []})
    assert count == 0


def test_opensearch_indexer_doc_structure():
    """Each upserted doc should carry text, heading_path, and ACL fields."""
    indexer = OpenSearchLexicalIndexer(index_name="test_structure", _mock=True)
    doc_id = uuid4()
    chunk_id = uuid4()
    parent_id = uuid4()
    chunk = _make_chunk(doc_id, 0, parent_id)
    acl = {"tenant_id": str(uuid4()), "owner_user_id": str(uuid4()), "allowed_user_ids": ["user-1"], "group_ids": ["g1", "g2"], "allowed_group_ids": ["g1", "g2"], "visibility": "group", "sensitivity": "restricted", "sensitivity_rank": 400, "expires_at": None, "acl_policy_id": str(uuid4()), "acl_policy_version": 7, "allowed_role_ids": [], "allowed_org_unit_ids": [], "allowed_project_ids": []}

    chunk = chunk.model_copy(update={"id": chunk_id})

    indexer.upsert(chunks=[chunk], acl_metadata=acl)

    docs = indexer._last_bulk_body
    assert len(docs) == 2  # action + source per doc
    source = docs[1]  # second element is the document source
    assert source["text"] == "This is a test paragraph for OpenSearch BM25 indexing."
    assert source["heading_path"] == ["Introduction"]
    assert source["tenant_id"] == acl["tenant_id"]
    assert source["group_ids"] == ["g1", "g2"]
    assert source["allowed_group_ids"] == ["g1", "g2"]
    assert source["allowed_user_ids"] == ["user-1"]
    assert source["visibility"] == "group"
    assert source["sensitivity"] == "restricted"
    assert source["sensitivity_rank"] == 400
    assert source["acl_policy_id"] == acl["acl_policy_id"]
    assert source["acl_policy_version"] == 7
    assert source["allowed_project_ids"] == []
    assert source["document_id"] == str(doc_id)
    assert source["chunk_id"] == str(chunk_id)
    assert source["chunk_index"] == 0
