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
