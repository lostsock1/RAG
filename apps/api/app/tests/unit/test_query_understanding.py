from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.retrieval.base import RetrievalHit, RetrievalQuery
from app.services.retrieval.hybrid_retriever import HybridSearchRetriever
from app.services.retrieval.query_understanding import (
    CompositeQueryUnderstander,
    HeuristicQueryDecomposer,
    LlmMultiQueryExpander,
    StubQueryExpander,
)
from app.services.retrieval.router import QueryRouter


# ---------------------------------------------------------------------------
# StubQueryExpander
# ---------------------------------------------------------------------------


def test_stub_expander_is_deterministic():
    expander = StubQueryExpander()
    first = expander.expand("how does entropy change")
    second = expander.expand("how does entropy change")
    assert first == second
    assert len(first) == 2
    assert all("how does entropy change" in q for q in first)


# ---------------------------------------------------------------------------
# HeuristicQueryDecomposer (ADR-0021 decompose arm — LLM-free)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query,expected",
    [
        (
            "What is the difference between mitosis and meiosis?",
            ["mitosis", "meiosis"],
        ),
        (
            "Compare aerobic respiration with anaerobic respiration",
            ["aerobic respiration", "anaerobic respiration"],
        ),
        (
            "Compare ionic bonds and covalent bonds",
            ["ionic bonds", "covalent bonds"],
        ),
        (
            "exothermic reactions versus endothermic reactions",
            ["exothermic reactions", "endothermic reactions"],
        ),
        (
            "How does osmosis work and why do cells shrink in salt water?",
            ["How does osmosis work", "why do cells shrink in salt water?"],
        ),
    ],
)
def test_decomposer_splits_multi_hop_shapes(query, expected):
    assert HeuristicQueryDecomposer().expand(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        "What is the second law of thermodynamics?",  # single-entity
        "Wie lautet der zweite Hauptsatz der Thermodynamik?",  # non-matching language shape
        "acids and bases",  # bare conjunction, no twin-question shape
        "compare",  # degenerate
    ],
)
def test_decomposer_passes_through_single_hop(query):
    assert HeuristicQueryDecomposer().expand(query) == []


def test_decomposer_drops_degenerate_fragments():
    # Sub-queries shorter than 3 chars are noise, not retrieval queries.
    assert HeuristicQueryDecomposer().expand("a vs be") == []


# ---------------------------------------------------------------------------
# LlmMultiQueryExpander (fake transport — no network)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, body: dict, error: Exception | None = None) -> None:
        self._body = body
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self) -> dict:
        return self._body


class _FakeTransport:
    def __init__(self, content: str, error: Exception | None = None) -> None:
        self.requests: list[dict] = []
        self._content = content
        self._error = error

    def post(self, url, *, headers, json, timeout):
        self.requests.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _FakeResponse(
            {"choices": [{"message": {"content": self._content}}]}, error=self._error
        )


def _expander(transport, **overrides) -> LlmMultiQueryExpander:
    kwargs = dict(
        base_url="https://fake.example/v1/",
        api_key="test-key",
        model_name="fake-model",
        transport=transport,
    )
    kwargs.update(overrides)
    return LlmMultiQueryExpander(**kwargs)


def test_llm_expander_parses_one_paraphrase_per_line():
    transport = _FakeTransport("entropy in closed systems\nsecond law statement\ndisorder over time")
    result = _expander(transport).expand("what does the second law say")
    assert result == [
        "entropy in closed systems",
        "second law statement",
        "disorder over time",
    ]
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request["url"] == "https://fake.example/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer test-key"
    assert request["json"]["model"] == "fake-model"
    assert request["json"]["temperature"] == 0.0
    assert "what does the second law say" in request["json"]["messages"][0]["content"]


def test_llm_expander_strips_numbering_and_bullets():
    transport = _FakeTransport("1. first rewrite\n- second rewrite\n* third rewrite")
    result = _expander(transport).expand("original")
    assert result == ["first rewrite", "second rewrite", "third rewrite"]


