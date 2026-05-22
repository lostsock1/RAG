from __future__ import annotations

from app.schemas.citations import Citation, ResolveCitationsResponse


class CitationResolver:
    """Metadata-only citation resolver.

    Maps citation IDs to stable citation objects using only
    ACL-safe retrieval hits already passed in. Never fetches
    unauthorized source text.
    """

    def resolve(
        self,
        *,
        citation_ids: list[str],
        hits: list,
    ) -> ResolveCitationsResponse:
        by_id = {
            hit.citation_id: hit
            for hit in hits
            if hit.citation_id is not None
            and hit.chunk_id is not None
            and hit.source_viewer_url is not None
        }
        items: list[Citation] = []
        for citation_id in citation_ids:
            hit = by_id.get(citation_id)
            if hit is None:
                continue
            items.append(
                Citation(
                    citation_id=citation_id,
                    document_id=hit.document_id,
                    document_title=hit.document_title,
                    chunk_id=hit.chunk_id,
                    source_viewer_url=hit.source_viewer_url,
                    page_start=hit.page_start,
                    page_end=hit.page_end,
                    heading_path=hit.heading_path,
                )
            )
        return ResolveCitationsResponse(items=items)
