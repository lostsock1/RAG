from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.db.base import session_factory
from app.db.models.acl import AclAllowedGroup, AclAllowedUser, AclGrant
from app.db.models.audit import AuditEvent
from app.db.models.document import Document
from app.db.models.group import Group
from app.services.acl_service import build_document_acl_filter


@dataclass(slots=True)
class DocumentAclView:
    document_id: UUID
    owner_user_id: UUID
    visibility: str
    allowed_user_ids: list[UUID]
    allowed_group_ids: list[UUID]
    sensitivity: str
    expires_at: datetime | None


@dataclass(slots=True)
class DocumentIndexAclMetadata:
    document_id: UUID
    tenant_id: UUID
    owner_user_id: UUID
    visibility: str
    allowed_user_ids: list[UUID]
    allowed_group_ids: list[UUID]
    sensitivity: str
    expires_at: datetime | None

    def to_payload(self) -> dict[str, object]:
        return {
            "document_id": str(self.document_id),
            "tenant_id": str(self.tenant_id),
            "owner_user_id": str(self.owner_user_id),
            "allowed_user_ids": [str(value) for value in self.allowed_user_ids],
            "group_ids": [str(value) for value in self.allowed_group_ids],
            "visibility": self.visibility,
            "sensitivity": self.sensitivity,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


def _is_admin(roles: list[str]) -> bool:
    return "admin" in roles


def _load_document_acl(session, document_id: UUID) -> DocumentAclView | None:
    acl_grant = session.scalar(select(AclGrant).where(AclGrant.document_id == document_id))
    if acl_grant is None:
        return None

    allowed_user_ids = list(
        session.scalars(
            select(AclAllowedUser.user_id)
            .where(AclAllowedUser.acl_grant_id == acl_grant.id)
            .order_by(AclAllowedUser.user_id)
        )
    )
    allowed_group_ids = list(
        session.scalars(
            select(AclAllowedGroup.group_id)
            .where(AclAllowedGroup.acl_grant_id == acl_grant.id)
            .order_by(AclAllowedGroup.group_id)
        )
    )

    return DocumentAclView(
        document_id=document_id,
        owner_user_id=acl_grant.owner_user_id,
        visibility=acl_grant.visibility,
        allowed_user_ids=allowed_user_ids,
        allowed_group_ids=allowed_group_ids,
        sensitivity=acl_grant.sensitivity,
        expires_at=acl_grant.expires_at,
    )



def get_document_index_acl_metadata(*, document_id: UUID) -> dict[str, object]:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Document persistence is not configured: session_factory has no database bind."
            )

        document = session.scalar(select(Document).where(Document.id == document_id))
        if document is None or document.is_tombstoned:
            raise RuntimeError(
                f"Index ACL metadata could not be loaded: document {document_id} was not found or is tombstoned."
            )

        acl_view = _load_document_acl(session, document_id)
        if acl_view is None:
            raise RuntimeError(
                f"Index ACL metadata could not be loaded: document {document_id} has no ACL grant."
            )

        return DocumentIndexAclMetadata(
            document_id=document.id,
            tenant_id=document.tenant_id,
            owner_user_id=acl_view.owner_user_id,
            visibility=acl_view.visibility,
            allowed_user_ids=acl_view.allowed_user_ids,
            allowed_group_ids=acl_view.allowed_group_ids,
            sensitivity=acl_view.sensitivity,
            expires_at=acl_view.expires_at,
        ).to_payload()


def create_document_with_owner_acl(
    *,
    tenant_id: UUID,
    owner_user_id: UUID,
    title: str,
    source_type: str,
    source_hash: str,
    file_name: str,
    file_size_bytes: int,
    object_key: str,
    document_type: str | None = None,
    language: str | None = None,
) -> Document:
    document = Document(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        title=title,
        source_type=source_type,
        document_type=document_type,
        language=language,
        source_hash=source_hash,
        file_name=file_name,
        file_size_bytes=file_size_bytes,
        object_key=object_key,
        ingestion_status="uploaded",
    )

    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Document persistence is not configured: session_factory has no database bind."
            )

        session.add(document)
        session.flush()

        acl_grant = AclGrant(
            document_id=document.id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            visibility="private",
            sensitivity="internal",
        )
        session.add(acl_grant)
        session.flush()

        session.add(AclAllowedUser(acl_grant_id=acl_grant.id, user_id=owner_user_id))
        session.commit()
        session.refresh(document)

    return document


def get_or_create_document_by_source_hash(
    *,
    tenant_id: UUID,
    owner_user_id: UUID,
    title: str,
    source_type: str,
    source_hash: str,
    file_name: str,
    file_size_bytes: int,
    object_key: str,
    document_type: str | None = None,
    language: str | None = None,
) -> Document:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Document persistence is not configured: session_factory has no database bind."
            )

        existing_document = session.scalar(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.owner_user_id == owner_user_id,
                Document.source_hash == source_hash,
                Document.is_tombstoned.is_(False),
            )
        )
        if existing_document is not None:
            return existing_document

    try:
        return create_document_with_owner_acl(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            title=title,
            source_type=source_type,
            document_type=document_type,
            language=language,
            source_hash=source_hash,
            file_name=file_name,
            file_size_bytes=file_size_bytes,
            object_key=object_key,
        )
    except IntegrityError:
        existing_document = get_live_document_by_source_hash(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            source_hash=source_hash,
        )
        if existing_document is None:
            raise
        return existing_document


def get_live_document_by_source_hash(*, tenant_id: UUID, owner_user_id: UUID, source_hash: str) -> Document | None:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Document persistence is not configured: session_factory has no database bind."
            )

        return session.scalar(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.owner_user_id == owner_user_id,
                Document.source_hash == source_hash,
                Document.is_tombstoned.is_(False),
            )
        )


