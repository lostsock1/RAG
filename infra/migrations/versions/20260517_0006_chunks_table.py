"""chunks table

Revision ID: 20260517_0006
Revises: 20260517_0005
Create Date: 2026-05-17 00:06:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260517_0006"
down_revision = "20260517_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chunks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("unit_type", sa.String(length=32), nullable=False),
        sa.Column("heading_path", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("is_tombstoned", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_chunks_document_id_documents"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["chunks.id"], name=op.f("fk_chunks_parent_id_chunks")),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_chunk_index"),
    )
    op.create_index(op.f("ix_chunks_document_id"), "chunks", ["document_id"])
    op.create_index(op.f("ix_chunks_parent_id"), "chunks", ["parent_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_chunks_parent_id"), table_name="chunks")
    op.drop_index(op.f("ix_chunks_document_id"), table_name="chunks")
    op.drop_table("chunks")
