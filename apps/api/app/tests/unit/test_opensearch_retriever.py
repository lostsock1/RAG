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


def test_opensearch_retriever_includes_allowed_document_filter() -> None:
    client = _FakeOpenSearchClient()
    retriever = OpenSearchRetriever(client=client, index_name="chunks-test")

    retriever.search(
        RetrievalQuery(
            query="acl filter",
            tenant_id="tenant-1",
            allowed_document_ids=["doc-1", "doc-2"],
            top_k=5,
        )
    )

    assert client.calls == [
        {
            "index": "chunks-test",
            "body": {
                "query": {
                    "bool": {
                        "must": [{"match": {"text": "acl filter"}}],
                        "filter": [{"terms": {"document_id": ["doc-1", "doc-2"]}}],
                    }
                },
                "size": 5,
            },
        }
    ]


def test_opensearch_retriever_uses_match_phrase_for_quoted_exact_queries() -> None:
    client = _FakeOpenSearchClient()
    retriever = OpenSearchRetriever(client=client, index_name="chunks-test")

    retriever.search(
        RetrievalQuery(
            query='"needle phrase"',
            tenant_id="tenant-1",
            allowed_document_ids=["doc-1"],
            top_k=2,
        )
    )

    assert client.calls == [
        {
            "index": "chunks-test",
            "body": {
                "query": {
                    "bool": {
                        "must": [{"match_phrase": {"text": "needle phrase"}}],
                        "filter": [{"terms": {"document_id": ["doc-1"]}}],
                    }
                },
                "size": 2,
            },
        }
    ]


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
