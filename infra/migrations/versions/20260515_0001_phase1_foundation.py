"""phase 1 foundation schema

Revision ID: 20260515_0001
Revises: 
Create Date: 2026-05-15 00:01:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260515_0001"
down_revision = None
branch_labels = None
depends_on = None

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.String()), "postgresql")
inet_type = sa.String(length=45).with_variant(postgresql.INET(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenants_slug")),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("roles", json_type, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_users_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("tenant_id", "email", name=op.f("uq_users_tenant_id")),
    )
    op.create_index(op.f("ix_users_tenant_id"), "users", ["tenant_id"], unique=False)

    op.create_table(
        "groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_groups_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_groups")),
        sa.UniqueConstraint("tenant_id", "name", name=op.f("uq_groups_tenant_id")),
    )
    op.create_index(op.f("ix_groups_tenant_id"), "groups", ["tenant_id"], unique=False)

    op.create_table(
        "user_groups",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], name=op.f("fk_user_groups_group_id_groups")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_groups_user_id_users")),
        sa.PrimaryKeyConstraint("user_id", "group_id", name=op.f("pk_user_groups")),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("document_type", sa.String(length=64), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("source_hash", sa.String(length=128), nullable=False),
        sa.Column("file_name", sa.String(length=1024), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("object_key", sa.String(length=1024), nullable=True),
        sa.Column("ingestion_status", sa.String(length=32), nullable=False, server_default="uploaded"),
        sa.Column("parser_version", sa.String(length=64), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
        sa.Column("is_tombstoned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], name=op.f("fk_documents_owner_user_id_users")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_documents_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(op.f("ix_documents_owner_user_id"), "documents", ["owner_user_id"], unique=False)
    op.create_index(op.f("ix_documents_tenant_id"), "documents", ["tenant_id"], unique=False)

    op.create_table(
        "acl_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default="private"),
        sa.Column("sensitivity", sa.String(length=16), nullable=False, server_default="internal"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_acl_grants_document_id_documents"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], name=op.f("fk_acl_grants_owner_user_id_users")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_acl_grants_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_acl_grants")),
    )
    op.create_index(op.f("ix_acl_grants_document_id"), "acl_grants", ["document_id"], unique=False)
    op.create_index(op.f("ix_acl_grants_owner_user_id"), "acl_grants", ["owner_user_id"], unique=False)
    op.create_index(op.f("ix_acl_grants_tenant_id"), "acl_grants", ["tenant_id"], unique=False)

    op.create_table(
        "acl_allowed_users",
        sa.Column("acl_grant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["acl_grant_id"], ["acl_grants.id"], name=op.f("fk_acl_allowed_users_acl_grant_id_acl_grants"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_acl_allowed_users_user_id_users")),
        sa.PrimaryKeyConstraint("acl_grant_id", "user_id", name=op.f("pk_acl_allowed_users")),
    )

    op.create_table(
        "acl_allowed_groups",
        sa.Column("acl_grant_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["acl_grant_id"], ["acl_grants.id"], name=op.f("fk_acl_allowed_groups_acl_grant_id_acl_grants"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], name=op.f("fk_acl_allowed_groups_group_id_groups")),
        sa.PrimaryKeyConstraint("acl_grant_id", "group_id", name=op.f("pk_acl_allowed_groups")),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("details", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("ip_address", inet_type, nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name=op.f("fk_audit_events_tenant_id_tenants")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_audit_events_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_tenant_id"), "audit_events", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_audit_events_tenant_id_timestamp"), "audit_events", ["tenant_id", "timestamp"], unique=False)
    op.create_index(op.f("ix_audit_events_user_id"), "audit_events", ["user_id"], unique=False)
    op.create_index(op.f("ix_audit_events_user_id_timestamp"), "audit_events", ["user_id", "timestamp"], unique=False)
    op.create_index(op.f("ix_audit_events_resource_type_resource_id"), "audit_events", ["resource_type", "resource_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_events_resource_type_resource_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_user_id_timestamp"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_user_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_tenant_id_timestamp"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_tenant_id"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("acl_allowed_groups")
    op.drop_table("acl_allowed_users")
    op.drop_index(op.f("ix_acl_grants_tenant_id"), table_name="acl_grants")
    op.drop_index(op.f("ix_acl_grants_owner_user_id"), table_name="acl_grants")
    op.drop_index(op.f("ix_acl_grants_document_id"), table_name="acl_grants")
    op.drop_table("acl_grants")
    op.drop_index(op.f("ix_documents_tenant_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_owner_user_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_table("user_groups")
    op.drop_index(op.f("ix_groups_tenant_id"), table_name="groups")
    op.drop_table("groups")
    op.drop_index(op.f("ix_users_tenant_id"), table_name="users")
    op.drop_table("users")
    op.drop_table("tenants")
