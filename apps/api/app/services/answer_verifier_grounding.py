from __future__ import annotations

import logging
import re
from typing import Any

from app.schemas.verification import VerificationSentenceResult, VerificationSummary

logger = logging.getLogger(__name__)


class GroundingAnswerVerifier:
    """Grounding-based sentence-level evidence verifier (ADR-0019).

    Uses MiniCheck-Flan-T5-Large — a fact-checking model trained specifically
    to decide whether a claim is supported by a grounding document, including
    paraphrased claims (the failure mode that made strict NLI entailment
    non-functional per ADR-0016).

    Scoring follows the official MiniCheck inference recipe (verified against
    the upstream repository, see research/2026-06-11-phase-d-entry.md):
    input ``"predict: " + document + eos + claim``, a single forward pass with
    a zero decoder token, and ``P(support) = softmax(logits[:, [3, 209]])[1]``.

    Each answer sentence is scored against every context block in one batched
    forward; the sentence is supported when the best block's support
    probability reaches ``threshold``. ``unsupported_ratio`` aggregates the
    overall verdict exactly like the NLI verifier (default 0.0 — a true
    support metric is all-or-nothing by default).
    """

    # Token positions for [unsupported, supported] per the official recipe.
    _LABEL_TOKEN_IDS = [3, 209]

    def __init__(
        self,
        model_name: str = "lytang/MiniCheck-Flan-T5-Large",
        threshold: float = 0.5,
        max_input_length: int = 2048,
        *,
        unsupported_ratio: float = 0.0,
    ) -> None:
        self._model_name = model_name
        self._threshold = threshold
        self._max_input_length = max_input_length
        self._unsupported_ratio = unsupported_ratio
        self._model: Any | None = None
        self._tokenizer: Any | None = None

    def _ensure_model(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return
        try:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Grounding verifier initialization failed: install 'transformers' "
                "(ships with the [ml] extras) to use the grounding answer verifier."
            ) from exc

        logger.info("Loading grounding verifier model %s ...", self._model_name)
        self._tokenizer = AutoTokenizer.from_pretrained(self._model_name)
        self._model = AutoModelForSeq2SeqLM.from_pretrained(self._model_name)
        self._model.eval()

    def _support_probabilities(self, *, sentence: str, block_texts: list[str]) -> list[float]:
        """P(support) for one sentence against each block, in one batch."""
        import torch

        assert self._tokenizer is not None and self._model is not None
        texts = [
            f"predict: {block_text}{self._tokenizer.eos_token}{sentence}"
            for block_text in block_texts
        ]
        inputs = self._tokenizer(
            texts,
            max_length=self._max_input_length,
            truncation=True,
            padding=True,
            return_tensors="pt",
        )
        device = getattr(self._model, "device", "cpu")
        input_ids = inputs["input_ids"].to(device)
        attention_mask = inputs["attention_mask"].to(device)
        decoder_input_ids = torch.zeros((input_ids.size(0), 1), dtype=torch.long).to(device)

        with torch.no_grad():
            outputs = self._model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                decoder_input_ids=decoder_input_ids,
            )
        logits = outputs.logits.squeeze(1)
        label_logits = logits[:, torch.tensor(self._LABEL_TOKEN_IDS)]
        probs = torch.nn.functional.softmax(label_logits, dim=-1)
        return [float(p) for p in probs[:, 1].cpu()]

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

        block_texts = [block.text for block in context_payload.blocks]
        results: list[VerificationSentenceResult] = []
        for sentence in sentences:
            probabilities = self._support_probabilities(
                sentence=sentence, block_texts=block_texts
            )
            best_idx = max(range(len(probabilities)), key=probabilities.__getitem__)
            best_score = probabilities[best_idx]

            if best_score >= self._threshold:
                citation_id = context_payload.blocks[best_idx].citation_id
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
        actual_ratio = unsupported / len(results)
        overall = "supported" if actual_ratio <= self._unsupported_ratio else "unsupported"

        return VerificationSummary(
            status=overall,
            sentence_count=len(results),
            supported_sentence_count=supported,
            unsupported_sentence_count=unsupported,
            insufficient_evidence_sentence_count=0,
            sentences=results,
        )
