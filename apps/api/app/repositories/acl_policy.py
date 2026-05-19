from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.db.base import session_factory
from app.db.acl_models import (
    AclPolicy,
    AclPolicyDimension,
    AclPolicySensitivityLevel,
    AclPolicyVisibilityMode,
)


class AclPolicyLockedError(RuntimeError):
    pass


@dataclass(slots=True)
class AclPolicyNamedValue:
    key: str
    display_name: str
    is_active: bool
    rank: int | None = None


@dataclass(slots=True)
class TenantAclPolicyView:
    policy_id: UUID
    tenant_id: UUID
    policy_version: int
    status: str
    locked_at: datetime | None
    default_visibility_mode: str
    visibility_modes: dict[str, AclPolicyNamedValue]
    sensitivity_levels: dict[str, AclPolicyNamedValue]
    dimensions: dict[str, AclPolicyNamedValue]


_DEFAULT_VISIBILITY_MODES = {
    "private": ("Private", True),
    "group": ("Group", True),
    "tenant": ("Tenant", True),
    "public": ("Public", True),
}
_DEFAULT_SENSITIVITY_LEVELS = {
    "public": ("Public", 100, True),
    "internal": ("Internal", 200, True),
    "confidential": ("Confidential", 300, True),
    "restricted": ("Restricted", 400, True),
}
_DEFAULT_DIMENSIONS = {
    "user": ("User", True),
    "group": ("Group", True),
    "role": ("Role", False),
    "org_unit": ("Org Unit", False),
    "project": ("Project", False),
}


def _require_known_keys(*, label: str, provided_keys: set[str], allowed_keys: set[str]) -> None:
    unknown_keys = sorted(provided_keys - allowed_keys)
    if unknown_keys:
        raise ValueError(
            f"Unknown ACL policy {label} key(s): {', '.join(unknown_keys)}. Allowed keys: {', '.join(sorted(allowed_keys))}."
        )


def _get_policy(session, *, tenant_id: UUID) -> AclPolicy | None:
    return session.scalar(select(AclPolicy).where(AclPolicy.tenant_id == tenant_id))


def _create_default_policy(session, *, tenant_id: UUID) -> AclPolicy:
    policy = AclPolicy(tenant_id=tenant_id, policy_version=1, status="draft", default_visibility_mode="private")
    session.add(policy)
    session.flush()

    session.add_all(
        [
            AclPolicyVisibilityMode(policy_id=policy.id, key=key, display_name=display_name, is_active=is_active)
            for key, (display_name, is_active) in _DEFAULT_VISIBILITY_MODES.items()
        ]
    )
    session.add_all(
        [
            AclPolicySensitivityLevel(
                policy_id=policy.id,
                key=key,
                display_name=display_name,
                rank=rank,
                is_active=is_active,
            )
            for key, (display_name, rank, is_active) in _DEFAULT_SENSITIVITY_LEVELS.items()
        ]
    )
    session.add_all(
        [
            AclPolicyDimension(policy_id=policy.id, key=key, display_name=display_name, is_active=is_active)
            for key, (display_name, is_active) in _DEFAULT_DIMENSIONS.items()
        ]
    )
    session.flush()
    return policy


def _serialize_policy(session, *, policy: AclPolicy) -> TenantAclPolicyView:
    visibility_modes = {
        row.key: AclPolicyNamedValue(key=row.key, display_name=row.display_name, is_active=row.is_active)
        for row in session.scalars(
            select(AclPolicyVisibilityMode).where(AclPolicyVisibilityMode.policy_id == policy.id)
        ).all()
    }
    sensitivity_levels = {
        row.key: AclPolicyNamedValue(
            key=row.key,
            display_name=row.display_name,
            is_active=row.is_active,
            rank=row.rank,
        )
        for row in session.scalars(
            select(AclPolicySensitivityLevel).where(AclPolicySensitivityLevel.policy_id == policy.id)
        ).all()
    }
    dimensions = {
        row.key: AclPolicyNamedValue(key=row.key, display_name=row.display_name, is_active=row.is_active)
        for row in session.scalars(
            select(AclPolicyDimension).where(AclPolicyDimension.policy_id == policy.id)
        ).all()
    }
    return TenantAclPolicyView(
        policy_id=policy.id,
        tenant_id=policy.tenant_id,
        policy_version=policy.policy_version,
        status=policy.status,
        locked_at=policy.locked_at,
        default_visibility_mode=policy.default_visibility_mode,
        visibility_modes=visibility_modes,
        sensitivity_levels=sensitivity_levels,
        dimensions=dimensions,
    )


