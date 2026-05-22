from __future__ import annotations

from typing import Protocol

from app.services.retrieval.base import RetrievalHit


class Reranker(Protocol):
    def rerank(self, *, query: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]: ...


class StubReranker:
    def rerank(self, *, query: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
        return list(hits[:top_k])


__all__ = ["Reranker", "StubReranker"]
