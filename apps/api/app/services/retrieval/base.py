from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True)
class RetrievalQuery:
    query: str
    tenant_id: str
    allowed_document_ids: list[str]
    top_k: int


@dataclass(slots=True)
class RetrievalHit:
    document_id: str
    chunk_id: str | None
    score: float
    text: str
    page_start: int | None = None
    page_end: int | None = None
    heading_path: list[str] = field(default_factory=list)


class SearchRetriever(Protocol):
    def search(self, query: RetrievalQuery) -> list[RetrievalHit] | list[dict]: ...


class NullSearchRetriever:
    def search(self, query: RetrievalQuery) -> list[RetrievalHit]:
        return []
