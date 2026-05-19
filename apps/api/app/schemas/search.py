from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)


class SearchHitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    document_title: str
    source_type: str
    chunk_id: str | None = None
    score: float
    text: str
    page_start: int | None = None
    page_end: int | None = None
    heading_path: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SearchHitResponse] = Field(default_factory=list)
    total: int
