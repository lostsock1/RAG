from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.request_context import RequestContext
from app.schemas.search import SearchHitResponse, SearchRequest
from app.services.retrieval.base import RetrievalHit
from app.services.retrieval.search_service import SearchService


class RetrieverStub:
    def __init__(self, hits: list[RetrievalHit]) -> None:
        self.hits = hits

    def search(self, query) -> list[RetrievalHit]:
        return list(self.hits)


def test_search_hit_response_accepts_citation_source_and_route_metadata() -> None:
    payload = SearchHitResponse.model_validate(
        {
            "document_id": "doc-1",
            "document_title": "Doc",
            "source_type": "loose_document",
            "chunk_id": "chunk-1",
            "citation_id": "chunk-1",
            "source_viewer_url": "/api/v1/search/sources/chunk-1",
            "route": "exact",
            "score": 0.9,
            "text": "body",
            "heading_path": ["A"],
        }
    )

    assert payload.citation_id == "chunk-1"
    assert payload.source_viewer_url == "/api/v1/search/sources/chunk-1"
    assert payload.route == "exact"


def test_search_service_returns_stable_citation_and_route_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.retrieval.search_service.list_documents_for_context",
        lambda **kwargs: [type("DocRow", (), {"id": "doc-1", "title": "Doc", "source_type": "loose_document"})()],
    )
    monkeypatch.setattr("app.services.retrieval.search_service.write_audit_event", lambda **kwargs: None)

    service = SearchService(
        RetrieverStub(
            [
                RetrievalHit(
                    document_id="doc-1",
                    chunk_id="chunk-1",
                    score=0.9,
                    text="body",
                    heading_path=["A"],
                    route="exact",
                )
            ]
        )
    )

    response = service.search(
        context=RequestContext(
            tenant_id="00000000-0000-0000-0000-000000000001",
            user_id="00000000-0000-0000-0000-000000000002",
            group_ids=[],
            roles=["editor"],
            scopes=["documents:read"],
        ),
        payload=SearchRequest(query="needle", top_k=5),
    )

    assert response.total == 1
    assert response.items[0].citation_id == "chunk-1"
    assert response.items[0].source_viewer_url == "/api/v1/search/sources/chunk-1"
    assert response.items[0].route == "exact"


def test_search_service_omits_source_viewer_url_when_chunk_id_is_not_resolvable(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.retrieval.search_service.list_documents_for_context",
        lambda **kwargs: [type("DocRow", (), {"id": "doc-1", "title": "Doc", "source_type": "loose_document"})()],
    )
    monkeypatch.setattr("app.services.retrieval.search_service.write_audit_event", lambda **kwargs: None)

    service = SearchService(
        RetrieverStub(
            [
                RetrievalHit(
                    document_id="doc-1",
                    chunk_id=None,
                    score=0.9,
                    text="body",
                    heading_path=["A"],
                    route="semantic",
                )
            ]
        )
    )

    response = service.search(
        context=RequestContext(
            tenant_id="00000000-0000-0000-0000-000000000001",
            user_id="00000000-0000-0000-0000-000000000002",
            group_ids=[],
            roles=["editor"],
            scopes=["documents:read"],
        ),
        payload=SearchRequest(query="needle", top_k=5),
    )

    assert response.items[0].citation_id is None
    assert response.items[0].source_viewer_url is None