def _apply_overrides(
    session,
    *,
    policy: AclPolicy,
    default_visibility_mode: str | None,
    visibility_display_names: dict[str, str] | None,
    visibility_active_flags: dict[str, bool] | None,
    sensitivity_display_names: dict[str, str] | None,
    dimension_display_names: dict[str, str] | None,
    dimension_active_flags: dict[str, bool] | None,
) -> None:
    visibility_rows = {
        row.key: row
        for row in session.scalars(
            select(AclPolicyVisibilityMode).where(AclPolicyVisibilityMode.policy_id == policy.id)
        ).all()
    }
    sensitivity_rows = {
        row.key: row
        for row in session.scalars(
            select(AclPolicySensitivityLevel).where(AclPolicySensitivityLevel.policy_id == policy.id)
        ).all()
    }
    dimension_rows = {
        row.key: row
        for row in session.scalars(
            select(AclPolicyDimension).where(AclPolicyDimension.policy_id == policy.id)
        ).all()
    }

    visibility_keys = set(visibility_rows)
    sensitivity_keys = set(sensitivity_rows)
    dimension_keys = set(dimension_rows)

    if visibility_display_names:
        _require_known_keys(
            label="visibility_display_names",
            provided_keys=set(visibility_display_names),
            allowed_keys=visibility_keys,
        )
    if visibility_active_flags:
        _require_known_keys(
            label="visibility_active_flags",
            provided_keys=set(visibility_active_flags),
            allowed_keys=visibility_keys,
        )
    if sensitivity_display_names:
        _require_known_keys(
            label="sensitivity_display_names",
            provided_keys=set(sensitivity_display_names),
            allowed_keys=sensitivity_keys,
        )
    if dimension_display_names:
        _require_known_keys(
            label="dimension_display_names",
            provided_keys=set(dimension_display_names),
            allowed_keys=dimension_keys,
        )
    if dimension_active_flags:
        _require_known_keys(
            label="dimension_active_flags",
            provided_keys=set(dimension_active_flags),
            allowed_keys=dimension_keys,
        )
    if default_visibility_mode is not None and default_visibility_mode not in visibility_keys:
        raise ValueError(
            f"Unknown ACL policy default visibility '{default_visibility_mode}'. Allowed keys: {', '.join(sorted(visibility_keys))}."
        )

    if visibility_display_names:
        for key, display_name in visibility_display_names.items():
            visibility_rows[key].display_name = display_name
    if visibility_active_flags:
        for key, is_active in visibility_active_flags.items():
            visibility_rows[key].is_active = is_active
    if sensitivity_display_names:
        for key, display_name in sensitivity_display_names.items():
            sensitivity_rows[key].display_name = display_name
    if dimension_display_names:
        for key, display_name in dimension_display_names.items():
            dimension_rows[key].display_name = display_name
    if dimension_active_flags:
        for key, is_active in dimension_active_flags.items():
            dimension_rows[key].is_active = is_active

    if default_visibility_mode is not None:
        visibility_row = visibility_rows[default_visibility_mode]
        if not visibility_row.is_active:
            raise ValueError(f"ACL policy default visibility '{default_visibility_mode}' must be active.")
        policy.default_visibility_mode = default_visibility_mode


def configure_tenant_acl_policy(
    *,
    tenant_id: UUID,
    default_visibility_mode: str | None = None,
    visibility_display_names: dict[str, str] | None = None,
    visibility_active_flags: dict[str, bool] | None = None,
    sensitivity_display_names: dict[str, str] | None = None,
    dimension_display_names: dict[str, str] | None = None,
    dimension_active_flags: dict[str, bool] | None = None,
) -> TenantAclPolicyView:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError("ACL policy persistence is not configured: session_factory has no database bind.")

        policy = _get_policy(session, tenant_id=tenant_id)
        if policy is None:
            policy = _create_default_policy(session, tenant_id=tenant_id)
        elif policy.status == "locked":
            raise AclPolicyLockedError(
                "ACL bootstrap policy is locked because ingestion has already started for this tenant."
            )

        _apply_overrides(
            session,
            policy=policy,
            default_visibility_mode=default_visibility_mode,
            visibility_display_names=visibility_display_names,
            visibility_active_flags=visibility_active_flags,
            sensitivity_display_names=sensitivity_display_names,
            dimension_display_names=dimension_display_names,
            dimension_active_flags=dimension_active_flags,
        )
        session.commit()
        session.refresh(policy)
        return _serialize_policy(session, policy=policy)


def get_tenant_acl_policy(*, tenant_id: UUID) -> TenantAclPolicyView | None:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError("ACL policy persistence is not configured: session_factory has no database bind.")

        policy = _get_policy(session, tenant_id=tenant_id)
        if policy is None:
            return None
        return _serialize_policy(session, policy=policy)


def ensure_tenant_acl_policy_locked_for_session(session, *, tenant_id: UUID) -> AclPolicy:
    policy = _get_policy(session, tenant_id=tenant_id)
    if policy is None:
        policy = _create_default_policy(session, tenant_id=tenant_id)
    if policy.status != "locked":
        policy.status = "locked"
        policy.locked_at = datetime.now(timezone.utc)
        session.flush()
    return policy


def lock_tenant_acl_policy(*, tenant_id: UUID) -> TenantAclPolicyView:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError("ACL policy persistence is not configured: session_factory has no database bind.")

        policy = ensure_tenant_acl_policy_locked_for_session(session, tenant_id=tenant_id)
        session.commit()
        session.refresh(policy)
        return _serialize_policy(session, policy=policy)


def get_policy_sensitivity_rank_for_session(session, *, policy_id: UUID, sensitivity: str) -> int:
    sensitivity_level = session.scalar(
        select(AclPolicySensitivityLevel).where(
            AclPolicySensitivityLevel.policy_id == policy_id,
            AclPolicySensitivityLevel.key == sensitivity,
        )
    )
    if sensitivity_level is None:
        raise ValueError(f"ACL sensitivity '{sensitivity}' is not defined in policy {policy_id}.")
    if not sensitivity_level.is_active:
        raise ValueError(f"ACL sensitivity '{sensitivity}' is inactive in policy {policy_id}.")
    return sensitivity_level.rank


def validate_policy_visibility_for_session(session, *, policy_id: UUID, visibility: str) -> None:
    visibility_mode = session.scalar(
        select(AclPolicyVisibilityMode).where(
            AclPolicyVisibilityMode.policy_id == policy_id,
            AclPolicyVisibilityMode.key == visibility,
        )
    )
    if visibility_mode is None or not visibility_mode.is_active:
        raise ValueError(f"ACL visibility '{visibility}' is not active in policy {policy_id}.")
