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
