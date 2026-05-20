from __future__ import annotations

from uuid import UUID

from app.services.embedders.bge_m3 import BgeM3Embedder
from app.services.retrieval.base import QueryEmbedding


class BgeM3QueryEmbedder:
    def __init__(self, *, embedder: BgeM3Embedder | None = None) -> None:
        self._embedder = embedder or BgeM3Embedder()

    def embed_query(self, query: str) -> QueryEmbedding:
        result = self._embedder.embed(
            chunk_ids=[UUID("00000000-0000-0000-0000-000000000000")],
            texts=[query],
        )[0]
        return QueryEmbedding(
            dense=result.dense.values,
            sparse_indices=result.sparse.indices,
            sparse_values=result.sparse.values,
        )
