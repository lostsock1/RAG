from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from app.schemas.embeddings import DenseVector, EmbeddingResult, SparseVector


class StubEmbedder:
    """Deterministic stub embedder for testing.

    Produces fixed-dimension dense vectors derived from text hash,
    and sparse vectors with a single non-zero entry.
    """

    def __init__(self, dimension: int = 8) -> None:
        self._dimension = dimension

    def embed(
        self,
        *,
        chunk_ids: list[UUID],
        texts: list[str],
    ) -> list[EmbeddingResult]:
        if not chunk_ids:
            return []

        results: list[EmbeddingResult] = []
        for chunk_id, text in zip(chunk_ids, texts):
            # Deterministic dense vector from text hash
            h = sha256(text.encode("utf-8")).digest()
            values = [(h[i % len(h)] / 255.0) for i in range(self._dimension)]
            results.append(
                EmbeddingResult(
                    chunk_id=chunk_id,
                    dense=DenseVector(values=values, dimension=self._dimension),
                    sparse=SparseVector(indices=[0], values=[1.0]),
                )
            )
        return results
