from pathlib import Path
import sys

from sqlalchemy.dialects import postgresql

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.repositories.audit import build_audit_event
from app.services.acl_service import build_document_acl_filter


def test_acl_filter_includes_owner_group_tenant_and_public_visibility() -> None:
    sql_filter = build_document_acl_filter(
        tenant_id="11111111-1111-1111-1111-111111111111",
        user_id="22222222-2222-2222-2222-222222222222",
        group_ids=["33333333-3333-3333-3333-333333333333"],
    )

    compiled = str(
        sql_filter.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "11111111-1111-1111-1111-111111111111" in compiled
    assert "22222222-2222-2222-2222-222222222222" in compiled
    assert "33333333-3333-3333-3333-333333333333" in compiled
    assert "tenant" in compiled
    assert "public" in compiled
    assert "is_tombstoned" in compiled


def test_build_audit_event_matches_task_5_signature() -> None:
    event = build_audit_event(
        tenant_id="11111111-1111-1111-1111-111111111111",
        user_id="22222222-2222-2222-2222-222222222222",
        action="documents.list",
        resource_type="document",
        resource_id="44444444-4444-4444-4444-444444444444",
        details={"filters_applied": ["acl"]},
    )

    assert event.tenant_id == "11111111-1111-1111-1111-111111111111"
    assert event.user_id == "22222222-2222-2222-2222-222222222222"
    assert event.action == "documents.list"
    assert event.resource_type == "document"
    assert event.resource_id == "44444444-4444-4444-4444-444444444444"
    assert event.details == {"filters_applied": ["acl"]}
