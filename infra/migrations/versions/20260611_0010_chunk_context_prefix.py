"""context_prefix column for chunks (ADR-0020 contextual augmentation)

Revision ID: 20260611_0010
Revises: 20260523_0009
Create Date: 2026-06-11 00:10:00

Adds a nullable context_prefix (Text) column to chunks. When contextual
augmentation is enabled at ingest, this holds the breadcrumb or
LLM-generated situating context that is prepended to the chunk text for
embedding and BM25 indexing only — the original ``text`` column remains the
display/citation text. NULL means no augmentation (the default), in which
case the searchable representation is identical to ``text``.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260611_0010"
down_revision = "20260523_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chunks",
        sa.Column("context_prefix", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chunks", "context_prefix")
