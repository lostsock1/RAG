from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.request_context import RequestContext


def test_request_context_contains_acl_inputs() -> None:
    context = RequestContext(
        tenant_id="tenant-1",
        user_id="user-1",
        group_ids=["group-a"],
        roles=["editor"],
        scopes=["documents:read"],
    )

    assert context.tenant_id == "tenant-1"
    assert context.group_ids == ["group-a"]