def resolve_group_ids_for_context(*, session, tenant_id: UUID, group_ids: list[str]) -> list[UUID]:
    resolved_group_ids: list[UUID] = []
    unresolved_group_names: list[str] = []

    for group_id in group_ids:
        try:
            resolved_group_ids.append(UUID(group_id))
        except ValueError:
            unresolved_group_names.append(group_id)

    if unresolved_group_names:
        resolved_group_ids.extend(
            session.scalars(
                select(Group.id).where(
                    Group.tenant_id == tenant_id,
                    Group.name.in_(unresolved_group_names),
                )
            ).all()
        )

    return resolved_group_ids


def list_documents_for_context(*, tenant_id: str, user_id: str, group_ids: list[str]) -> list[Document]:
    tenant_uuid = UUID(tenant_id)
    user_uuid = UUID(user_id)

    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Document persistence is not configured: session_factory has no database bind."
            )

        group_uuids = resolve_group_ids_for_context(
            session=session,
            tenant_id=tenant_uuid,
            group_ids=group_ids,
        )

        documents = session.scalars(
            select(Document)
            .join(AclGrant, AclGrant.document_id == Document.id)
            .where(
                build_document_acl_filter(
                    tenant_id=tenant_uuid,
                    user_id=user_uuid,
                    group_ids=group_uuids,
                )
            )
            .order_by(Document.created_at.asc(), Document.title.asc())
        ).all()

        return list(documents)


def get_document_acl(
    *,
    document_id: UUID,
    tenant_id: str,
    user_id: str,
    roles: list[str],
) -> DocumentAclView | None:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Document persistence is not configured: session_factory has no database bind."
            )

        document = session.scalar(select(Document).where(Document.id == document_id))
        if document is None or str(document.tenant_id) != tenant_id:
            return None
        if str(document.owner_user_id) != user_id and not _is_admin(roles):
            return None

        return _load_document_acl(session, document_id)


def update_document_acl(
    *,
    document_id: UUID,
    tenant_id: str,
    user_id: str,
    roles: list[str],
    visibility: str,
    allowed_user_ids: list[UUID],
    allowed_group_ids: list[UUID],
    sensitivity: str,
    expires_at: datetime | None,
) -> DocumentAclView | None:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Document persistence is not configured: session_factory has no database bind."
            )

        document = session.scalar(select(Document).where(Document.id == document_id))
        if document is None or str(document.tenant_id) != tenant_id:
            return None
        if str(document.owner_user_id) != user_id and not _is_admin(roles):
            return None

        acl_grant = session.scalar(select(AclGrant).where(AclGrant.document_id == document_id))
        if acl_grant is None:
            return None

        acl_grant.visibility = visibility
        acl_grant.sensitivity = sensitivity
        acl_grant.expires_at = expires_at

        session.execute(delete(AclAllowedUser).where(AclAllowedUser.acl_grant_id == acl_grant.id))
        session.execute(delete(AclAllowedGroup).where(AclAllowedGroup.acl_grant_id == acl_grant.id))

        owner_user_id = document.owner_user_id
        user_ids = {owner_user_id, *allowed_user_ids}
        group_id_set = set(allowed_group_ids)

        session.add_all(
            [
                AclAllowedUser(acl_grant_id=acl_grant.id, user_id=allowed_user_id)
                for allowed_user_id in sorted(user_ids)
            ]
        )
        session.add_all(
            [
                AclAllowedGroup(acl_grant_id=acl_grant.id, group_id=allowed_group_id)
                for allowed_group_id in sorted(group_id_set)
            ]
        )
        session.add(
            AuditEvent(
                tenant_id=document.tenant_id,
                user_id=UUID(user_id),
                action="acl.update",
                resource_type="document",
                resource_id=document.id,
                details={
                    "visibility": visibility,
                    "allowed_user_ids": [str(value) for value in sorted(user_ids)],
                    "allowed_group_ids": [str(value) for value in sorted(group_id_set)],
                    "sensitivity": sensitivity,
                },
            )
        )
        session.commit()

        acl_view = _load_document_acl(session, document_id)
        assert acl_view is not None
        return acl_view


def write_document_upload_audit_event(
    *,
    tenant_id: UUID,
    user_id: UUID,
    document_id: UUID,
    title: str,
    source_type: str,
    source_hash: str,
    object_key: str,
    ingestion_status: str,
    ingestion_run_id: UUID | None = None,
) -> None:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Audit persistence is not configured: session_factory has no database bind."
            )

        details = {
            "title": title,
            "source_type": source_type,
            "source_hash": source_hash,
            "object_key": object_key,
            "ingestion_status": ingestion_status,
        }
        if ingestion_run_id is not None:
            details["ingestion_run_id"] = str(ingestion_run_id)

        session.add(
            AuditEvent(
                tenant_id=tenant_id,
                user_id=user_id,
                action="document.upload",
                resource_type="document",
                resource_id=document_id,
                details=details,
            )
        )
        session.commit()


def write_document_list_audit_event(*, tenant_id: str, user_id: str, document_ids: list[UUID]) -> None:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Audit persistence is not configured: session_factory has no database bind."
            )

        session.add(
            AuditEvent(
                tenant_id=UUID(tenant_id),
                user_id=UUID(user_id),
                action="document.list",
                resource_type="document",
                resource_id=None,
                details={
                    "filters_applied": ["acl"],
                    "document_ids": [str(document_id) for document_id in document_ids],
                    "document_count": len(document_ids),
                },
            )
        )
        session.commit()
