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


class _FakeReranker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], int]] = []

    def rerank(self, *, query: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
        self.calls.append((query, [hit.chunk_id or hit.document_id for hit in hits], top_k))
        return list(reversed(hits[:top_k]))


class _TextSortingReranker:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def rerank(self, *, query: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
        self.calls.append([hit.chunk_id or hit.document_id for hit in hits])
        return sorted(hits, key=lambda hit: hit.text)[:top_k]


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


def test_parent_expansion_replaces_text_but_keeps_leaf_identity() -> None:
    """E1: expansion swaps in parent TEXT only — citation chunk_id and the
    leaf's locator fields (heading path, pages) stay leaf-precise."""
    lexical = _FakeLexicalRetriever(
        [
            RetrievalHit(
                document_id="doc-1",
                chunk_id="child-1",
                score=1.0,
                text="leaf text",
                page_start=2,
                page_end=2,
                heading_path=["Section A", "Leaf heading"],
            )
        ]
    )
    vector = _FakeVectorRetriever(dense_hits=[], sparse_hits=[])
    search_sources = _FakeSearchSourcesRepository(
        {
            "child-1": {
                "chunk_id": "parent-1",
                "document_id": "doc-1",
                "text": "parent context before. leaf text. parent context after.",
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

    assert len(results) == 1
    hit = results[0]
    assert hit.chunk_id == "child-1"
    assert hit.text == "parent context before. leaf text. parent context after."
    assert hit.heading_path == ["Section A", "Leaf heading"]
    assert hit.page_start == 2
    assert hit.page_end == 2
    assert search_sources.calls == [["child-1"]]


def test_hybrid_retriever_invokes_reranker_for_non_exact_query() -> None:
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
    reranker = _FakeReranker()
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=vector,
        query_embedder=_FakeQueryEmbedder({"dense": [0.1], "sparse": {"indices": [], "values": []}}),
        reranker=reranker,
    )

    results = retriever.search(
        RetrievalQuery(
            query="hybrid query",
            tenant_id="tenant-1",
            allowed_document_ids=["doc-1"],
            top_k=3,
        )
    )

    assert reranker.calls == [("hybrid query", ["chunk-b", "chunk-a", "chunk-c"], 3)]
    assert [hit.chunk_id for hit in results] == ["chunk-c", "chunk-a", "chunk-b"]


def test_reranker_scores_leaf_texts_and_expansion_applies_after_rerank() -> None:
    """E1: the reranker must see precise LEAF texts (a whole-document parent
    blob would defeat cross-encoder precision and its max_length window);
    parent text replaces leaf text only after ranking."""
    lexical = _FakeLexicalRetriever(
        [
            RetrievalHit(document_id="doc-1", chunk_id="child-1", score=1.0, text="zulu leaf"),
            RetrievalHit(document_id="doc-1", chunk_id="child-2", score=0.9, text="alpha leaf"),
        ]
    )
    vector = _FakeVectorRetriever(dense_hits=[], sparse_hits=[])
    search_sources = _FakeSearchSourcesRepository(
        {
            "child-1": {
                "chunk_id": "parent-1",
                "document_id": "doc-1",
                "text": "zulu leaf with surrounding parent context",
                "heading_path": ["Section Z"],
                "page_start": 10,
                "page_end": 11,
            },
            "child-2": {
                "chunk_id": "parent-2",
                "document_id": "doc-1",
                "text": "alpha leaf with surrounding parent context",
                "heading_path": ["Section A"],
                "page_start": 2,
                "page_end": 3,
            },
        }
    )
    reranker = _TextSortingReranker()
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=vector,
        query_embedder=_FakeQueryEmbedder({"dense": [0.1], "sparse": {"indices": [], "values": []}}),
        search_sources_repository=search_sources,
        reranker=reranker,
    )

    results = retriever.search(
        RetrievalQuery(
            query="summarize section",
            tenant_id="tenant-1",
            allowed_document_ids=["doc-1"],
            top_k=2,
        )
    )

    # reranker received the LEAF candidates (sorted them by leaf text)
    assert reranker.calls == [["child-1", "child-2"]]
    assert [hit.chunk_id for hit in results] == ["child-2", "child-1"]
    assert [hit.text for hit in results] == [
        "alpha leaf with surrounding parent context",
        "zulu leaf with surrounding parent context",
    ]


def test_parent_expansion_dedupes_shared_parent_and_backfills_to_top_k() -> None:
    lexical = _FakeLexicalRetriever(
        [
            RetrievalHit(document_id="doc-1", chunk_id="child-1", score=1.0, text="first leaf"),
            RetrievalHit(document_id="doc-1", chunk_id="child-2", score=0.9, text="second leaf"),
            RetrievalHit(document_id="doc-1", chunk_id="child-3", score=0.8, text="third leaf"),
        ]
    )
    vector = _FakeVectorRetriever(dense_hits=[], sparse_hits=[])
    shared_parent = {
        "chunk_id": "parent-1",
        "document_id": "doc-1",
        "text": "first leaf and second leaf together in one parent",
        "heading_path": [],
        "page_start": 1,
        "page_end": 2,
    }
    search_sources = _FakeSearchSourcesRepository(
        {
            "child-1": shared_parent,
            "child-2": shared_parent,
            "child-3": {
                "chunk_id": "parent-2",
                "document_id": "doc-1",
                "text": "third leaf inside its own parent",
                "heading_path": [],
                "page_start": 3,
                "page_end": 3,
            },
        }
    )
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=vector,
        query_embedder=_FakeQueryEmbedder({"dense": [0.1], "sparse": {"indices": [], "values": []}}),
        search_sources_repository=search_sources,
        rerank_candidate_limit=10,
    )

    results = retriever.search(
        RetrievalQuery(
            query="three leaves",
            tenant_id="tenant-1",
            allowed_document_ids=["doc-1"],
            top_k=2,
        )
    )

    # child-2 collapses into child-1's parent; child-3 backfills the slot.
    assert [hit.chunk_id for hit in results] == ["child-1", "child-3"]
    assert results[0].text == "first leaf and second leaf together in one parent"
    assert results[1].text == "third leaf inside its own parent"


def test_parent_expansion_dedupes_directly_retrieved_parent_chunk() -> None:
    """Parents are indexed too — a raw parent hit duplicating an expanded
    leaf's content must collapse into one result."""
    lexical = _FakeLexicalRetriever(
        [
            RetrievalHit(document_id="doc-1", chunk_id="child-1", score=1.0, text="the leaf"),
            RetrievalHit(
                document_id="doc-1",
                chunk_id="parent-1",
                score=0.9,
                text="the leaf with its parent context",
            ),
        ]
    )
    vector = _FakeVectorRetriever(dense_hits=[], sparse_hits=[])
    search_sources = _FakeSearchSourcesRepository(
        {
            "child-1": {
                "chunk_id": "parent-1",
                "document_id": "doc-1",
                "text": "the leaf with its parent context",
                "heading_path": [],
                "page_start": 1,
                "page_end": 2,
            }
        }
    )
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=vector,
        query_embedder=_FakeQueryEmbedder({"dense": [0.1], "sparse": {"indices": [], "values": []}}),
        search_sources_repository=search_sources,
        rerank_candidate_limit=10,
    )

    results = retriever.search(
        RetrievalQuery(
            query="the leaf",
            tenant_id="tenant-1",
            allowed_document_ids=["doc-1"],
            top_k=2,
        )
    )

    assert [hit.chunk_id for hit in results] == ["child-1"]
    assert results[0].text == "the leaf with its parent context"


def test_parent_expansion_keeps_distinct_windows_of_shared_whole_doc_parent() -> None:
    """E1 eval-gate regression (recall@10 1.0 -> 0.9): under the loose
    profile the parent is the WHOLE document, so dedupe keyed on parent id
    collapsed every leaf of a document into one hit and lost distinct
    evidence spans. Far-apart leaves must both survive with their own
    capped windows; only content containment dedupes."""
    leaf_one = "FIRST DISTINCT EVIDENCE SPAN."
    leaf_two = "SECOND DISTINCT EVIDENCE SPAN."
    whole_doc_parent = leaf_one + ("x" * 500) + leaf_two
    lexical = _FakeLexicalRetriever(
        [
            RetrievalHit(document_id="doc-1", chunk_id="child-1", score=1.0, text=leaf_one),
            RetrievalHit(document_id="doc-1", chunk_id="child-2", score=0.9, text=leaf_two),
        ]
    )
    vector = _FakeVectorRetriever(dense_hits=[], sparse_hits=[])
    parent_payload = {
        "chunk_id": "parent-1",
        "document_id": "doc-1",
        "text": whole_doc_parent,
        "heading_path": [],
        "page_start": 1,
        "page_end": 9,
    }
    search_sources = _FakeSearchSourcesRepository(
        {"child-1": parent_payload, "child-2": parent_payload}
    )
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=vector,
        query_embedder=_FakeQueryEmbedder({"dense": [0.1], "sparse": {"indices": [], "values": []}}),
        search_sources_repository=search_sources,
        rerank_candidate_limit=10,
        parent_expansion_max_characters=120,
    )

    results = retriever.search(
        RetrievalQuery(
            query="both spans",
            tenant_id="tenant-1",
            allowed_document_ids=["doc-1"],
            top_k=2,
        )
    )

    assert [hit.chunk_id for hit in results] == ["child-1", "child-2"]
    assert leaf_one in results[0].text
    assert leaf_two in results[1].text
    assert len(results[0].text) <= 120
    assert len(results[1].text) <= 120


