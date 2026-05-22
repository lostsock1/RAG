from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.citations import Citation
from app.schemas.verification import VerificationSummary


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)

    @field_validator("question")
    @classmethod
    def reject_whitespace_only(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question must not be blank or whitespace-only.")
        return value


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_text: str
    status: Literal["answered", "not_enough_evidence"]
    model_name: str | None = None
    provider_name: str | None = None
    context_block_count: int
    retrieval_hit_count: int
    usage: dict[str, int] | None = None
    citations: list[Citation] = []
    verification: VerificationSummary | None = None
