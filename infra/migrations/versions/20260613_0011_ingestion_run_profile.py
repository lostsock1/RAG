"""profile column for ingestion_runs (F2 — document profile selection)

Revision ID: 20260613_0011
Revises: 20260611_0010
Create Date: 2026-06-13 00:11:00

Adds a NOT NULL profile column (loose|book) to ingestion_runs, defaulting to
"loose". The document profile is chosen at upload and snapshotted on the run
(peer of parser_backend / workflow_backend / source_hash); run_chunk_stage
reads it to select the chunker (ADR-0012). The server_default backfills any
pre-existing runs to "loose", matching the prior behaviour where only
non-loose source_types were chunked as books.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260613_0011"
down_revision = "20260611_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_runs",
        sa.Column(
            "profile",
            sa.String(length=16),
            nullable=False,
            server_default="loose",
        ),
    )


def downgrade() -> None:
    op.drop_column("ingestion_runs", "profile")
