from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from app.services.retrieval.base import RetrievalQuery
from app.services.retrieval.qdrant_retriever import QdrantRetriever


class _FakeQdrantClient:
    def __init__(self) -> None:
        self.query_points_calls: list[dict] = []

    def query_points(self, **kwargs: object) -> object:
        self.query_points_calls.append(dict(kwargs))
        return []


def test_qdrant_retriever_uses_payload_acl_filter() -> None:
    """P1-2: The retriever must use a payload-side ACL filter, not just a
    document-id list.  The filter must include tenant scoping and access
    clauses even when allowed_document_ids is empty."""
    client = _FakeQdrantClient()
    retriever = QdrantRetriever(client=client, collection_name="chunks-test")

    query = RetrievalQuery(
        query="acl filter",
        tenant_id="tenant-1",
        user_id="user-1",
        group_ids=["group-a"],
        allowed_document_ids=[],
        top_k=7,
    )

    retriever.search_dense(query, [0.1, 0.2, 0.3])

    assert len(client.query_points_calls) == 1
    call = client.query_points_calls[0]
    assert call["collection_name"] == "chunks-test"
    assert call["query"] == [0.1, 0.2, 0.3]
    assert call["using"] == "dense"
    assert call["limit"] == 7
    assert call["with_payload"] is True

    # The filter must be a proper Filter object with ACL structure
    query_filter = call["query_filter"]
    assert isinstance(query_filter, Filter)
    # must contains: tenant_clause, not_tombstoned, unexpired (numeric
    # expires_at_ts Range, A5), access_filter.
    assert query_filter.must is not None
    assert len(query_filter.must) == 4

    # First clause: tenant_id == "tenant-1"
    tenant_clause = query_filter.must[0]
    assert isinstance(tenant_clause, FieldCondition)
    assert tenant_clause.key == "tenant_id"
    assert isinstance(tenant_clause.match, MatchValue)
    assert tenant_clause.match.value == "tenant-1"


def test_qdrant_retriever_adds_narrow_filter_when_allowed_document_ids_provided() -> None:
    """P1-2: When allowed_document_ids is non-empty, it is applied as an
    additional narrow filter on top of the ACL filter (opt-in)."""
    client = _FakeQdrantClient()
    retriever = QdrantRetriever(client=client, collection_name="chunks-test")

    query = RetrievalQuery(
        query="acl filter",
        tenant_id="tenant-1",
        user_id="user-1",
        group_ids=[],
        allowed_document_ids=["doc-1", "doc-2"],
        top_k=7,
    )

    retriever.search_dense(query, [0.1, 0.2, 0.3])

    call = client.query_points_calls[0]
    query_filter = call["query_filter"]
    assert isinstance(query_filter, Filter)
    # When allowed_document_ids is set, the outer filter wraps ACL + narrow
    assert query_filter.must is not None
    assert len(query_filter.must) == 2  # [acl_filter, narrow_condition]
    narrow = query_filter.must[1]
    assert isinstance(narrow, FieldCondition)
    assert narrow.key == "document_id"
    assert isinstance(narrow.match, MatchAny)
    assert narrow.match.any == ["doc-1", "doc-2"]


def test_qdrant_retriever_uses_persisted_chunk_id_from_payload() -> None:
    document_id = "00000000-0000-0000-0000-000000000123"
    expected_chunk_id = str(uuid4())

    class _ReturningQdrantClient(_FakeQdrantClient):
        def query_points(self, **kwargs: object) -> object:
            super().query_points(**kwargs)
            return [
                SimpleNamespace(
                    score=0.77,
                    payload={
                        "document_id": document_id,
                        "chunk_id": expected_chunk_id,
                        "chunk_index": 4,
                        "text": "retrieved text",
                    },
                )
            ]

    retriever = QdrantRetriever(client=_ReturningQdrantClient(), collection_name="chunks-test")

    hits = retriever.search_dense(
        RetrievalQuery(
            query="needle",
            tenant_id="tenant-1",
            allowed_document_ids=[document_id],
            top_k=1,
        ),
        [0.1, 0.2, 0.3],
    )

    assert hits[0].chunk_id == expected_chunk_id


def test_qdrant_retriever_does_not_derive_chunk_id_when_payload_omits_it() -> None:
    document_id = "00000000-0000-0000-0000-000000000123"

    class _ReturningQdrantClient(_FakeQdrantClient):
        def query_points(self, **kwargs: object) -> object:
            super().query_points(**kwargs)
            return [
                SimpleNamespace(
                    score=0.77,
                    payload={
                        "document_id": document_id,
                        "chunk_index": 4,
                        "text": "retrieved text",
                    },
                )
            ]

    retriever = QdrantRetriever(client=_ReturningQdrantClient(), collection_name="chunks-test")

    hits = retriever.search_dense(
        RetrievalQuery(
            query="needle",
            tenant_id="tenant-1",
            allowed_document_ids=[document_id],
            top_k=1,
        ),
        [0.1, 0.2, 0.3],
    )

    assert hits[0].chunk_id is None
