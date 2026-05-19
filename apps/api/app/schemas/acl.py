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


class AclPolicyNamedValueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    display_name: str
    is_active: bool
    rank: int | None = None


class TenantAclBootstrapPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    policy_id: UUID
    tenant_id: UUID
    policy_version: int
    status: str
    locked_at: datetime | None = None
    default_visibility_mode: str
    visibility_modes: dict[str, AclPolicyNamedValueResponse]
    sensitivity_levels: dict[str, AclPolicyNamedValueResponse]
    dimensions: dict[str, AclPolicyNamedValueResponse]


class TenantAclBootstrapPolicyUpdateRequest(BaseModel):
    default_visibility_mode: str | None = None
    visibility_display_names: dict[str, str] | None = None
    visibility_active_flags: dict[str, bool] | None = None
    sensitivity_display_names: dict[str, str] | None = None
    dimension_display_names: dict[str, str] | None = None
    dimension_active_flags: dict[str, bool] | None = None
