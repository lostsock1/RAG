from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: str
    document_id: str
    document_title: str
    chunk_id: str
    source_viewer_url: str
    page_start: int | None = None
    page_end: int | None = None
    heading_path: list[str] = []


class ResolveCitationsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citations: list[str]


class ResolveCitationsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[Citation]
