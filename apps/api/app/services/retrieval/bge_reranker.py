from __future__ import annotations

from dataclasses import replace
import logging
from typing import Any

from app.services.retrieval.base import RetrievalHit

logger = logging.getLogger(__name__)


class BgeRerankerV2M3:
    """Cross-encoder reranker for ``BAAI/bge-reranker-v2-m3`` (ADR-0014).

    Implemented on plain transformers — the model is a standard XLM-RoBERTa
    sequence-classification cross-encoder, scored per the official model
    card: tokenize (query, passage) pairs padded/truncated to ``max_length``
    and read the single relevance logit per pair (raw, unnormalized — only
    the ordering is consumed). FlagEmbedding is deliberately not used here:
    its 1.4.0 reranker path calls ``tokenizer.prepare_for_model``, which
    transformers 5.x removed for slow tokenizers, so it crashes on first
    rerank under the pinned stack (2026-06-11 finding).
    """

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
        self._tokenizer: Any | None = None

    def _ensure_model(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Reranker initialization failed: install 'transformers' to use "
                "'bge-reranker-v2-m3'."
            ) from exc

        logger.info("Loading reranker model %s ...", self._model_name)
        self._tokenizer = AutoTokenizer.from_pretrained(self._model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(self._model_name)
        self._model.eval()

    def _compute_scores(self, pairs: list[tuple[str, str]]) -> list[float]:
        import torch

        assert self._tokenizer is not None and self._model is not None
        scores: list[float] = []
        for start in range(0, len(pairs), self._batch_size):
            batch = pairs[start : start + self._batch_size]
            inputs = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self._max_length,
                return_tensors="pt",
            )
            with torch.no_grad():
                logits = self._model(**inputs).logits
            scores.extend(logits.view(-1).float().tolist())
        return scores

    def rerank(self, *, query: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
        if not hits:
            return []

        self._ensure_model()
        scores = self._compute_scores([(query, hit.text) for hit in hits])
        reranked = [replace(hit, score=float(score)) for hit, score in zip(hits, scores, strict=True)]
        reranked.sort(key=lambda hit: hit.score, reverse=True)
        return reranked[:top_k]


__all__ = ["BgeRerankerV2M3"]
