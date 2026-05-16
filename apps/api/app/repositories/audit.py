from __future__ import annotations

from app.db.base import session_factory
from app.db.models.audit import AuditEvent


def build_audit_event(
    *,
    tenant_id: str,
    user_id: str | None,
    action: str,
    resource_type: str | None,
    resource_id: str | None,
    details: dict,
) -> AuditEvent:
    return AuditEvent(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=dict(details),
    )


def write_audit_event(
    *,
    tenant_id: str,
    user_id: str | None,
    action: str,
    resource_type: str | None,
    resource_id: str | None,
    details: dict,
) -> None:
    event = build_audit_event(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
    )

    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                'Audit persistence is not configured: session_factory has no database bind.'
            )

        session.add(event)
        session.commit()
