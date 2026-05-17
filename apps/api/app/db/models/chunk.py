from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, json_type


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_chunks_document_chunk_index",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_type: Mapped[str] = mapped_column(String(length=32), nullable=False)
    heading_path: Mapped[dict] = mapped_column(json_type(), nullable=False, default=list, server_default="[]")
    page_start: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    text: Mapped[str] = mapped_column(Text(), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("chunks.id"), nullable=True, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer(), nullable=False)
    is_tombstoned: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