def test_llm_expander_drops_empties_and_duplicates_of_original():
    transport = _FakeTransport("ORIGINAL QUERY\n\nreal rewrite\nreal rewrite\nanother rewrite")
    result = _expander(transport).expand("original query")
    assert result == ["real rewrite", "another rewrite"]


def test_llm_expander_caps_at_max_expansions():
    transport = _FakeTransport("a rewrite\nb rewrite\nc rewrite\nd rewrite\ne rewrite")
    result = _expander(transport, max_expansions=2).expand("original")
    assert result == ["a rewrite", "b rewrite"]


def test_llm_expander_empty_content_yields_no_expansions():
    transport = _FakeTransport("   ")
    assert _expander(transport).expand("original") == []


def test_llm_expander_propagates_transport_errors():
    transport = _FakeTransport("x", error=RuntimeError("upstream 500"))
    with pytest.raises(RuntimeError, match="upstream 500"):
        _expander(transport).expand("original")


# ---------------------------------------------------------------------------
# CompositeQueryUnderstander ("both" arm)
# ---------------------------------------------------------------------------


def test_composite_unions_in_order_dedupes_and_caps():
    first = StubQueryExpander(suffixes=("alpha", "beta"))
    second = StubQueryExpander(suffixes=("alpha", "gamma", "delta"))
    composite = CompositeQueryUnderstander(understanders=[first, second], max_expansions=3)
    assert composite.expand("q") == ["q alpha", "q beta", "q gamma"]


def test_composite_excludes_rewrites_equal_to_original():
    class _Echo:
        def expand(self, query: str) -> list[str]:
            return [query.upper(), "fresh angle"]

    composite = CompositeQueryUnderstander(understanders=[_Echo()], max_expansions=3)
    assert composite.expand("Original") == ["fresh angle"]


# ---------------------------------------------------------------------------
# HybridSearchRetriever integration (route gate + fusion across queries)
# ---------------------------------------------------------------------------


def _hit(chunk_id: str, text: str | None = None) -> RetrievalHit:
    return RetrievalHit(
        document_id="doc-1", chunk_id=chunk_id, score=1.0, text=text or chunk_id
    )


class _QuerySensitiveLexical:
    """Returns hits keyed by the query string — proves which query surfaced what."""

    def __init__(self, hits_by_query: dict[str, list[RetrievalHit]]) -> None:
        self._hits_by_query = hits_by_query
        self.queries: list[str] = []

    def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        self.queries.append(query.query)
        return list(self._hits_by_query.get(query.query, []))


class _EmptyVector:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search_dense(self, query: RetrievalQuery, embedding: object) -> list[RetrievalHit]:
        self.queries.append(query.query)
        return []

    def search_sparse(self, query: RetrievalQuery, embedding: object) -> list[RetrievalHit]:
        return []


class _CountingEmbedder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed_query(self, query: str) -> object:
        self.calls.append(query)
        return {"dense": [0.1], "sparse": {"indices": [], "values": []}}


class _SpyUnderstander:
    def __init__(self, expansions: list[str]) -> None:
        self._expansions = expansions
        self.calls: list[str] = []

    def expand(self, query: str) -> list[str]:
        self.calls.append(query)
        return list(self._expansions)


def _semantic_query(text: str = "how does osmosis work") -> RetrievalQuery:
    return RetrievalQuery(
        query=text, tenant_id="t", allowed_document_ids=["doc-1"], top_k=5
    )


def test_retriever_merges_candidates_surfaced_only_by_expansions():
    lexical = _QuerySensitiveLexical(
        {
            "how does osmosis work": [_hit("chunk-original")],
            "osmosis paraphrase": [_hit("chunk-paraphrase-only")],
        }
    )
    understander = _SpyUnderstander(["osmosis paraphrase"])
    embedder = _CountingEmbedder()
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=_EmptyVector(),
        query_embedder=embedder,
        query_understander=understander,
    )

    results = retriever.search(_semantic_query())

    assert understander.calls == ["how does osmosis work"]
    assert lexical.queries == ["how does osmosis work", "osmosis paraphrase"]
    assert embedder.calls == ["how does osmosis work", "osmosis paraphrase"]
    assert {hit.chunk_id for hit in results} == {"chunk-original", "chunk-paraphrase-only"}
    # Original-query evidence outranks paraphrase-only evidence at equal ranks
    # (RRF sums; both have one list each at rank 1 — order falls back to
    # first-fused; the original query's lists are fused first).
    assert results[0].chunk_id == "chunk-original"


