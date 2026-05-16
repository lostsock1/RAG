from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ParsedBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_type: str | None = None
    text: str | None = None
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)


class ParsedPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_number: int
    text: str
    blocks: list[ParsedBlock]


class ParsedTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_number: int
    bbox: list[float] = Field(min_length=4, max_length=4)
    markdown: str


class ParserProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parser_backend: str
    parser_version: str
    profile: str


class ParsedArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    pages: list[ParsedPage]
    tables: list[ParsedTable]
    provenance: ParserProvenance
