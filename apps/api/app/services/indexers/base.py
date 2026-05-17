from __future__ import annotations

from typing import Protocol

from app.schemas.chunks import Chunk
from app.schemas.embeddings import EmbeddingResult


class VectorIndexer(Protocol):
    """Writes dense + sparse vectors with ACL metadata to a vector store (e.g., Qdrant)."""

    def upsert(
        self,
        *,
        chunks: list[Chunk],
        embeddings: list[EmbeddingResult],
        acl_metadata: dict,
    ) -> int:
        """Upsert chunks with embeddings. Returns count of upserted records."""
        ...


class LexicalIndexer(Protocol):
    """Writes text chunks with ACL metadata to a lexical search index (e.g., OpenSearch)."""

    def upsert(
        self,
        *,
        chunks: list[Chunk],
        acl_metadata: dict,
    ) -> int:
        """Upsert chunks for BM25/phrase search. Returns count of upserted records."""
        ...
