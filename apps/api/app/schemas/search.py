from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)

    @field_validator('query')
    @classmethod
    def reject_whitespace_only(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('Query must not be blank or whitespace-only.')
        return v


class SearchHitResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    document_id: str
    document_title: str
    source_type: str
    chunk_id: str | None = None
    citation_id: str | None = None
    source_viewer_url: str | None = None
    route: str
    score: float
    text: str
    page_start: int | None = None
    page_end: int | None = None
    heading_path: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    items: list[SearchHitResponse] = Field(default_factory=list)
    total: int


class SearchSourceChunkResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    chunk_id: str
    text: str
    page_start: int | None = None
    page_end: int | None = None
    heading_path: list[str] = Field(default_factory=list)
    is_focus: bool = False


class SearchSourceResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    citation_id: str
    document_id: str
    document_title: str
    source_type: str
    focus_chunk_id: str
    parent_chunk_id: str | None = None
    items: list[SearchSourceChunkResponse] = Field(default_factory=list)
