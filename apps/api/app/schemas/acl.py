from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentAclUpdateRequest(BaseModel):
    visibility: str
    allowed_user_ids: list[UUID] = Field(default_factory=list)
    allowed_group_ids: list[UUID] = Field(default_factory=list)
    sensitivity: str = "internal"
    expires_at: datetime | None = None


class DocumentAclResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    owner_user_id: UUID
    visibility: str
    allowed_user_ids: list[UUID]
    allowed_group_ids: list[UUID]
    sensitivity: str
    expires_at: datetime | None = None
