from __future__ import annotations

from dataclasses import replace
import logging
from typing import Any

from app.services.retrieval.base import RetrievalHit

logger = logging.getLogger(__name__)

FlagReranker = None


class BgeRerankerV2M3:
    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        batch_size: int = 8,
        max_length: int = 512,
    ) -> None:
        self._model_name = model_name
        self._batch_size = batch_size
        self._max_length = max_length
        self._model: Any | None = None

    def _ensure_model(self) -> None:
        global FlagReranker
        if self._model is not None:
            return
        if FlagReranker is None:
            try:
                from FlagEmbedding import FlagReranker as _FlagReranker
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "Reranker initialization failed: install the 'FlagEmbedding' package to use 'bge-reranker-v2-m3'."
                ) from exc
            FlagReranker = _FlagReranker

        logger.info("Loading reranker model %s ...", self._model_name)
        self._model = FlagReranker(self._model_name, use_fp16=False)

    def rerank(self, *, query: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
        if not hits:
            return []

        self._ensure_model()
        scores = self._model.compute_score(
            [(query, hit.text) for hit in hits],
            batch_size=self._batch_size,
            max_length=self._max_length,
        )
        reranked = [replace(hit, score=float(score)) for hit, score in zip(hits, scores, strict=True)]
        reranked.sort(key=lambda hit: hit.score, reverse=True)
        return reranked[:top_k]


__all__ = ["BgeRerankerV2M3"]
