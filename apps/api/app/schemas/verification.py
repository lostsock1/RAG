from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class VerificationSentenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentence: str
    status: Literal["supported", "unsupported", "insufficient_evidence"]
    citation_ids: list[str] = []


class VerificationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["supported", "unsupported", "insufficient_evidence"]
    sentence_count: int
    supported_sentence_count: int
    unsupported_sentence_count: int
    insufficient_evidence_sentence_count: int
    sentences: list[VerificationSentenceResult]


class VerifyAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    answer_text: str
    top_k: int = 5