def test_retriever_rrf_prefers_candidates_confirmed_by_multiple_queries():
    lexical = _QuerySensitiveLexical(
        {
            "how does osmosis work": [_hit("chunk-a"), _hit("chunk-b")],
            "osmosis paraphrase": [_hit("chunk-b"), _hit("chunk-c")],
        }
    )
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=_EmptyVector(),
        query_embedder=_CountingEmbedder(),
        query_understander=_SpyUnderstander(["osmosis paraphrase"]),
    )

    results = retriever.search(_semantic_query())

    # chunk-b appears in both queries' lists -> highest RRF mass.
    assert results[0].chunk_id == "chunk-b"


def test_retriever_caps_expansions():
    lexical = _QuerySensitiveLexical({"how does osmosis work": [_hit("chunk-a")]})
    understander = _SpyUnderstander([f"extra {i}" for i in range(10)])
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=_EmptyVector(),
        query_embedder=_CountingEmbedder(),
        query_understander=understander,
        max_query_expansions=3,
    )

    retriever.search(_semantic_query())

    assert lexical.queries == [
        "how does osmosis work",
        "extra 0",
        "extra 1",
        "extra 2",
    ]


def test_retriever_dedupes_expansions_against_original_and_each_other():
    lexical = _QuerySensitiveLexical({"how does osmosis work": [_hit("chunk-a")]})
    understander = _SpyUnderstander(
        ["How Does Osmosis Work", "fresh angle", "  fresh angle  ", ""]
    )
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=_EmptyVector(),
        query_embedder=_CountingEmbedder(),
        query_understander=understander,
    )

    retriever.search(_semantic_query())

    assert lexical.queries == ["how does osmosis work", "fresh angle"]


def test_exact_route_never_invokes_understander():
    lexical = _QuerySensitiveLexical({'"needle phrase"': [_hit("chunk-exact")]})
    understander = _SpyUnderstander(["should never be used"])
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=_EmptyVector(),
        query_embedder=_CountingEmbedder(),
        query_understander=understander,
    )

    results = retriever.search(_semantic_query('"needle phrase"'))

    assert understander.calls == []
    assert [hit.route for hit in results] == ["exact"]


def test_retriever_without_understander_runs_single_query_path():
    lexical = _QuerySensitiveLexical({"how does osmosis work": [_hit("chunk-a")]})
    embedder = _CountingEmbedder()
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=_EmptyVector(),
        query_embedder=embedder,
    )

    results = retriever.search(_semantic_query())

    assert lexical.queries == ["how does osmosis work"]
    assert embedder.calls == ["how does osmosis work"]
    assert [hit.chunk_id for hit in results] == ["chunk-a"]


def test_reranker_receives_original_query_not_paraphrases():
    class _CapturingReranker:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def rerank(self, *, query: str, hits, top_k: int):
            self.queries.append(query)
            return list(hits[:top_k])

    lexical = _QuerySensitiveLexical(
        {
            "how does osmosis work": [_hit("chunk-a")],
            "osmosis paraphrase": [_hit("chunk-b")],
        }
    )
    reranker = _CapturingReranker()
    retriever = HybridSearchRetriever(
        router=QueryRouter(),
        lexical_retriever=lexical,
        vector_retriever=_EmptyVector(),
        query_embedder=_CountingEmbedder(),
        reranker=reranker,
        query_understander=_SpyUnderstander(["osmosis paraphrase"]),
    )

    retriever.search(_semantic_query())

    assert reranker.queries == ["how does osmosis work"]
