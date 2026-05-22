from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.context import ContextPayload


class GenerateAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    context_payload: ContextPayload
    model_name: str | None = Field(default=None, min_length=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_output_tokens: int | None = Field(default=None, ge=1)


class GenerateAnswerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_text: str
    model_name: str
    provider_name: str
    usage: dict[str, int] | None = None
