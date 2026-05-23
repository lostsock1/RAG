from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, inet_type, json_type


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(length=64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
    resource_id: Mapped[UUID | None] = mapped_column(nullable=True)
    details: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict, server_default="{}")
    ip_address: Mapped[str | None] = mapped_column(inet_type(), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
