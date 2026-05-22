"""Tests for NliAnswerVerifier.

These tests load the cross-encoder/nli-deberta-v3-base model (~1.3 GB on first
run, cached thereafter).  Mark them with @pytest.mark.slow so CI can skip them
on lightweight runners.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.schemas.context import ContextBlock, ContextPayload
from app.services.answer_verifier_nli import NliAnswerVerifier


def _block(
    text: str,
    citation_id: str = "cite-1",
    document_id: str = "doc-1",
    rank: int = 1,
) -> ContextBlock:
    return ContextBlock(
        text=text,
        document_id=document_id,
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


# ---------------------------------------------------------------------------
# Test 1: Paraphrase detection — the key case substring overlap fails on
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_nli_verifier_detects_paraphrased_entailment() -> None:
    """A paraphrased sentence should be marked as supported."""
    verifier = NliAnswerVerifier()
    payload = _payload([
        _block(
            "The second law states that entropy of an isolated system "
            "can never decrease over time.",
            citation_id="thermo-2nd",
        )
    ])

    summary = verifier.verify(
        answer_text="Entropy never decreases in an isolated system.",
        context_payload=payload,
    )

    assert summary.sentences[0].status == "supported", (
        f"Expected 'supported' for paraphrased sentence, got "
        f"'{summary.sentences[0].status}'"
    )
    assert summary.sentences[0].citation_ids == ["thermo-2nd"]


# ---------------------------------------------------------------------------
# Test 2: Hallucination detection
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_nli_verifier_detects_hallucination() -> None:
    """An exaggerated claim not entailed by context should be unsupported."""
    verifier = NliAnswerVerifier()
    payload = _payload([
        _block(
            "The second law states that entropy of an isolated system "
            "can never decrease over time.",
            citation_id="thermo-2nd",
        )
    ])

    summary = verifier.verify(
        answer_text="Entropy always increases in all processes without exception.",
        context_payload=payload,
    )

    assert summary.sentences[0].status == "unsupported", (
        f"Expected 'unsupported' for hallucinated sentence, got "
        f"'{summary.sentences[0].status}'"
    )


# ---------------------------------------------------------------------------
# Test 3: Empty context → insufficient_evidence
# ---------------------------------------------------------------------------


def test_nli_verifier_insufficient_evidence_when_no_context() -> None:
    """No context blocks should yield insufficient_evidence (no model load)."""
    verifier = NliAnswerVerifier()
    payload = _payload([])

    summary = verifier.verify(
        answer_text="Something.",
        context_payload=payload,
    )

    assert summary.status == "insufficient_evidence"
    assert summary.insufficient_evidence_sentence_count == 1
    assert summary.sentences[0].status == "insufficient_evidence"


# ---------------------------------------------------------------------------
# Test 4: Multiple blocks — best match selected for citation
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_nli_verifier_selects_best_matching_block() -> None:
    """Citation should point to the block that best entails the sentence."""
    verifier = NliAnswerVerifier()
    payload = _payload([
        _block(
            "Photosynthesis converts light to chemical energy.",
            citation_id="photo-1",
            rank=1,
        ),
        _block(
            "The second law of thermodynamics states that entropy never "
            "decreases in an isolated system.",
            citation_id="thermo-2nd",
            rank=2,
        ),
    ])

    summary = verifier.verify(
        answer_text="In thermodynamics, entropy cannot decrease in a closed system.",
        context_payload=payload,
    )

    assert summary.sentences[0].status == "supported"
    assert summary.sentences[0].citation_ids == ["thermo-2nd"], (
        f"Expected citation to thermo-2nd, got {summary.sentences[0].citation_ids}"
    )


# ---------------------------------------------------------------------------
# Test 5: Mixed sentences — some supported, some unsupported
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_nli_verifier_mixed_sentences() -> None:
    """Overall status should be 'unsupported' when any sentence is unsupported."""
    verifier = NliAnswerVerifier()
    payload = _payload([
        _block(
            "The second law states that entropy of an isolated system "
            "can never decrease over time.",
            citation_id="thermo-2nd",
        )
    ])

    summary = verifier.verify(
        answer_text=(
            "Entropy never decreases in an isolated system. "
            "Quantum tunneling allows particles to pass through walls."
        ),
        context_payload=payload,
    )

    assert summary.sentence_count == 2
    assert summary.sentences[0].status == "supported"
    assert summary.sentences[1].status == "unsupported"
    assert summary.status == "unsupported"
    assert summary.supported_sentence_count == 1
    assert summary.unsupported_sentence_count == 1


# ---------------------------------------------------------------------------
# Test 6: Empty answer text
# ---------------------------------------------------------------------------


def test_nli_verifier_empty_answer() -> None:
    """Empty answer should return insufficient_evidence with 0 sentences."""
    verifier = NliAnswerVerifier()
    payload = _payload([_block("Some context.")])

    summary = verifier.verify(answer_text="", context_payload=payload)

    assert summary.status == "insufficient_evidence"
    assert summary.sentence_count == 0


# ---------------------------------------------------------------------------
# Test 7: Verbatim match (should also work via NLI)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_nli_verifier_verbatim_match() -> None:
    """A verbatim sentence should also be detected as supported."""
    verifier = NliAnswerVerifier()
    payload = _payload([
        _block(
            "Alpha evidence proves the answer.",
            citation_id="cite-alpha",
        )
    ])

    summary = verifier.verify(
        answer_text="Alpha evidence proves the answer.",
        context_payload=payload,
    )

    assert summary.sentences[0].status == "supported"
    assert summary.sentences[0].citation_ids == ["cite-alpha"]
