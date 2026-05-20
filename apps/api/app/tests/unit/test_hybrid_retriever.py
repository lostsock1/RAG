from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.retrieval.base import RetrievalHit, RetrievalQuery
from app.services.retrieval.hybrid_retriever import HybridSearchRetriever
from app.services.retrieval.router import QueryRouter


class _FakeLexicalRetriever:
    def __init__(self, hits: list[RetrievalHit]) -> None:
        self._hits = hits
        self.calls: list[RetrievalQuery] = []

    def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        self.calls.append(query)
        return list(self._hits)


class _FakeVectorRetriever:
    def __init__(
        self,
        *,
        dense_hits: list[RetrievalHit],
        sparse_hits: list[RetrievalHit],
    ) -> None:
        self._dense_hits = dense_hits
        self._sparse_hits = sparse_hits
        self.dense_calls: list[RetrievalQuery] = []
        self.sparse_calls: list[RetrievalQuery] = []

    def search_dense(self, query: RetrievalQuery, embedding: object) -> list[RetrievalHit]:
        self.dense_calls.append((query, embedding))
        return list(self._dense_hits)

    def search_sparse(self, query: RetrievalQuery, embedding: object) -> list[RetrievalHit]:
        self.sparse_calls.append((query, embedding))
        return list(self._sparse_hits)


class _FakeQueryEmbedder:
    def __init__(self, embedding: object) -> None:
        self.embedding = embedding
        self.calls: list[str] = []

    def embed_query(self, query: str) -> object:
        self.calls.append(query)
        return self.embedding


class _FakeSearchSourcesRepository:
    def __init__(self, parent_by_child_id: dict[str, dict[str, object]]) -> None:
        self._parent_by_child_id = parent_by_child_id
        self.calls: list[list[str]] = []

    def get_parent_chunks_by_child_ids(self, *, child_chunk_ids: list[str]) -> dict[str, dict[str, object]]:
        self.calls.append(child_chunk_ids)
        return {
            child_chunk_id: self._parent_by_child_id[child_chunk_id]
            for child_chunk_id in child_chunk_ids
            if child_chunk_id in self._parent_by_child_id
        }


def test_hybrid_retriever_uses_exact_lane_without_dense_search_for_quoted_query() -> None:
    lexical = _FakeLexicalRetriever(
        [
            RetrievalHit(
                document_id="doc-1",
                chunk_id="chunk-1",
                score=9.0,
                text="exact hit",
            )
        ]
    )
    vector = _FakeVectorRetriever(dense_hits=[], sparse_hits=[])
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=vector,
        query_embedder=_FakeQueryEmbedder({"dense": [0.1], "sparse": {"indices": [], "values": []}}),
    )

    results = retriever.search(
        RetrievalQuery(
            query='"needle phrase"',
            tenant_id="tenant-1",
            allowed_document_ids=["doc-1"],
            top_k=5,
        )
    )

    assert [hit.route for hit in results] == ["exact"]
    assert vector.dense_calls == []
    assert vector.sparse_calls == []


def test_hybrid_retriever_combines_candidate_ids_with_rrf_for_non_exact_query() -> None:
    lexical = _FakeLexicalRetriever(
        [
            RetrievalHit(document_id="doc-1", chunk_id="chunk-a", score=1.0, text="A"),
            RetrievalHit(document_id="doc-1", chunk_id="chunk-b", score=0.8, text="B lexical"),
        ]
    )
    vector = _FakeVectorRetriever(
        dense_hits=[
            RetrievalHit(document_id="doc-1", chunk_id="chunk-b", score=0.9, text="B dense"),
            RetrievalHit(document_id="doc-1", chunk_id="chunk-c", score=0.7, text="C dense"),
        ],
        sparse_hits=[
            RetrievalHit(document_id="doc-1", chunk_id="chunk-b", score=0.95, text="B sparse")
        ],
    )
    query_embedder = _FakeQueryEmbedder(
        {"dense": [0.11, 0.22], "sparse": {"indices": [7, 9], "values": [0.5, 0.25]}}
    )
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=vector,
        query_embedder=query_embedder,
    )

    results = retriever.search(
        RetrievalQuery(
            query="hybrid query",
            tenant_id="tenant-1",
            allowed_document_ids=["doc-1"],
            top_k=3,
        )
    )

    assert [hit.chunk_id for hit in results] == ["chunk-b", "chunk-a", "chunk-c"]
    assert [hit.route for hit in results] == ["semantic", "semantic", "semantic"]
    assert query_embedder.calls == ["hybrid query"]
    assert vector.dense_calls == [
        (
            RetrievalQuery(
                query="hybrid query",
                tenant_id="tenant-1",
                allowed_document_ids=["doc-1"],
                top_k=3,
            ),
            {"dense": [0.11, 0.22], "sparse": {"indices": [7, 9], "values": [0.5, 0.25]}},
        )
    ]
    assert vector.sparse_calls == [
        (
            RetrievalQuery(
                query="hybrid query",
                tenant_id="tenant-1",
                allowed_document_ids=["doc-1"],
                top_k=3,
            ),
            {"dense": [0.11, 0.22], "sparse": {"indices": [7, 9], "values": [0.5, 0.25]}},
        )
    ]


def test_parent_expansion_fetches_parent_chunk_for_synthesis_route() -> None:
    lexical = _FakeLexicalRetriever(
        [
            RetrievalHit(
                document_id="doc-1",
                chunk_id="child-1",
                score=1.0,
                text="leaf text",
            )
        ]
    )
    vector = _FakeVectorRetriever(dense_hits=[], sparse_hits=[])
    search_sources = _FakeSearchSourcesRepository(
        {
            "child-1": {
                "chunk_id": "parent-1",
                "document_id": "doc-1",
                "text": "parent text",
                "heading_path": ["Section A"],
                "page_start": 2,
                "page_end": 3,
            }
        }
    )
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=vector,
        query_embedder=_FakeQueryEmbedder({"dense": [0.1], "sparse": {"indices": [], "values": []}}),
        search_sources_repository=search_sources,
    )

    results = retriever.search(
        RetrievalQuery(
            query="summarize section a",
            tenant_id="tenant-1",
            allowed_document_ids=["doc-1"],
            top_k=3,
        )
    )

    assert [(hit.chunk_id, hit.text, hit.heading_path) for hit in results] == [
        ("parent-1", "parent text", ["Section A"])
    ]
    assert search_sources.calls == [["child-1"]]
