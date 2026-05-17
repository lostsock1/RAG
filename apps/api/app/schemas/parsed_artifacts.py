from __future__ import annotations

from copy import deepcopy
from typing import Literal
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


class OcrProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["applied", "not-applied", "unverified"]
    applied: bool | None = None
    engine: str
    provider: Literal["docling-local", "remote-api"]
    page_numbers: list[int] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ParserProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parser_backend: Literal["docling-local", "remote-api"]
    parser_version: str
    profile: Literal["local-cpu", "local-gpu", "remote-api"]
    ocr: OcrProvenance | None = None


class ParsedArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    pages: list[ParsedPage]
    tables: list[ParsedTable]
    provenance: ParserProvenance


LEGACY_PARSER_BACKEND_MAP = {
    "docling": "docling-local",
    "remote": "remote-api",
}

LEGACY_PROFILE_MAP = {
    "cpu-local": "local-cpu",
    "gpu-local": "local-gpu",
}


def normalize_parsed_artifact_payload(payload: dict) -> dict:
    normalized = deepcopy(payload)
    provenance = normalized.get("provenance")
    if not isinstance(provenance, dict):
        return normalized

    parser_backend = provenance.get("parser_backend")
    if parser_backend in LEGACY_PARSER_BACKEND_MAP:
        provenance["parser_backend"] = LEGACY_PARSER_BACKEND_MAP[parser_backend]

    profile = provenance.get("profile")
    if profile in LEGACY_PROFILE_MAP:
        provenance["profile"] = LEGACY_PROFILE_MAP[profile]

    return normalized
