from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.documents import DocumentResponse


class IngestionRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    tenant_id: UUID
    status: str
    workflow_backend: str
    parser_backend: str
    source_hash: str
    created_at: datetime
    updated_at: datetime


class IngestionRunListResponse(BaseModel):
    items: list[IngestionRunResponse]


class IngestionJobListResponse(BaseModel):
    items: list[IngestionJobResponse]


class IngestionJobResponse(IngestionRunResponse):
    pass


class DocumentUploadResponse(DocumentResponse):
    ingestion_run_id: UUID
