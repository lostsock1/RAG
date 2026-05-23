"""chunks postgres compat — fix UUID column types and boolean server_default

Revision ID: 20260523_0008
Revises: 20260519_0007
Create Date: 2026-05-23 00:08:00

On Postgres the chunks table was created with String columns for id,
document_id, and parent_id, but documents.id is uuid.  The FK
chunks.document_id (varchar) → documents.id (uuid) is invalid on Postgres
and alembic upgrade head will refuse.  Additionally is_tombstoned used
server_default="0" which is not a valid Postgres boolean literal.

This migration is a no-op on SQLite (TEXT is used for UUIDs there and the
schema is already consistent).  On Postgres it:
  1. Drops the FK and PK constraints.
  2. Alters id, document_id, parent_id to uuid using USING casts.
  3. Re-creates the PK and FK constraints.
  4. Fixes is_tombstoned server_default to 'false'.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260523_0008"
down_revision = "20260519_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite uses TEXT for UUIDs — no changes needed.
        return

    # 1. Drop FK constraints that reference the columns we are altering.
    op.drop_constraint("fk_chunks_document_id_documents", "chunks", type_="foreignkey")
    op.drop_constraint("fk_chunks_parent_id_chunks", "chunks", type_="foreignkey")

    # 2. Drop the primary key constraint.
    op.drop_constraint("pk_chunks", "chunks", type_="primary")

    # 3. Alter column types to uuid.
    op.alter_column(
        "chunks",
        "id",
        type_=sa.Uuid(),
        postgresql_using="id::uuid",
        nullable=False,
    )
    op.alter_column(
        "chunks",
        "document_id",
        type_=sa.Uuid(),
        postgresql_using="document_id::uuid",
        nullable=False,
    )
    op.alter_column(
        "chunks",
        "parent_id",
        type_=sa.Uuid(),
        postgresql_using="parent_id::uuid",
        nullable=True,
    )

    # 4. Re-create PK.
    op.create_primary_key("pk_chunks", "chunks", ["id"])

    # 5. Re-create FK constraints.
    op.create_foreign_key(
        "fk_chunks_document_id_documents",
        "chunks",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_chunks_parent_id_chunks",
        "chunks",
        "chunks",
        ["parent_id"],
        ["id"],
    )

    # 6. Fix is_tombstoned server_default.
    op.alter_column(
        "chunks",
        "is_tombstoned",
        server_default=sa.text("false"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Reverse: drop FK/PK, cast back to varchar, re-create constraints.
    op.drop_constraint("fk_chunks_document_id_documents", "chunks", type_="foreignkey")
    op.drop_constraint("fk_chunks_parent_id_chunks", "chunks", type_="foreignkey")
    op.drop_constraint("pk_chunks", "chunks", type_="primary")

    op.alter_column(
        "chunks",
        "id",
        type_=sa.String(),
        postgresql_using="id::text",
        nullable=False,
    )
    op.alter_column(
        "chunks",
        "document_id",
        type_=sa.String(),
        postgresql_using="document_id::text",
        nullable=False,
    )
    op.alter_column(
        "chunks",
        "parent_id",
        type_=sa.String(),
        postgresql_using="parent_id::text",
        nullable=True,
    )

    op.create_primary_key("pk_chunks", "chunks", ["id"])
    op.create_foreign_key(
        "fk_chunks_document_id_documents",
        "chunks",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_chunks_parent_id_chunks",
        "chunks",
        "chunks",
        ["parent_id"],
        ["id"],
    )
    op.alter_column(
        "chunks",
        "is_tombstoned",
        server_default="0",
    )
