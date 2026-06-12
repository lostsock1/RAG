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
    # ADR-0020: situating context (breadcrumb or LLM-generated) prepended to
    # ``text`` for the *searchable* representation only. None => no augmentation.
    context_prefix: str | None = None

    @property
    def search_text(self) -> str:
        """Text used for embedding and BM25 indexing.

        Equals ``context_prefix + "\\n" + text`` when augmentation is present,
        else ``text`` verbatim — so the disabled path is byte-identical to the
        unaugmented pipeline. ``text`` always stays the display/citation text.
        """
        if self.context_prefix:
            return f"{self.context_prefix}\n{self.text}"
        return self.text
