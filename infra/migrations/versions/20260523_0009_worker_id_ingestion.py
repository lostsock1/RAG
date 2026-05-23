"""worker_id columns for ingestion_runs and ingestion_stages

Revision ID: 20260523_0009
Revises: 20260523_0008
Create Date: 2026-05-23 00:09:00

Adds a nullable worker_id (UUID) column to ingestion_runs and
ingestion_stages so that recover_orphaned_runs can distinguish runs
belonging to the current process from runs belonging to other (possibly
still-live) processes.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260523_0009"
down_revision = "20260523_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_runs",
        sa.Column("worker_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "ingestion_stages",
        sa.Column("worker_id", sa.Uuid(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ingestion_stages", "worker_id")
    op.drop_column("ingestion_runs", "worker_id")
