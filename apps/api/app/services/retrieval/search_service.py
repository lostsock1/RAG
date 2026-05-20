from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
from uuid import UUID

from app.core.request_context import RequestContext
from app.repositories.audit import write_audit_event
from app.repositories.documents import list_documents_for_context
from app.schemas.search import SearchHitResponse, SearchRequest, SearchResponse
from app.services.retrieval.base import RetrievalHit, RetrievalQuery, SearchRetriever


def _normalize_hit(raw_hit: RetrievalHit | dict) -> RetrievalHit:
    if isinstance(raw_hit, RetrievalHit):
        return raw_hit
    if is_dataclass(raw_hit):
        return RetrievalHit(**asdict(raw_hit))
    return RetrievalHit(**raw_hit)


def _build_citation_id(hit: RetrievalHit) -> str | None:
    return hit.chunk_id


def _build_source_viewer_url(citation_id: str | None) -> str | None:
    if citation_id is None:
        return None
    return f'/api/v1/search/sources/{citation_id}'


class SearchService:
    def __init__(self, retriever: SearchRetriever | None = None) -> None:
        if retriever is None:
            raise RuntimeError(
                'Search retrieval is not configured yet. Configure a search retriever before using /search.'
            )
        self._retriever = retriever

    def search(self, *, context: RequestContext, payload: SearchRequest) -> SearchResponse:
        documents = list_documents_for_context(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            group_ids=context.group_ids,
        )
        document_map = {str(document.id): document for document in documents}
        allowed_document_ids = list(document_map.keys())

        query = RetrievalQuery(
            query=payload.query,
            tenant_id=context.tenant_id,
            allowed_document_ids=allowed_document_ids,
            top_k=payload.top_k,
        )
        raw_hits = self._retriever.search(query)
        normalized_hits = [_normalize_hit(hit) for hit in raw_hits]
        filtered_hits = [
            hit
            for hit in normalized_hits
            if hit.document_id in document_map
        ][: payload.top_k]

        items = []
        for hit in filtered_hits:
            citation_id = _build_citation_id(hit)
            items.append(
                SearchHitResponse(
                    document_id=hit.document_id,
                    document_title=document_map[hit.document_id].title,
                    source_type=document_map[hit.document_id].source_type,
                    chunk_id=hit.chunk_id,
                    citation_id=citation_id,
                    source_viewer_url=_build_source_viewer_url(citation_id),
                    route=hit.route,
                    score=hit.score,
                    text=hit.text,
                    page_start=hit.page_start,
                    page_end=hit.page_end,
                    heading_path=hit.heading_path,
                )
            )

        write_audit_event(
            tenant_id=UUID(context.tenant_id),
            user_id=UUID(context.user_id),
            action='search.query',
            resource_type='document',
            resource_id=None,
            details={
                'query_sha256': hashlib.sha256(payload.query.encode('utf-8')).hexdigest(),
                'query_length': len(payload.query),
                'top_k': payload.top_k,
                'allowed_document_ids': allowed_document_ids,
                'result_document_ids': [item.document_id for item in items],
                'result_count': len(items),
            },
        )

        return SearchResponse(items=items, total=len(items))
