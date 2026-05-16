from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, exists, false, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.acl import AclAllowedGroup, AclAllowedUser, AclGrant
from app.db.models.document import Document


def build_document_acl_filter(
    tenant_id: UUID | str,
    user_id: UUID | str,
    group_ids: list[UUID] | list[str],
) -> ColumnElement[bool]:
    """Return a SQLAlchemy filter for the Phase 1 document ACL rules."""
    has_explicit_user_grant = exists(
        select(1).where(
            AclAllowedUser.acl_grant_id == AclGrant.id,
            AclAllowedUser.user_id == user_id,
        )
    )

    has_matching_group_grant: ColumnElement[bool] = false()
    if group_ids:
        has_matching_group_grant = exists(
            select(1).where(
                AclAllowedGroup.acl_grant_id == AclGrant.id,
                AclAllowedGroup.group_id.in_(group_ids),
            )
        )

    has_access = or_(
        Document.owner_user_id == user_id,
        AclGrant.owner_user_id == user_id,
        has_explicit_user_grant,
        has_matching_group_grant,
        AclGrant.visibility == "tenant",
    )
    is_unexpired_acl = or_(AclGrant.expires_at.is_(None), AclGrant.expires_at > datetime.now(UTC))

    return and_(
        Document.id == AclGrant.document_id,
        Document.tenant_id == tenant_id,
        AclGrant.tenant_id == tenant_id,
        Document.is_tombstoned.is_(False),
        is_unexpired_acl,
        has_access,
    )
