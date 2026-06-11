"""Tests for GroundingAnswerVerifier (ADR-0019, MiniCheck-Flan-T5-Large).

Default-suite tests use an injected deterministic fake model so the ~3 GB
weights are never loaded here; real-model behavior tests live in tests/eval/
(nightly CI + on-demand).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch", reason="ML stack not installed")

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.schemas.context import ContextBlock, ContextPayload
from app.services.answer_verifier_grounding import GroundingAnswerVerifier


def _block(text: str, citation_id: str = "cite-1", rank: int = 1) -> ContextBlock:
    return ContextBlock(
        text=text,
        document_id="doc-1",
        document_title="Test Doc",
        chunk_id=citation_id,
        citation_id=citation_id,
        heading_path=[],
        rank=rank,
    )


def _payload(blocks: list[ContextBlock]) -> ContextPayload:
    return ContextPayload(
        blocks=blocks,
        block_count=len(blocks),
        total_characters=sum(len(b.text) for b in blocks),
        truncated=False,
    )


class _FakeTokenizer:
    eos_token = "</s>"

    def __init__(self) -> None:
        self.last_texts: list[str] = []

    def __call__(self, texts, **kwargs):
        self.last_texts = list(texts)
        n = len(self.last_texts)
        return {
            "input_ids": torch.ones((n, 4), dtype=torch.long),
            "attention_mask": torch.ones((n, 4), dtype=torch.long),
        }


class _FakeModel:
    """Builds logits so that softmax(logits[:, [3, 209]])[1] equals the score
    assigned by ``score_fn`` to each input text — the exact extraction the
    real MiniCheck recipe uses."""

    device = "cpu"

    def __init__(self, tokenizer: _FakeTokenizer, score_fn) -> None:
        self._tokenizer = tokenizer
        self._score_fn = score_fn

    def eval(self):  # pragma: no cover - parity with real model API
        return self

    def __call__(self, *, input_ids, attention_mask, decoder_input_ids):
        from types import SimpleNamespace

        n = input_ids.size(0)
        vocab = 300
        logits = torch.zeros((n, 1, vocab))
        for i, text in enumerate(self._tokenizer.last_texts):
            p = min(max(self._score_fn(text), 1e-6), 1 - 1e-6)
            logits[i, 0, 3] = 0.0
            logits[i, 0, 209] = math.log(p / (1 - p))
        return SimpleNamespace(logits=logits)


def _verifier(score_fn, *, threshold: float = 0.5, unsupported_ratio: float = 0.0) -> GroundingAnswerVerifier:
    verifier = GroundingAnswerVerifier(threshold=threshold, unsupported_ratio=unsupported_ratio)
    tokenizer = _FakeTokenizer()
    verifier._tokenizer = tokenizer
    verifier._model = _FakeModel(tokenizer, score_fn)
    return verifier


def test_input_format_follows_official_minicheck_recipe():
    """Input must be 'predict: ' + block + eos + sentence (entry-note recipe)."""
    captured = {}

    def score_fn(text: str) -> float:
        captured["text"] = text
        return 0.9

    verifier = _verifier(score_fn)
    verifier.verify(
        answer_text="Entropy never decreases.",
        context_payload=_payload([_block("The second law says entropy never decreases.")]),
    )
    assert captured["text"] == (
        "predict: The second law says entropy never decreases.</s>Entropy never decreases."
    )


def test_supported_sentence_gets_citation_of_best_block():
    def score_fn(text: str) -> float:
        return 0.95 if "best block" in text else 0.2

    verifier = _verifier(score_fn)
    summary = verifier.verify(
        answer_text="The claim holds.",
        context_payload=_payload([
            _block("irrelevant block", citation_id="cite-weak", rank=1),
            _block("the best block for this", citation_id="cite-best", rank=2),
        ]),
    )
    assert summary.status == "supported"
    assert summary.sentences[0].status == "supported"
    assert summary.sentences[0].citation_ids == ["cite-best"]


def test_unsupported_sentence_fails_threshold():
    verifier = _verifier(lambda text: 0.3)
    summary = verifier.verify(
        answer_text="A fabricated claim.",
        context_payload=_payload([_block("unrelated evidence")]),
    )
    assert summary.status == "unsupported"
    assert summary.unsupported_sentence_count == 1


def test_unsupported_ratio_aggregation():
    def score_fn(text: str) -> float:
        return 0.1 if "fabricated" in text else 0.9

    # 1 of 3 sentences unsupported -> ratio 1/3
    answer = "True one. True two. A fabricated third."
    blocks = _payload([_block("True one. True two. evidence")])

    strict = _verifier(score_fn, unsupported_ratio=0.0)
    assert strict.verify(answer_text=answer, context_payload=blocks).status == "unsupported"

    lenient = _verifier(score_fn, unsupported_ratio=0.4)
    assert lenient.verify(answer_text=answer, context_payload=blocks).status == "supported"


def test_empty_answer_is_insufficient_evidence():
    verifier = _verifier(lambda text: 0.9)
    summary = verifier.verify(answer_text="   ", context_payload=_payload([_block("evidence")]))
    assert summary.status == "insufficient_evidence"
    assert summary.sentence_count == 0


def test_zero_blocks_is_insufficient_evidence():
    verifier = _verifier(lambda text: 0.9)
    summary = verifier.verify(answer_text="Some claim.", context_payload=_payload([]))
    assert summary.status == "insufficient_evidence"
    assert summary.insufficient_evidence_sentence_count == 1


def test_sentence_splitting_matches_verifier_family():
    """Same regex family as the NLI/substring verifiers: split on [.!?]+ws."""
    seen: list[str] = []

    def score_fn(text: str) -> float:
        seen.append(text)
        return 0.9

    verifier = _verifier(score_fn)
    summary = verifier.verify(
        answer_text="First fact. Second fact! Third?",
        context_payload=_payload([_block("evidence text")]),
    )
    assert summary.sentence_count == 3
    assert [s.sentence for s in summary.sentences] == ["First fact.", "Second fact!", "Third?"]
