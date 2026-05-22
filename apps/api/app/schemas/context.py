from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.services.retrieval.base import RetrievalHit


class BuildContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    hits: list[RetrievalHit] = Field(default_factory=list)
    document_titles: dict[str, str] = Field(default_factory=dict)
    max_characters: int = Field(ge=1)
    max_blocks: int | None = Field(default=None, ge=1)


class ContextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    document_title: str
    chunk_id: str | None = None
    citation_id: str | None = None
    text: str
    heading_path: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    rank: int


class ContextPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocks: list[ContextBlock] = Field(default_factory=list)
    block_count: int
    total_characters: int
    truncated: bool = False
