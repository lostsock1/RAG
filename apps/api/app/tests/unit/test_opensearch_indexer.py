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


class _FakeIndices:
    def exists(self, index):
        return True


class _FakeOpenSearch:
    captured: dict = {}

    def __init__(self, **kwargs):
        _FakeOpenSearch.captured = dict(kwargs)
        self.indices = _FakeIndices()


def test_opensearch_indexer_client_honors_tls_settings(monkeypatch):
    """P2-1: _ensure_client honors use_ssl/verify_certs instead of hard-coding verify_certs=False."""
    monkeypatch.setattr(
        "app.services.indexers.opensearch_indexer.OpenSearch", _FakeOpenSearch
    )

    secure = OpenSearchLexicalIndexer(index_name="tls_secure", use_ssl=True, verify_certs=True)
    secure._ensure_client()
    assert _FakeOpenSearch.captured["use_ssl"] is True
    assert _FakeOpenSearch.captured["verify_certs"] is True
    assert "ssl_show_warn" not in _FakeOpenSearch.captured

    insecure = OpenSearchLexicalIndexer(index_name="tls_insecure", verify_certs=False)
    insecure._ensure_client()
    assert _FakeOpenSearch.captured["verify_certs"] is False
    assert _FakeOpenSearch.captured["ssl_show_warn"] is False


def test_opensearch_indexer_verifies_certs_by_default(monkeypatch):
    """P2-1: secure by default — certificate verification on unless explicitly disabled."""
    monkeypatch.setattr(
        "app.services.indexers.opensearch_indexer.OpenSearch", _FakeOpenSearch
    )

    OpenSearchLexicalIndexer(index_name="tls_default")._ensure_client()
    assert _FakeOpenSearch.captured["verify_certs"] is True


def test_opensearch_indexer_augmented_chunk_splits_search_and_display_text():
    """ADR-0020: BM25 `text` carries the augmented search representation while
    `display_text` preserves the original verbatim chunk text."""
    indexer = OpenSearchLexicalIndexer(index_name="test_augmented", _mock=True)
    chunk = _make_chunk(uuid4(), 0, uuid4()).model_copy(
        update={"context_prefix": "Doc Title > Section (p. 1)"}
    )
    acl = {"tenant_id": str(uuid4()), "owner_user_id": str(uuid4()), "allowed_user_ids": [], "group_ids": [], "allowed_group_ids": [], "visibility": "private", "sensitivity": "internal", "sensitivity_rank": 200, "expires_at": None, "acl_policy_id": str(uuid4()), "acl_policy_version": 1, "allowed_role_ids": [], "allowed_org_unit_ids": [], "allowed_project_ids": []}

    indexer.upsert(chunks=[chunk], acl_metadata=acl)

    source = indexer._last_bulk_body[1]
    assert source["text"] == (
        "Doc Title > Section (p. 1)\n"
        "This is a test paragraph for OpenSearch BM25 indexing."
    )
    assert source["display_text"] == "This is a test paragraph for OpenSearch BM25 indexing."


def test_opensearch_indexer_unaugmented_chunk_text_fields_identical():
    """Disabled path: search and display text are byte-identical."""
    indexer = OpenSearchLexicalIndexer(index_name="test_unaugmented", _mock=True)
    chunk = _make_chunk(uuid4(), 0, uuid4())
    acl = {"tenant_id": str(uuid4()), "owner_user_id": str(uuid4()), "allowed_user_ids": [], "group_ids": [], "allowed_group_ids": [], "visibility": "private", "sensitivity": "internal", "sensitivity_rank": 200, "expires_at": None, "acl_policy_id": str(uuid4()), "acl_policy_version": 1, "allowed_role_ids": [], "allowed_org_unit_ids": [], "allowed_project_ids": []}

    indexer.upsert(chunks=[chunk], acl_metadata=acl)

    source = indexer._last_bulk_body[1]
    assert source["text"] == source["display_text"] == chunk.text
