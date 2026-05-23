from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.request_context import RequestContext
from app.core.security import assert_dev_auth_bind_is_loopback


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


def test_dev_auth_rejects_when_bind_not_loopback() -> None:
    """P1-6: assert_dev_auth_bind_is_loopback must raise RuntimeError when the
    bind address is not a loopback address."""
    with pytest.raises(RuntimeError, match="AUTH_MODE=dev is not allowed"):
        assert_dev_auth_bind_is_loopback("0.0.0.0")

    with pytest.raises(RuntimeError, match="AUTH_MODE=dev is not allowed"):
        assert_dev_auth_bind_is_loopback("192.168.1.1")

    with pytest.raises(RuntimeError, match="AUTH_MODE=dev is not allowed"):
        assert_dev_auth_bind_is_loopback("10.0.0.1")


def test_dev_auth_allows_loopback_bind_addresses() -> None:
    """P1-6: assert_dev_auth_bind_is_loopback must not raise for loopback addresses."""
    assert_dev_auth_bind_is_loopback("127.0.0.1")   # no exception
    assert_dev_auth_bind_is_loopback("::1")          # no exception
    assert_dev_auth_bind_is_loopback("localhost")    # no exception
