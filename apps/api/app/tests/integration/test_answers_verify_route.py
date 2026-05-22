from __future__ import annotations

from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.config import Settings
from app.core.request_context import RequestContext
from app.core.security import get_request_context
from app.main import create_app


class _VerifyRetrieverStub:
    """Returns a hit whose text contains the answer sentence."""

    def search(self, query) -> list[dict]:
        return [
            {
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "score": 0.9,
                "text": "Alpha evidence proves the answer.",
                "page_start": 1,
                "page_end": 1,
                "heading_path": ["Section 1"],
                "route": "semantic",
            }
        ]


def _request_context() -> RequestContext:
    return RequestContext(
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        group_ids=[],
        roles=["editor"],
        scopes=["documents:read"],
    )


def _make_app(*, settings: Settings, retriever=None):
    app = create_app(settings)
    app.dependency_overrides[get_request_context] = _request_context
    if retriever is not None:
        app.state.search_retriever = retriever
    return app


def test_answers_verify_returns_supported_when_evidence_matches(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.retrieval.search_service.list_documents_for_context",
        lambda **kwargs: [
            type("DocRow", (), {"id": "doc-1", "title": "Doc A", "source_type": "loose_document"})()
        ],
    )
    monkeypatch.setattr("app.services.retrieval.search_service.write_audit_event", lambda **kwargs: None)

    app = _make_app(
        settings=Settings(llm_backend="stub", parser_backend=""),
        retriever=_VerifyRetrieverStub(),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/answers/verify",
            json={
                "question": "What happened?",
                "answer_text": "Alpha evidence proves the answer.",
                "top_k": 3,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "supported"
    assert body["supported_sentence_count"] == 1


def test_answers_verify_returns_503_when_retriever_missing() -> None:
    app = _make_app(settings=Settings(llm_backend="stub", parser_backend=""))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/answers/verify",
            json={
                "question": "What happened?",
                "answer_text": "Something.",
                "top_k": 3,
            },
        )

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"].lower()
