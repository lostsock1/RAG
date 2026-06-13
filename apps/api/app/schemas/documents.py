from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentUploadForm(BaseModel):
    title: str
    source_type: str
    document_type: str | None = None
    language: str | None = None
    # Document profile selects the chunker (ADR-0012): "book" gets the
    # hierarchy-aware chunker, "loose" gets the flat structure-aware one.
    profile: Literal["loose", "book"] = "loose"


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    owner_user_id: UUID
    title: str
    source_type: str
    document_type: str | None = None
    language: str | None = None
    source_hash: str
    file_name: str | None = None
    file_size_bytes: int | None = None
    object_key: str | None = None
    ingestion_status: str
    created_at: datetime
    updated_at: datetime
