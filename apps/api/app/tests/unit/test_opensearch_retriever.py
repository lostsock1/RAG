from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.retrieval.base import RetrievalQuery
from app.services.retrieval.opensearch_retriever import OpenSearchRetriever


class _FakeOpenSearchClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def search(self, *, index: str, body: dict) -> dict:
        self.calls.append({"index": index, "body": body})
        return {"hits": {"hits": []}}


def test_opensearch_retriever_uses_payload_acl_filter() -> None:
    """P1-2: The retriever must use payload-side ACL filter clauses."""
    client = _FakeOpenSearchClient()
    retriever = OpenSearchRetriever(client=client, index_name="chunks-test")

    retriever.search(
        RetrievalQuery(
            query="acl filter",
            tenant_id="tenant-1",
            user_id="user-1",
            group_ids=["group-a"],
            allowed_document_ids=[],
            top_k=5,
        )
    )

    assert len(client.calls) == 1
    body = client.calls[0]["body"]
    query_bool = body["query"]["bool"]
    assert query_bool["must"] == [{"match": {"text": "acl filter"}}]
    # ACL filter must include tenant scoping
    filter_clauses = query_bool["filter"]
    assert isinstance(filter_clauses, list)
    assert len(filter_clauses) == 4  # tenant, tombstone, expiry, access
    assert filter_clauses[0] == {"term": {"tenant_id": "tenant-1"}}
    assert filter_clauses[1] == {"term": {"is_tombstoned": False}}


def test_opensearch_retriever_adds_narrow_filter_when_allowed_document_ids_provided() -> None:
    """P1-2: When allowed_document_ids is non-empty, it is appended as an
    additional narrow filter on top of the ACL filter."""
    client = _FakeOpenSearchClient()
    retriever = OpenSearchRetriever(client=client, index_name="chunks-test")

    retriever.search(
        RetrievalQuery(
            query="acl filter",
            tenant_id="tenant-1",
            user_id="user-1",
            group_ids=[],
            allowed_document_ids=["doc-1", "doc-2"],
            top_k=5,
        )
    )

    filter_clauses = client.calls[0]["body"]["query"]["bool"]["filter"]
    # 4 ACL clauses + 1 narrow clause
    assert len(filter_clauses) == 5
    assert filter_clauses[-1] == {"terms": {"document_id": ["doc-1", "doc-2"]}}


def test_opensearch_retriever_uses_match_phrase_for_quoted_exact_queries() -> None:
    client = _FakeOpenSearchClient()
    retriever = OpenSearchRetriever(client=client, index_name="chunks-test")

    retriever.search(
        RetrievalQuery(
            query='"needle phrase"',
            tenant_id="tenant-1",
            user_id="user-1",
            group_ids=[],
            allowed_document_ids=["doc-1"],
            top_k=2,
        )
    )

    body = client.calls[0]["body"]
    assert body["query"]["bool"]["must"] == [{"match_phrase": {"text": "needle phrase"}}]
    assert body["size"] == 2


def test_opensearch_retriever_uses_persisted_chunk_id_from_hit_payload() -> None:
    expected_chunk_id = str(uuid4())

    class _ReturningOpenSearchClient(_FakeOpenSearchClient):
        def search(self, *, index: str, body: dict) -> dict:
            super().search(index=index, body=body)
            return {
                "hits": {
                    "hits": [
                        {
                            "_score": 1.2,
                            "_source": {
                                "document_id": "doc-1",
                                "chunk_id": expected_chunk_id,
                                "chunk_index": 7,
                                "text": "retrieved text",
                            },
                        }
                    ]
                }
            }

    retriever = OpenSearchRetriever(client=_ReturningOpenSearchClient(), index_name="chunks-test")

    hits = retriever.search(
        RetrievalQuery(
            query="needle",
            tenant_id="tenant-1",
            allowed_document_ids=["doc-1"],
            top_k=1,
        )
    )

    assert hits[0].chunk_id == expected_chunk_id


def test_opensearch_retriever_does_not_derive_chunk_id_when_hit_payload_omits_it() -> None:
    class _ReturningOpenSearchClient(_FakeOpenSearchClient):
        def search(self, *, index: str, body: dict) -> dict:
            super().search(index=index, body=body)
            return {
                "hits": {
                    "hits": [
                        {
                            "_score": 1.2,
                            "_source": {
                                "document_id": "doc-1",
                                "chunk_index": 7,
                                "text": "retrieved text",
                            },
                        }
                    ]
                }
            }

    retriever = OpenSearchRetriever(client=_ReturningOpenSearchClient(), index_name="chunks-test")

    hits = retriever.search(
        RetrievalQuery(
            query="needle",
            tenant_id="tenant-1",
            allowed_document_ids=["doc-1"],
            top_k=1,
        )
    )

    assert hits[0].chunk_id is None
