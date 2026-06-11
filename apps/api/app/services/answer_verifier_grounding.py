from __future__ import annotations

import logging
import re
from typing import Any

from app.schemas.verification import VerificationSentenceResult, VerificationSummary

logger = logging.getLogger(__name__)


class GroundingAnswerVerifier:
    """Grounding-based sentence-level evidence verifier (ADR-0019).

    Uses MiniCheck models — fact-checkers trained specifically to decide
    whether a claim is supported by a grounding document, including
    paraphrased claims (the failure mode that made strict NLI entailment
    non-functional per ADR-0016).

    Scoring follows the official MiniCheck inference recipes (verified against
    the upstream repository, see research/2026-06-11-phase-d-entry.md):

    - seq2seq (MiniCheck-Flan-T5-Large): input
      ``"predict: " + document + eos + claim``, a single forward pass with a
      zero decoder token, ``P(support) = softmax(logits[:, [3, 209]])[1]``,
      2048-token window.
    - sequence classification (MiniCheck-RoBERTa-Large / DeBERTa-v3-Large):
      input ``document_chunk + eos + claim`` (no prefix), 2-class head,
      ``P(support) = softmax(logits)[:, 1]``. The window is 512 tokens for
      RoBERTa, so each block is sentence-packed into chunks of at most
      ``max_input_length - 300`` tokens (the upstream claim reserve) and the
      block score is the max over its chunks — without this, truncation
      would cut off the trailing claim itself.

    Each answer sentence is scored against every context block in one batched
    forward; the sentence is supported when the best block's support
    probability reaches ``threshold``. ``unsupported_ratio`` aggregates the
    overall verdict exactly like the NLI verifier (default 0.0 — a true
    support metric is all-or-nothing by default).
    """

    # Token positions for [unsupported, supported] per the official recipe.
    _LABEL_TOKEN_IDS = [3, 209]
    # Upstream: default_chunk_size = max_model_len - 300, reserving room for
    # the claim appended after the document chunk.
    _CLAIM_TOKEN_RESERVE = 300
    _RECIPE_DEFAULT_MAX_INPUT_LENGTH = {"seq2seq": 2048, "classification": 512}

    def __init__(
        self,
        model_name: str = "lytang/MiniCheck-Flan-T5-Large",
        threshold: float = 0.5,
        max_input_length: int | None = None,
        *,
        unsupported_ratio: float = 0.0,
    ) -> None:
        self._model_name = model_name
        self._recipe = self._resolve_recipe(model_name)
        self._threshold = threshold
        self._max_input_length = (
            max_input_length
            if max_input_length is not None
            else self._RECIPE_DEFAULT_MAX_INPUT_LENGTH[self._recipe]
        )
        self._unsupported_ratio = unsupported_ratio
        self._model: Any | None = None
        self._tokenizer: Any | None = None

    @staticmethod
    def _resolve_recipe(model_name: str) -> str:
        lowered = model_name.lower()
        if "flan-t5" in lowered:
            return "seq2seq"
        if "roberta" in lowered or "deberta" in lowered:
            return "classification"
        raise RuntimeError(
            f"Unsupported grounding model family: {model_name!r}. Supported: "
            "MiniCheck Flan-T5 (seq2seq) and RoBERTa/DeBERTa (sequence "
            "classification) checkpoints."
        )

    def _ensure_model(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return
        try:
            from transformers import (
                AutoModelForSeq2SeqLM,
                AutoModelForSequenceClassification,
                AutoTokenizer,
            )
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Grounding verifier initialization failed: install 'transformers' "
                "(ships with the [ml] extras) to use the grounding answer verifier."
            ) from exc

        logger.info("Loading grounding verifier model %s ...", self._model_name)
        self._tokenizer = AutoTokenizer.from_pretrained(self._model_name)
        if self._recipe == "seq2seq":
            self._model = AutoModelForSeq2SeqLM.from_pretrained(self._model_name)
        else:
            self._model = AutoModelForSequenceClassification.from_pretrained(self._model_name)
        self._model.eval()

    def _support_probabilities(self, *, sentence: str, block_texts: list[str]) -> list[float]:
        """P(support) for one sentence against each block, in one batch."""
        if self._recipe == "seq2seq":
            return self._support_probabilities_seq2seq(sentence=sentence, block_texts=block_texts)
        return self._support_probabilities_classification(sentence=sentence, block_texts=block_texts)

    def _support_probabilities_seq2seq(self, *, sentence: str, block_texts: list[str]) -> list[float]:
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

    def _support_probabilities_classification(
        self, *, sentence: str, block_texts: list[str]
    ) -> list[float]:
        import torch

        assert self._tokenizer is not None and self._model is not None
        chunk_budget = max(self._max_input_length - self._CLAIM_TOKEN_RESERVE, 1)
        pair_texts: list[str] = []
        pair_block_indices: list[int] = []
        for block_index, block_text in enumerate(block_texts):
            for chunk in self._chunk_by_tokens(block_text, chunk_budget):
                pair_texts.append(f"{chunk}{self._tokenizer.eos_token}{sentence}")
                pair_block_indices.append(block_index)
        if not pair_texts:
            return [0.0] * len(block_texts)

        inputs = self._tokenizer(
            pair_texts,
            max_length=self._max_input_length,
            truncation=True,
            padding=True,
            return_tensors="pt",
        )
        device = getattr(self._model, "device", "cpu")
        with torch.no_grad():
            outputs = self._model(
                input_ids=inputs["input_ids"].to(device),
                attention_mask=inputs["attention_mask"].to(device),
            )
        probs = torch.nn.functional.softmax(outputs.logits, dim=-1)[:, 1].cpu()

        best_by_block = [0.0] * len(block_texts)
        for prob, block_index in zip(probs, pair_block_indices):
            best_by_block[block_index] = max(best_by_block[block_index], float(prob))
        return best_by_block

    def _chunk_by_tokens(self, text: str, chunk_budget: int) -> list[str]:
        """Greedy sentence-packing into chunks of at most ``chunk_budget``
        tokens, mirroring the upstream recipe. An oversized single segment is
        yielded as its own chunk (upstream behavior; tokenizer truncation then
        applies)."""
        segments = [part for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]
        if not segments:
            return []

        chunks: list[str] = []
        current: list[str] = []
        current_tokens = 0
        for segment in segments:
            segment_tokens = self._count_tokens(segment)
            if current and current_tokens + segment_tokens > chunk_budget:
                chunks.append(" ".join(current))
                current = [segment]
                current_tokens = segment_tokens
            else:
                current.append(segment)
                current_tokens += segment_tokens
        if current:
            chunks.append(" ".join(current))
        return chunks

    def _count_tokens(self, text: str) -> int:
        assert self._tokenizer is not None
        encoded = self._tokenizer(
            text,
            padding=False,
            add_special_tokens=False,
            truncation=True,
            max_length=self._max_input_length,
        )
        return len(encoded["input_ids"])

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
