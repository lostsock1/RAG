"""acl bootstrap policy

Revision ID: 20260519_0007
Revises: 20260517_0006
Create Date: 2026-05-19 12:00:00
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260519_0007"
down_revision = "20260517_0006"
branch_labels = None
depends_on = None


def _uuid_column() -> sa.Uuid:
    return sa.Uuid()


def upgrade() -> None:
    op.create_table(
        "acl_policies",
        sa.Column("id", _uuid_column(), nullable=False),
        sa.Column("tenant_id", _uuid_column(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("default_visibility_mode", sa.String(length=16), nullable=False, server_default="private"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_acl_policies_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_acl_policies")),
        sa.UniqueConstraint("tenant_id", name="uq_acl_policies_tenant_id"),
    )
    op.create_index(op.f("ix_acl_policies_tenant_id"), "acl_policies", ["tenant_id"], unique=False)

    op.create_table(
        "acl_policy_visibility_modes",
        sa.Column("policy_id", _uuid_column(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["policy_id"], ["acl_policies.id"], name=op.f("fk_acl_policy_visibility_modes_policy_id_acl_policies"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("policy_id", "key", name=op.f("pk_acl_policy_visibility_modes")),
    )
    op.create_table(
        "acl_policy_sensitivity_levels",
        sa.Column("policy_id", _uuid_column(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["policy_id"], ["acl_policies.id"], name=op.f("fk_acl_policy_sensitivity_levels_policy_id_acl_policies"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("policy_id", "key", name=op.f("pk_acl_policy_sensitivity_levels")),
    )
    op.create_table(
        "acl_policy_dimensions",
        sa.Column("policy_id", _uuid_column(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["policy_id"], ["acl_policies.id"], name=op.f("fk_acl_policy_dimensions_policy_id_acl_policies"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("policy_id", "key", name=op.f("pk_acl_policy_dimensions")),
    )

    with op.batch_alter_table("acl_grants") as batch_op:
        batch_op.add_column(sa.Column("acl_policy_id", _uuid_column(), nullable=True))
        batch_op.add_column(sa.Column("acl_policy_version", sa.Integer(), nullable=False, server_default=sa.text("1")))
        batch_op.add_column(sa.Column("sensitivity_rank", sa.Integer(), nullable=False, server_default=sa.text("200")))
        batch_op.create_foreign_key(op.f("fk_acl_grants_acl_policy_id_acl_policies"), "acl_policies", ["acl_policy_id"], ["id"])
        batch_op.create_index(op.f("ix_acl_grants_acl_policy_id"), ["acl_policy_id"], unique=False)

    connection = op.get_bind()
    acl_grants = sa.table(
        "acl_grants",
        sa.column("id", _uuid_column()),
        sa.column("tenant_id", _uuid_column()),
        sa.column("sensitivity", sa.String()),
        # Columns added earlier in this same migration via batch_alter_table.
        # They must appear in this sa.table() reflection so the backfill
        # UPDATE below can bind to them. SQLite was lenient; Postgres
        # raises `Unconsumed column names` if these are missing.
        sa.column("acl_policy_id", _uuid_column()),
        sa.column("acl_policy_version", sa.Integer()),
        sa.column("sensitivity_rank", sa.Integer()),
    )
    acl_policies = sa.table(
        "acl_policies",
        sa.column("id", _uuid_column()),
        sa.column("tenant_id", _uuid_column()),
        sa.column("policy_version", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("locked_at", sa.DateTime(timezone=True)),
        sa.column("default_visibility_mode", sa.String()),
    )
    visibility_modes = sa.table(
        "acl_policy_visibility_modes",
        sa.column("policy_id", _uuid_column()),
        sa.column("key", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    sensitivity_levels = sa.table(
        "acl_policy_sensitivity_levels",
        sa.column("policy_id", _uuid_column()),
        sa.column("key", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("rank", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
    )
    dimensions = sa.table(
        "acl_policy_dimensions",
        sa.column("policy_id", _uuid_column()),
        sa.column("key", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )

    sensitivity_rank_map = {"public": 100, "internal": 200, "confidential": 300, "restricted": 400}
    distinct_tenants = [row[0] for row in connection.execute(sa.select(sa.distinct(acl_grants.c.tenant_id))).fetchall()]
    now = datetime.now(timezone.utc)
    for tenant_id in distinct_tenants:
        policy_id = uuid4()
        connection.execute(
            sa.insert(acl_policies).values(
                id=policy_id,
                tenant_id=tenant_id,
                policy_version=1,
                status="locked",
                locked_at=now,
                default_visibility_mode="private",
            )
        )
        connection.execute(
            sa.insert(visibility_modes),
            [
                {"policy_id": policy_id, "key": "private", "display_name": "Private", "is_active": True},
                {"policy_id": policy_id, "key": "group", "display_name": "Group", "is_active": True},
                {"policy_id": policy_id, "key": "tenant", "display_name": "Tenant", "is_active": True},
                {"policy_id": policy_id, "key": "public", "display_name": "Public", "is_active": True},
            ],
        )
        connection.execute(
            sa.insert(sensitivity_levels),
            [
                {"policy_id": policy_id, "key": "public", "display_name": "Public", "rank": 100, "is_active": True},
                {"policy_id": policy_id, "key": "internal", "display_name": "Internal", "rank": 200, "is_active": True},
                {"policy_id": policy_id, "key": "confidential", "display_name": "Confidential", "rank": 300, "is_active": True},
                {"policy_id": policy_id, "key": "restricted", "display_name": "Restricted", "rank": 400, "is_active": True},
            ],
        )
        connection.execute(
            sa.insert(dimensions),
            [
                {"policy_id": policy_id, "key": "user", "display_name": "User", "is_active": True},
                {"policy_id": policy_id, "key": "group", "display_name": "Group", "is_active": True},
                {"policy_id": policy_id, "key": "role", "display_name": "Role", "is_active": False},
                {"policy_id": policy_id, "key": "org_unit", "display_name": "Org Unit", "is_active": False},
                {"policy_id": policy_id, "key": "project", "display_name": "Project", "is_active": False},
            ],
        )

        rows = connection.execute(
            sa.select(acl_grants.c.id, acl_grants.c.sensitivity).where(acl_grants.c.tenant_id == tenant_id)
        ).fetchall()
        for acl_grant_id, sensitivity in rows:
            connection.execute(
                sa.update(acl_grants)
                .where(acl_grants.c.id == acl_grant_id)
                .values(
                    acl_policy_id=policy_id,
                    acl_policy_version=1,
                    sensitivity_rank=sensitivity_rank_map.get(sensitivity, 200),
                )
            )


def downgrade() -> None:
    with op.batch_alter_table("acl_grants") as batch_op:
        batch_op.drop_index(op.f("ix_acl_grants_acl_policy_id"))
        batch_op.drop_constraint(op.f("fk_acl_grants_acl_policy_id_acl_policies"), type_="foreignkey")
        batch_op.drop_column("sensitivity_rank")
        batch_op.drop_column("acl_policy_version")
        batch_op.drop_column("acl_policy_id")

    op.drop_table("acl_policy_dimensions")
    op.drop_table("acl_policy_sensitivity_levels")
    op.drop_table("acl_policy_visibility_modes")
    op.drop_index(op.f("ix_acl_policies_tenant_id"), table_name="acl_policies")
    op.drop_table("acl_policies")
