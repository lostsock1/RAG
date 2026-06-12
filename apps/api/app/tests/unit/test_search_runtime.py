from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.config import Settings
from app.services.retrieval.runtime import build_search_retriever


class _FakeOpenSearchClient:
    def search(self, *, index: str, body: dict) -> dict:
        return {"hits": {"hits": []}}


class _FakeQdrantClient:
    def query_points(self, **kwargs: object) -> list[object]:
        return []


class _FakeQueryEmbedder:
    def embed_query(self, query: str) -> dict[str, object]:
        return {"dense": [0.1], "sparse": {"indices": [], "values": []}}


class _FakeReranker:
    def __init__(self, *, model_name: str, batch_size: int, max_length: int) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self.max_length = max_length


def test_search_runtime_enables_opensearch_certificate_verification_by_default(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_opensearch(**kwargs: object) -> _FakeOpenSearchClient:
        captured.update(kwargs)
        return _FakeOpenSearchClient()

    monkeypatch.setattr("app.services.retrieval.runtime.OpenSearch", _fake_opensearch)
    monkeypatch.setattr("app.services.retrieval.runtime.QdrantClient", lambda **kwargs: _FakeQdrantClient())
    monkeypatch.setattr("app.services.retrieval.runtime.BgeM3QueryEmbedder", _FakeQueryEmbedder)

    retriever = build_search_retriever(
        settings=Settings(search_backend="hybrid", opensearch_use_ssl=True),
        state=SimpleNamespace(),
    )

    assert retriever is not None
    assert captured["verify_certs"] is True
    assert "ssl_show_warn" not in captured


def test_search_runtime_allows_explicit_insecure_local_tls_override(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_opensearch(**kwargs: object) -> _FakeOpenSearchClient:
        captured.update(kwargs)
        return _FakeOpenSearchClient()

    monkeypatch.setattr("app.services.retrieval.runtime.OpenSearch", _fake_opensearch)
    monkeypatch.setattr("app.services.retrieval.runtime.QdrantClient", lambda **kwargs: _FakeQdrantClient())
    monkeypatch.setattr("app.services.retrieval.runtime.BgeM3QueryEmbedder", _FakeQueryEmbedder)

    retriever = build_search_retriever(
        settings=Settings(
            search_backend="hybrid",
            opensearch_use_ssl=True,
            opensearch_verify_certs=False,
        ),
        state=SimpleNamespace(),
    )

    assert retriever is not None
    assert captured["verify_certs"] is False
    assert captured["ssl_show_warn"] is False


def test_search_runtime_uses_stub_reranker_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr("app.services.retrieval.runtime.OpenSearch", lambda **kwargs: _FakeOpenSearchClient())
    monkeypatch.setattr("app.services.retrieval.runtime.QdrantClient", lambda **kwargs: _FakeQdrantClient())
    monkeypatch.setattr("app.services.retrieval.runtime.BgeM3QueryEmbedder", _FakeQueryEmbedder)

    retriever = build_search_retriever(
        settings=Settings(search_backend="hybrid", reranker_backend="disabled"),
        state=SimpleNamespace(),
    )

    assert retriever is not None
    assert retriever._reranker.__class__.__name__ == "StubReranker"


def test_search_runtime_builds_real_reranker_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr("app.services.retrieval.runtime.OpenSearch", lambda **kwargs: _FakeOpenSearchClient())
    monkeypatch.setattr("app.services.retrieval.runtime.QdrantClient", lambda **kwargs: _FakeQdrantClient())
    monkeypatch.setattr("app.services.retrieval.runtime.BgeM3QueryEmbedder", _FakeQueryEmbedder)
    monkeypatch.setattr("app.services.retrieval.runtime.BgeRerankerV2M3", _FakeReranker)

    retriever = build_search_retriever(
        settings=Settings(
            search_backend="hybrid",
            reranker_backend="bge-reranker-v2-m3",
            reranker_model_name="fake-model",
            reranker_batch_size=4,
            reranker_max_length=256,
        ),
        state=SimpleNamespace(),
    )

    assert retriever is not None
    assert retriever._reranker.__class__.__name__ == "_FakeReranker"
    assert retriever._reranker.model_name == "fake-model"
    assert retriever._reranker.batch_size == 4
    assert retriever._reranker.max_length == 256


def test_search_runtime_wires_parent_expansion_settings(monkeypatch) -> None:
    monkeypatch.setattr("app.services.retrieval.runtime.OpenSearch", lambda **kwargs: _FakeOpenSearchClient())
    monkeypatch.setattr("app.services.retrieval.runtime.QdrantClient", lambda **kwargs: _FakeQdrantClient())
    monkeypatch.setattr("app.services.retrieval.runtime.BgeM3QueryEmbedder", _FakeQueryEmbedder)

    default_retriever = build_search_retriever(
        settings=Settings(search_backend="hybrid"),
        state=SimpleNamespace(),
    )
    assert default_retriever is not None
    assert default_retriever._parent_expansion_enabled is True
    assert default_retriever._parent_expansion_max_characters == 2048

    disabled_retriever = build_search_retriever(
        settings=Settings(
            search_backend="hybrid",
            retrieval_parent_expansion=False,
            retrieval_parent_expansion_max_characters=512,
        ),
        state=SimpleNamespace(),
    )
    assert disabled_retriever is not None
    assert disabled_retriever._parent_expansion_enabled is False
    assert disabled_retriever._parent_expansion_max_characters == 512


def _patch_search_clients(monkeypatch) -> None:
    monkeypatch.setattr("app.services.retrieval.runtime.OpenSearch", lambda **kwargs: _FakeOpenSearchClient())
    monkeypatch.setattr("app.services.retrieval.runtime.QdrantClient", lambda **kwargs: _FakeQdrantClient())
    monkeypatch.setattr("app.services.retrieval.runtime.BgeM3QueryEmbedder", _FakeQueryEmbedder)


def test_search_runtime_query_understanding_disabled_wires_none(monkeypatch) -> None:
    """ADR-0021: disabled default leaves the retriever single-query path
    byte-identical (no understander object at all)."""
    _patch_search_clients(monkeypatch)

    retriever = build_search_retriever(
        settings=Settings(search_backend="hybrid"),
        state=SimpleNamespace(),
    )
    assert retriever is not None
    assert retriever._query_understander is None


def test_search_runtime_query_understanding_decompose_needs_no_llm(monkeypatch) -> None:
    _patch_search_clients(monkeypatch)

    retriever = build_search_retriever(
        settings=Settings(search_backend="hybrid", query_understanding="decompose"),
        state=SimpleNamespace(),
    )
    assert retriever is not None
    assert retriever._query_understander.__class__.__name__ == "HeuristicQueryDecomposer"


def test_search_runtime_query_understanding_multi_query_wires_llm_settings(monkeypatch) -> None:
    _patch_search_clients(monkeypatch)

    retriever = build_search_retriever(
        settings=Settings(
            search_backend="hybrid",
            query_understanding="multi_query",
            llm_base_url="https://ppq.example/v1",
            llm_api_key="secret",
            llm_model_name="fake-model",
            query_understanding_max_expansions=2,
            query_understanding_llm_max_output_tokens=64,
        ),
        state=SimpleNamespace(),
    )
    assert retriever is not None
    understander = retriever._query_understander
    assert understander.__class__.__name__ == "LlmMultiQueryExpander"
    assert understander._model_name == "fake-model"
    assert understander._max_expansions == 2
    assert understander._max_output_tokens == 64
    assert retriever._max_query_expansions == 2


def test_search_runtime_query_understanding_both_composes_decomposer_first(monkeypatch) -> None:
    _patch_search_clients(monkeypatch)

    retriever = build_search_retriever(
        settings=Settings(
            search_backend="hybrid",
            query_understanding="both",
            llm_base_url="https://ppq.example/v1",
            llm_api_key="secret",
        ),
        state=SimpleNamespace(),
    )
    assert retriever is not None
    understander = retriever._query_understander
    assert understander.__class__.__name__ == "CompositeQueryUnderstander"
    inner = [u.__class__.__name__ for u in understander._understanders]
    assert inner == ["HeuristicQueryDecomposer", "LlmMultiQueryExpander"]


def test_search_runtime_llm_backed_understanding_fails_truthfully_without_creds(monkeypatch) -> None:
    _patch_search_clients(monkeypatch)
    import pytest

    with pytest.raises(RuntimeError, match="requires llm_base_url"):
        build_search_retriever(
            settings=Settings(search_backend="hybrid", query_understanding="multi_query"),
            state=SimpleNamespace(),
        )

    with pytest.raises(RuntimeError, match="requires llm_api_key"):
        build_search_retriever(
            settings=Settings(
                search_backend="hybrid",
                query_understanding="both",
                llm_base_url="https://ppq.example/v1",
            ),
            state=SimpleNamespace(),
        )
