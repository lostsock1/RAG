"""ingestion reliability hardening

Revision ID: 20260517_0005
Revises: 20260516_0004
Create Date: 2026-05-17 00:05:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260517_0005"
down_revision = "20260516_0004"
branch_labels = None
depends_on = None


documents = sa.table(
    "documents",
    sa.column("id", sa.String()),
    sa.column("tenant_id", sa.String()),
    sa.column("owner_user_id", sa.String()),
    sa.column("source_hash", sa.String()),
    sa.column("is_tombstoned", sa.Boolean()),
    sa.column("tombstoned_at", sa.DateTime(timezone=True)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)

ingestion_stages = sa.table(
    "ingestion_stages",
    sa.column("id", sa.String()),
    sa.column("run_id", sa.String()),
    sa.column("stage_name", sa.String()),
    sa.column("created_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    connection = op.get_bind()

    ranked_documents = (
        sa.select(
            documents.c.id,
            sa.func.row_number()
            .over(
                partition_by=(
                    documents.c.tenant_id,
                    documents.c.owner_user_id,
                    documents.c.source_hash,
                ),
                order_by=(documents.c.created_at.asc(), documents.c.id.asc()),
            )
            .label("duplicate_rank"),
        )
        .where(documents.c.is_tombstoned.is_(False))
        .cte("ranked_documents")
    )

    connection.execute(
        sa.update(documents)
        .where(
            documents.c.id.in_(
                sa.select(ranked_documents.c.id).where(ranked_documents.c.duplicate_rank > 1)
            )
        )
        .values(
            is_tombstoned=True,
            tombstoned_at=sa.func.coalesce(documents.c.tombstoned_at, sa.func.current_timestamp()),
            updated_at=sa.func.current_timestamp(),
        )
    )

    ranked_stages = (
        sa.select(
            ingestion_stages.c.id,
            sa.func.row_number()
            .over(
                partition_by=(ingestion_stages.c.run_id, ingestion_stages.c.stage_name),
                order_by=(ingestion_stages.c.created_at.asc(), ingestion_stages.c.id.asc()),
            )
            .label("duplicate_rank"),
        )
        .cte("ranked_stages")
    )

    connection.execute(
        sa.delete(ingestion_stages).where(
            ingestion_stages.c.id.in_(
                sa.select(ranked_stages.c.id).where(ranked_stages.c.duplicate_rank > 1)
            )
        )
    )

    op.create_index(
        "ix_documents_live_owner_hash",
        "documents",
        ["tenant_id", "owner_user_id", "source_hash"],
        unique=True,
        sqlite_where=sa.text("is_tombstoned IS FALSE"),
        postgresql_where=sa.text("is_tombstoned IS FALSE"),
    )

    with op.batch_alter_table("ingestion_stages") as batch_op:
        batch_op.create_unique_constraint(
            "uq_ingestion_stages_run_stage_name",
            ["run_id", "stage_name"],
        )


def downgrade() -> None:
    with op.batch_alter_table("ingestion_stages") as batch_op:
        batch_op.drop_constraint("uq_ingestion_stages_run_stage_name", type_="unique")

    op.drop_index("ix_documents_live_owner_hash", table_name="documents")
