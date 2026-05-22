from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: str
    document_id: str
    document_title: str
    chunk_id: str
    source_viewer_url: str
    page_start: int | None = None
    page_end: int | None = None
    heading_path: list[str] = Field(default_factory=list)


class ResolveCitationsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citations: list[str] = Field(min_length=1)

    @field_validator("citations")
    @classmethod
    def validate_citations(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("Citation IDs must not be blank.")
        return normalized


class ResolveCitationsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[Citation]
