from __future__ import annotations

import logging
import re
from typing import Any

from app.schemas.verification import VerificationSentenceResult, VerificationSummary

logger = logging.getLogger(__name__)

_CrossEncoder: Any | None = None  # lazy import cache


def _softmax(logits: list[float]) -> list[float]:
    """Numerically-stable softmax for a 3-element logit vector."""
    import math

    max_l = max(logits)
    exps = [math.exp(l - max_l) for l in logits]
    total = sum(exps)
    return [e / total for e in exps]


class NliAnswerVerifier:
    """NLI-based sentence-level evidence verifier.

    Uses a cross-encoder NLI model to determine whether each answer sentence
    is supported by the context blocks. Unlike substring overlap, this correctly
    handles paraphrased content.

    The cross-encoder/nli-deberta-v3-base model outputs raw logits as a
    3-element array per pair: [contradiction, entailment, neutral].

    Scoring strategy (controlled by ``scoring_mode``):
      - ``"entailment"`` (default): uses the entailment probability as the
        support score. Strict — only sentences strictly entailed by context
        pass. Good for high-precision faithfulness.
      - ``"not_contradicted"``: uses ``1 - P(contradiction)`` as the support
        score. A sentence is considered supported if no context block
        contradicts it. This handles paraphrased and elaborated content that
        strict NLI classifies as "neutral". Recommended for RAG faithfulness
        where the LLM is expected to paraphrase rather than quote verbatim.

    The ``unsupported_ratio`` parameter controls the overall verdict: if the
    fraction of unsupported sentences is at most this ratio, the overall
    status is "supported". Default 0.0 (all-or-nothing).
    """

    # Label order confirmed from model card:
    # https://huggingface.co/cross-encoder/nli-deberta-v3-base
    _CONTRADICTION_IDX = 0
    _ENTAILMENT_IDX = 1

    def __init__(
        self,
        model_name: str = "cross-encoder/nli-deberta-v3-base",
        entailment_threshold: float = 0.5,
        max_length: int = 512,
        *,
        scoring_mode: str = "entailment",
        unsupported_ratio: float = 0.0,
    ) -> None:
        self._model_name = model_name
        self._entailment_threshold = entailment_threshold
        self._max_length = max_length
        self._scoring_mode = scoring_mode
        self._unsupported_ratio = unsupported_ratio
        self._model: Any | None = None

    def _ensure_model(self) -> None:
        global _CrossEncoder
        if self._model is not None:
            return
        if _CrossEncoder is None:
            try:
                from sentence_transformers import CrossEncoder as _CE
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "NLI verifier initialization failed: install 'sentence-transformers' "
                    "to use the NLI answer verifier.  "
                    "pip install 'uber-rag[eval]'"
                ) from exc
            _CrossEncoder = _CE

        logger.info("Loading NLI verifier model %s ...", self._model_name)
        self._model = _CrossEncoder(self._model_name)

    def _compute_support_score(self, probs: list[float]) -> float:
        """Compute the support score for a sentence given NLI probabilities.

        In ``"entailment"`` mode, returns P(entailment).
        In ``"not_contradicted"`` mode, returns 1 - P(contradiction).
        """
        if self._scoring_mode == "not_contradicted":
            return 1.0 - probs[self._CONTRADICTION_IDX]
        return probs[self._ENTAILMENT_IDX]

    def verify(self, *, answer_text: str, context_payload) -> VerificationSummary:
        sentences = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+", answer_text)
            if part.strip()
        ]

        if not sentences:
            return VerificationSummary(
                status="insufficient_evidence",
                sentence_count=0,
                supported_sentence_count=0,
                unsupported_sentence_count=0,
                insufficient_evidence_sentence_count=0,
                sentences=[],
            )

        if context_payload.block_count == 0:
            results = [
                VerificationSentenceResult(
                    sentence=s, status="insufficient_evidence", citation_ids=[]
                )
                for s in sentences
            ]
            return VerificationSummary(
                status="insufficient_evidence",
                sentence_count=len(results),
                supported_sentence_count=0,
                unsupported_sentence_count=0,
                insufficient_evidence_sentence_count=len(results),
                sentences=results,
            )

        self._ensure_model()

        results: list[VerificationSentenceResult] = []
        for sentence in sentences:
            # Score sentence against each context block as (premise, hypothesis).
            pairs = [(block.text, sentence) for block in context_payload.blocks]
            raw_scores = self._model.predict(pairs)

            # raw_scores shape: (num_pairs, 3) — raw logits per pair.
            # Find the block with highest support score.
            best_score = -1.0
            best_block_idx = -1
            for idx, logits in enumerate(raw_scores):
                probs = _softmax([float(v) for v in logits])
                score = self._compute_support_score(probs)
                if score > best_score:
                    best_score = score
                    best_block_idx = idx

            if best_score >= self._entailment_threshold and best_block_idx >= 0:
                citation_id = context_payload.blocks[best_block_idx].citation_id
                results.append(
                    VerificationSentenceResult(
                        sentence=sentence,
                        status="supported",
                        citation_ids=[citation_id] if citation_id else [],
                    )
                )
            else:
                results.append(
                    VerificationSentenceResult(
                        sentence=sentence,
                        status="unsupported",
                        citation_ids=[],
                    )
                )

        supported = sum(1 for r in results if r.status == "supported")
        unsupported = sum(1 for r in results if r.status == "unsupported")

        # Overall status: "supported" if unsupported ratio is within tolerance
        if results:
            actual_ratio = unsupported / len(results)
            overall = "supported" if actual_ratio <= self._unsupported_ratio else "unsupported"
        else:
            overall = "unsupported"

        return VerificationSummary(
            status=overall,
            sentence_count=len(results),
            supported_sentence_count=supported,
            unsupported_sentence_count=unsupported,
            insufficient_evidence_sentence_count=0,
            sentences=results,
        )
