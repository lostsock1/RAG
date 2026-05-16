"""phase 2 workflow backend truthfulness

Revision ID: 20260516_0004
Revises: 20260516_0003
Create Date: 2026-05-16 00:04:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260516_0004"
down_revision = "20260516_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ingestion_runs") as batch_op:
        batch_op.alter_column(
            "workflow_backend",
            existing_type=sa.String(length=32),
            server_default="scaffold",
        )


def downgrade() -> None:
    with op.batch_alter_table("ingestion_runs") as batch_op:
        batch_op.alter_column(
            "workflow_backend",
            existing_type=sa.String(length=32),
            server_default="temporal",
        )
