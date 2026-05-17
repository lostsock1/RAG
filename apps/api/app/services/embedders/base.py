from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.schemas.embeddings import EmbeddingResult


class Embedder(Protocol):
    def embed(
        self,
        *,
        chunk_ids: list[UUID],
        texts: list[str],
    ) -> list[EmbeddingResult]:
        """Embed a batch of texts. Returns one EmbeddingResult per input."""
        ...