def test_parent_expansion_caps_expanded_text_in_window_around_leaf() -> None:
    prefix = "p" * 100
    leaf_text = "NEEDLE FACT SENTENCE."
    suffix = "s" * 100
    lexical = _FakeLexicalRetriever(
        [RetrievalHit(document_id="doc-1", chunk_id="child-1", score=1.0, text=leaf_text)]
    )
    vector = _FakeVectorRetriever(dense_hits=[], sparse_hits=[])
    search_sources = _FakeSearchSourcesRepository(
        {
            "child-1": {
                "chunk_id": "parent-1",
                "document_id": "doc-1",
                "text": prefix + leaf_text + suffix,
                "heading_path": [],
                "page_start": 1,
                "page_end": 4,
            }
        }
    )
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=vector,
        query_embedder=_FakeQueryEmbedder({"dense": [0.1], "sparse": {"indices": [], "values": []}}),
        search_sources_repository=search_sources,
        parent_expansion_max_characters=61,
    )

    results = retriever.search(
        RetrievalQuery(
            query="needle",
            tenant_id="tenant-1",
            allowed_document_ids=["doc-1"],
            top_k=1,
        )
    )

    assert len(results) == 1
    assert len(results[0].text) == 61
    assert leaf_text in results[0].text
    # window is centered: both sides of the leaf carry context
    assert results[0].text[0] == "p" and results[0].text[-1] == "s"


