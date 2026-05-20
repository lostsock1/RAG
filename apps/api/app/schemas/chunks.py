from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentProfile(StrEnum):
    LOOSE = "loose"
    BOOK = "book"


class Chunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    document_id: UUID
    unit_type: str
    heading_path: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    text: str
    parent_id: UUID | None = None
    chunk_index: int
