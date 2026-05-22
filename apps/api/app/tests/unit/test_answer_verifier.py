from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.schemas.context import ContextBlock, ContextPayload
from app.services.answer_verifier import AnswerVerifier


def _context_payload(blocks: list[ContextBlock]) -> ContextPayload:
    return ContextPayload(
        blocks=blocks,
        block_count=len(blocks),
        total_characters=sum(len(b.text) for b in blocks),
        truncated=False,
    )


def test_answer_verifier_marks_sentence_supported_when_overlap_exists() -> None:
    verifier = AnswerVerifier()
    payload = _context_payload([
        ContextBlock(
            text="Alpha evidence proves the answer.",
            document_id="doc-1",
            document_title="Doc A",
            chunk_id="chunk-1",
            citation_id="chunk-1",
            page_start=1,
            page_end=1,
            heading_path=["A"],
            rank=1,
        )
    ])

    summary = verifier.verify(answer_text="Alpha evidence proves the answer.", context_payload=payload)

    assert summary.status == "supported"
    assert summary.supported_sentence_count == 1
    assert summary.sentences[0].citation_ids == ["chunk-1"]


def test_answer_verifier_marks_sentence_unsupported_when_no_overlap() -> None:
    verifier = AnswerVerifier()
    payload = _context_payload([
        ContextBlock(
            text="Completely different content here.",
            document_id="doc-1",
            document_title="Doc A",
            chunk_id="chunk-1",
            citation_id="chunk-1",
            page_start=1,
            page_end=1,
            heading_path=["A"],
            rank=1,
        )
    ])

    summary = verifier.verify(answer_text="This claim is not in the evidence.", context_payload=payload)

    assert summary.status == "unsupported"
    assert summary.unsupported_sentence_count == 1
    assert summary.sentences[0].citation_ids == []


def test_answer_verifier_marks_insufficient_evidence_when_no_context_blocks() -> None:
    verifier = AnswerVerifier()
    payload = _context_payload([])

    summary = verifier.verify(answer_text="Some answer text.", context_payload=payload)

    assert summary.status == "unsupported"
    assert summary.insufficient_evidence_sentence_count == 1


def test_answer_verifier_handles_multiple_sentences() -> None:
    verifier = AnswerVerifier()
    payload = _context_payload([
        ContextBlock(
            text="Alpha evidence proves the answer. Beta evidence is also relevant.",
            document_id="doc-1",
            document_title="Doc A",
            chunk_id="chunk-1",
            citation_id="chunk-1",
            page_start=1,
            page_end=1,
            heading_path=["A"],
            rank=1,
        )
    ])

    summary = verifier.verify(
        answer_text="Alpha evidence proves the answer. But this claim is unsupported.",
        context_payload=payload,
    )

    assert summary.status == "unsupported"
    assert summary.supported_sentence_count == 1
    assert summary.unsupported_sentence_count == 1
    assert summary.sentences[0].citation_ids == ["chunk-1"]
    assert summary.sentences[1].citation_ids == []


def test_answer_verifier_returns_supported_when_all_sentences_match() -> None:
    verifier = AnswerVerifier()
    payload = _context_payload([
        ContextBlock(
            text="First sentence. Second sentence.",
            document_id="doc-1",
            document_title="Doc A",
            chunk_id="chunk-1",
            citation_id="chunk-1",
            page_start=1,
            page_end=1,
            heading_path=["A"],
            rank=1,
        )
    ])

    summary = verifier.verify(
        answer_text="First sentence. Second sentence.",
        context_payload=payload,
    )

    assert summary.status == "supported"
    assert summary.supported_sentence_count == 2
