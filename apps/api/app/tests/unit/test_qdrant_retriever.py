from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.retrieval.base import RetrievalQuery
from app.services.retrieval.qdrant_retriever import QdrantRetriever


class _FakeQdrantClient:
    def __init__(self) -> None:
        self.query_points_calls: list[dict] = []

    def query_points(self, **kwargs: object) -> object:
        self.query_points_calls.append(dict(kwargs))
        return []


def test_qdrant_retriever_includes_allowed_document_filter() -> None:
    client = _FakeQdrantClient()
    retriever = QdrantRetriever(client=client, collection_name="chunks-test")

    query = RetrievalQuery(
        query="acl filter",
        tenant_id="tenant-1",
        allowed_document_ids=["doc-1", "doc-2"],
        top_k=7,
    )

    retriever.search_dense(query, [0.1, 0.2, 0.3])

    assert client.query_points_calls == [
        {
            "collection_name": "chunks-test",
            "query": [0.1, 0.2, 0.3],
            "using": "dense",
            "limit": 7,
            "query_filter": {
                "must": [
                    {
                        "key": "document_id",
                        "match": {"any": ["doc-1", "doc-2"]},
                    }
                ]
            },
            "with_payload": True,
        }
    ]


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
