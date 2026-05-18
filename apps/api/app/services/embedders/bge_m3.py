from __future__ import annotations

import hashlib
import logging
from uuid import UUID

import numpy as np

from app.schemas.embeddings import DenseVector, EmbeddingResult, SparseVector
from app.services.embedders.base import Embedder

logger = logging.getLogger(__name__)

# Stable integer for sparse token hashing (int64 range)
_INT64_MAX = 2**63 - 1


def _token_to_index(token: str) -> int:
    """Deterministic token string → int64 index via truncated SHA-256."""
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return int(digest[:15], 16)  # 60 bits, fits in int64


class BgeM3Embedder:
    """Real BGE-M3 embedder using FlagEmbedding.

    Model is lazily loaded on first ``embed()`` call so that importing
    this module does not trigger a multi-GB download at startup.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        device: str = "cpu",
        batch_size: int = 12,
        max_length: int = 512,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._batch_size = batch_size
        self._max_length = max_length
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel

            logger.info("Loading BGE-M3 model %s on %s ...", self._model_name, self._device)
            self._model = BGEM3FlagModel(self._model_name, use_fp16=False)
            logger.info("BGE-M3 model loaded.")

    def embed(
        self,
        *,
        chunk_ids: list[UUID],
        texts: list[str],
    ) -> list[EmbeddingResult]:
        if not texts:
            return []

        self._ensure_model()

        output = self._model.encode(
            texts,
            batch_size=self._batch_size,
            max_length=self._max_length,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )

        dense_vecs: np.ndarray = output["dense_vecs"]  # shape (n, 1024)
        lexical_weights: list[dict[str, float]] = output["lexical_weights"]

        # L2-normalize dense vectors for cosine similarity
        norms = np.linalg.norm(dense_vecs, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        dense_vecs = dense_vecs / norms

        results: list[EmbeddingResult] = []
        for i, (chunk_id, token_weights) in enumerate(zip(chunk_ids, lexical_weights)):
            dense = DenseVector(
                values=dense_vecs[i].tolist(),
                dimension=dense_vecs.shape[1],
            )

            # Convert token→weight dict to sorted (index, value) pairs
            sparse_pairs = sorted(
                ((_token_to_index(tok), float(w)) for tok, w in token_weights.items()),
                key=lambda p: p[0],
            )
            sparse = SparseVector(
                indices=[p[0] for p in sparse_pairs],
                values=[p[1] for p in sparse_pairs],
            )

            results.append(EmbeddingResult(chunk_id=chunk_id, dense=dense, sparse=sparse))

        return results
