from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(length=1024), nullable=False)
    source_type: Mapped[str] = mapped_column(String(length=32), nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
    language: Mapped[str | None] = mapped_column(String(length=8), nullable=True)
    source_hash: Mapped[str] = mapped_column(String(length=128), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(length=1024), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    object_key: Mapped[str | None] = mapped_column(String(length=1024), nullable=True)
    ingestion_status: Mapped[str] = mapped_column(String(length=32), nullable=False, default="uploaded", server_default="uploaded")
    parser_version: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(length=128), nullable=True)
    is_tombstoned: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default=text("false"))
    tombstoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