def test_parent_expansion_falls_back_to_leaf_when_parent_lost_the_leaf() -> None:
    """The chunker truncates parents at PARENT_MAX_CHARS — a leaf beyond the
    cut is absent from the parent text. Expansion must never swap evidence
    for a text that does not contain it."""
    lexical = _FakeLexicalRetriever(
        [RetrievalHit(document_id="doc-1", chunk_id="child-1", score=1.0, text="the precise evidence")]
    )
    vector = _FakeVectorRetriever(dense_hits=[], sparse_hits=[])
    search_sources = _FakeSearchSourcesRepository(
        {
            "child-1": {
                "chunk_id": "parent-1",
                "document_id": "doc-1",
                "text": "truncated parent text that no longer contains it",
                "heading_path": [],
                "page_start": 1,
                "page_end": 2,
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
            query="evidence",
            tenant_id="tenant-1",
            allowed_document_ids=["doc-1"],
            top_k=1,
        )
    )

    assert [hit.text for hit in results] == ["the precise evidence"]
    assert [hit.chunk_id for hit in results] == ["child-1"]


def test_parent_expansion_disabled_flag_skips_repository_entirely() -> None:
    lexical = _FakeLexicalRetriever(
        [RetrievalHit(document_id="doc-1", chunk_id="child-1", score=1.0, text="leaf text")]
    )
    vector = _FakeVectorRetriever(dense_hits=[], sparse_hits=[])
    search_sources = _FakeSearchSourcesRepository(
        {
            "child-1": {
                "chunk_id": "parent-1",
                "document_id": "doc-1",
                "text": "leaf text in parent",
                "heading_path": [],
                "page_start": 1,
                "page_end": 2,
            }
        }
    )
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=vector,
        query_embedder=_FakeQueryEmbedder({"dense": [0.1], "sparse": {"indices": [], "values": []}}),
        search_sources_repository=search_sources,
        parent_expansion_enabled=False,
    )

    results = retriever.search(
        RetrievalQuery(
            query="leaf",
            tenant_id="tenant-1",
            allowed_document_ids=["doc-1"],
            top_k=1,
        )
    )

    assert search_sources.calls == []
    assert [hit.text for hit in results] == ["leaf text"]
    assert [hit.chunk_id for hit in results] == ["child-1"]


def test_hybrid_retriever_bypasses_reranker_for_exact_query() -> None:
    lexical = _FakeLexicalRetriever(
        [
            RetrievalHit(document_id="doc-1", chunk_id="chunk-1", score=9.0, text="exact hit"),
        ]
    )
    vector = _FakeVectorRetriever(dense_hits=[], sparse_hits=[])
    reranker = _FakeReranker()
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=vector,
        query_embedder=_FakeQueryEmbedder({"dense": [0.1], "sparse": {"indices": [], "values": []}}),
        reranker=reranker,
    )

    results = retriever.search(
        RetrievalQuery(
            query='"needle phrase"',
            tenant_id="tenant-1",
            allowed_document_ids=["doc-1"],
            top_k=3,
        )
    )

    assert [hit.route for hit in results] == ["exact"]
    assert reranker.calls == []


def test_hybrid_retriever_bypasses_reranker_for_identifier_style_exact_query() -> None:
    lexical = _FakeLexicalRetriever(
        [
            RetrievalHit(document_id="doc-1", chunk_id="chunk-1", score=9.0, text="identifier hit"),
        ]
    )
    vector = _FakeVectorRetriever(dense_hits=[], sparse_hits=[])
    reranker = _FakeReranker()
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=vector,
        query_embedder=_FakeQueryEmbedder({"dense": [0.1], "sparse": {"indices": [], "values": []}}),
        reranker=reranker,
    )

    results = retriever.search(
        RetrievalQuery(
            query="RFC-9110",
            tenant_id="tenant-1",
            allowed_document_ids=["doc-1"],
            top_k=3,
        )
    )

    assert [hit.route for hit in results] == ["exact"]
    assert vector.dense_calls == []
    assert vector.sparse_calls == []
    assert reranker.calls == []
