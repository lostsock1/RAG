from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AclPolicy(Base):
    __tablename__ = "acl_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_acl_policies_tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    policy_version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(length=16), nullable=False, default="draft", server_default="draft")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    default_visibility_mode: Mapped[str] = mapped_column(
        String(length=16),
        nullable=False,
        default="private",
        server_default="private",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AclPolicyVisibilityMode(Base):
    __tablename__ = "acl_policy_visibility_modes"

    policy_id: Mapped[UUID] = mapped_column(ForeignKey("acl_policies.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(length=32), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(length=64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True, server_default=text("true"))


class AclPolicySensitivityLevel(Base):
    __tablename__ = "acl_policy_sensitivity_levels"

    policy_id: Mapped[UUID] = mapped_column(ForeignKey("acl_policies.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(length=32), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(length=64), nullable=False)
    rank: Mapped[int] = mapped_column(Integer(), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True, server_default=text("true"))


class AclPolicyDimension(Base):
    __tablename__ = "acl_policy_dimensions"

    policy_id: Mapped[UUID] = mapped_column(ForeignKey("acl_policies.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(length=32), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(length=64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default=text("false"))


class AclGrant(Base):
    __tablename__ = "acl_grants"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    acl_policy_id: Mapped[UUID | None] = mapped_column(ForeignKey("acl_policies.id"), index=True)
    acl_policy_version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1, server_default=text("1"))
    visibility: Mapped[str] = mapped_column(
        String(length=16),
        nullable=False,
        default="private",
        server_default="private",
    )
    sensitivity: Mapped[str] = mapped_column(
        String(length=16),
        nullable=False,
        default="internal",
        server_default="internal",
    )
    sensitivity_rank: Mapped[int] = mapped_column(Integer(), nullable=False, default=200, server_default=text("200"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AclAllowedUser(Base):
    __tablename__ = "acl_allowed_users"

    acl_grant_id: Mapped[UUID] = mapped_column(
        ForeignKey("acl_grants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)


class AclAllowedGroup(Base):
    __tablename__ = "acl_allowed_groups"

    acl_grant_id: Mapped[UUID] = mapped_column(
        ForeignKey("acl_grants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    group_id: Mapped[UUID] = mapped_column(ForeignKey("groups.id"), primary_key=True)
