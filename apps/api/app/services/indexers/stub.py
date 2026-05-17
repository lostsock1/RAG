from __future__ import annotations

from app.schemas.chunks import Chunk
from app.schemas.embeddings import EmbeddingResult


class StubVectorIndexer:
    """Stub vector indexer for testing. Tracks upserted count."""

    def __init__(self) -> None:
        self.upserted_count: int = 0

    def upsert(
        self,
        *,
        chunks: list[Chunk],
        embeddings: list[EmbeddingResult],
        acl_metadata: dict,
    ) -> int:
        self.upserted_count += len(chunks)
        return len(chunks)


class StubLexicalIndexer:
    """Stub lexical indexer for testing. Tracks upserted count."""

    def __init__(self) -> None:
        self.upserted_count: int = 0

    def upsert(
        self,
        *,
        chunks: list[Chunk],
        acl_metadata: dict,
    ) -> int:
        self.upserted_count += len(chunks)
        return len(chunks)
