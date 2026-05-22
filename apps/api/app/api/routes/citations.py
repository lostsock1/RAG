from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.request_context import RequestContext
from app.core.security import require_scopes
from app.repositories.audit import write_audit_event
from app.repositories.search_sources import get_source_slice_by_chunk_id
from app.schemas.citations import Citation, ResolveCitationsRequest, ResolveCitationsResponse

router = APIRouter()


@router.post("/resolve", response_model=ResolveCitationsResponse)
def resolve_citations_route(
    request: Request,
    payload: ResolveCitationsRequest,
    context: RequestContext = Depends(require_scopes(["documents:read"])),
) -> ResolveCitationsResponse:
    try:
        items: list[Citation] = []
        for citation_id in payload.citations:
            source_slice = get_source_slice_by_chunk_id(
                chunk_id=citation_id,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                group_ids=context.group_ids,
                context_window=0,
            )
            if source_slice is None:
                continue
            raw_items = source_slice.get("items", [])
            items_data = raw_items if isinstance(raw_items, list) else []
            focus_item = next(
                (item for item in items_data if isinstance(item, dict) and item.get("is_focus")),
                items_data[0] if items_data else None,
            )
            focus_dict = focus_item if isinstance(focus_item, dict) else {}
            items.append(
                Citation(
                    citation_id=citation_id,
                    document_id=str(source_slice["document_id"]),
                    document_title=str(source_slice["document_title"]),
                    chunk_id=str(source_slice["chunk_id"]),
                    source_viewer_url=f"/api/v1/search/sources/{citation_id}",
                    page_start=focus_dict.get("page_start"),
                    page_end=focus_dict.get("page_end"),
                    heading_path=[str(item) for item in focus_dict.get("heading_path", [])],
                )
            )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Citation resolution is not configured yet. Configure search source lookup before resolving citations.",
        ) from exc

    write_audit_event(
        tenant_id=cast(str, UUID(context.tenant_id)),
        user_id=cast(str, UUID(context.user_id)),
        action="citations.resolve",
        resource_type="document",
        resource_id=None,
        details={
            "requested_citation_ids": payload.citations,
            "resolved_citation_ids": [item.citation_id for item in items],
            "resolved_count": len(items),
        },
    )

    return ResolveCitationsResponse(items=items)
