from __future__ import annotations

import re

from app.schemas.verification import VerificationSentenceResult, VerificationSummary


class AnswerVerifier:
    """Deterministic sentence-level evidence verifier.

    Splits the generated answer into sentences and checks each
    against the authorized context blocks using casefolded substring
    overlap. This is intentionally conservative: false negatives
    (marking a paraphrased sentence as unsupported) are safer than
    false positives for this phase.
    """

    def verify(self, *, answer_text: str, context_payload) -> VerificationSummary:
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", answer_text) if part.strip()]
        results: list[VerificationSentenceResult] = []
        for sentence in sentences:
            normalized_sentence = sentence.casefold()
            matched_citation_ids = [
                block.citation_id
                for block in context_payload.blocks
                if block.citation_id and normalized_sentence in block.text.casefold()
            ]
            if matched_citation_ids:
                status = "supported"
            elif context_payload.block_count == 0:
                status = "insufficient_evidence"
            else:
                status = "unsupported"
            results.append(
                VerificationSentenceResult(
                    sentence=sentence,
                    status=status,
                    citation_ids=matched_citation_ids,
                )
            )
        supported = sum(1 for item in results if item.status == "supported")
        unsupported = sum(1 for item in results if item.status == "unsupported")
        insufficient = sum(1 for item in results if item.status == "insufficient_evidence")
        overall = "supported" if results and unsupported == 0 and insufficient == 0 else "unsupported"
        return VerificationSummary(
            status=overall,
            sentence_count=len(results),
            supported_sentence_count=supported,
            unsupported_sentence_count=unsupported,
            insufficient_evidence_sentence_count=insufficient,
            sentences=results,
        )
