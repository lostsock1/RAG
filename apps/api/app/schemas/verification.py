from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VerificationSentenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentence: str
    status: Literal["supported", "unsupported", "insufficient_evidence"]
    citation_ids: list[str] = Field(default_factory=list)


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

    question: str = Field(min_length=1)
    answer_text: str
    top_k: int = Field(default=5, ge=1, le=50)

    @field_validator("question")
    @classmethod
    def reject_blank_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question must not be blank or whitespace-only.")
        return value
