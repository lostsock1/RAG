"""phase 2 ingestion uniqueness constraints

Revision ID: 20260516_0003
Revises: 20260516_0002
Create Date: 2026-05-16 00:03:00
"""

from __future__ import annotations

from alembic import op

revision = "20260516_0003"
down_revision = "20260516_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("parsed_artifacts") as batch_op:
        batch_op.create_unique_constraint("uq_parsed_artifacts_run_id", ["run_id"])

    with op.batch_alter_table("quality_reports") as batch_op:
        batch_op.create_unique_constraint("uq_quality_reports_run_id", ["run_id"])


def downgrade() -> None:
    with op.batch_alter_table("quality_reports") as batch_op:
        batch_op.drop_constraint("uq_quality_reports_run_id", type_="unique")

    with op.batch_alter_table("parsed_artifacts") as batch_op:
        batch_op.drop_constraint("uq_parsed_artifacts_run_id", type_="unique")
