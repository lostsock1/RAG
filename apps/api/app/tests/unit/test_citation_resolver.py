from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.schemas.search import SearchHitResponse
from app.services.citation_resolver import CitationResolver


def _hit(
    citation_id: str = "chunk-1",
    chunk_id: str = "chunk-1",
    document_id: str = "doc-1",
    document_title: str = "Doc A",
    source_viewer_url: str = "/api/v1/search/sources/chunk-1",
    page_start: int = 2,
    page_end: int = 2,
    heading_path: list[str] | None = None,
) -> SearchHitResponse:
    return SearchHitResponse(
        document_id=document_id,
        document_title=document_title,
        source_type="loose_document",
        chunk_id=chunk_id,
        citation_id=citation_id,
        source_viewer_url=source_viewer_url,
        route="semantic",
        score=0.9,
        text="Alpha evidence",
        page_start=page_start,
        page_end=page_end,
        heading_path=heading_path or ["A"],
    )


def test_citation_resolver_returns_resolvable_citations_in_hit_order() -> None:
    resolver = CitationResolver()
    hits = [_hit(citation_id="chunk-1"), _hit(citation_id="chunk-2", chunk_id="chunk-2", document_id="doc-2", document_title="Doc B", source_viewer_url="/api/v1/search/sources/chunk-2")]

    result = resolver.resolve(citation_ids=["chunk-1", "chunk-2"], hits=hits)

    assert [item.citation_id for item in result.items] == ["chunk-1", "chunk-2"]
    assert result.items[0].document_title == "Doc A"
    assert result.items[1].document_title == "Doc B"


def test_citation_resolver_drops_unresolvable_ids_without_emitting_broken_urls() -> None:
    resolver = CitationResolver()
    result = resolver.resolve(citation_ids=["missing"], hits=[])

    assert result.items == []


def test_citation_resolver_skips_hits_without_citation_id() -> None:
    resolver = CitationResolver()
    hits = [_hit(citation_id=None, chunk_id=None, source_viewer_url=None)]

    result = resolver.resolve(citation_ids=["chunk-1"], hits=hits)

    assert result.items == []


def test_citation_resolver_preserves_page_and_heading_metadata() -> None:
    resolver = CitationResolver()
    hits = [_hit(page_start=5, page_end=7, heading_path=["Chapter 1", "Section 2"])]

    result = resolver.resolve(citation_ids=["chunk-1"], hits=hits)

    assert result.items[0].page_start == 5
    assert result.items[0].page_end == 7
    assert result.items[0].heading_path == ["Chapter 1", "Section 2"]


def test_citation_resolver_deduplicates_by_citation_id() -> None:
    resolver = CitationResolver()
    hits = [_hit(citation_id="chunk-1"), _hit(citation_id="chunk-1")]

    result = resolver.resolve(citation_ids=["chunk-1"], hits=hits)

    assert len(result.items) == 1
