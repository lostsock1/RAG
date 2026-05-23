from __future__ import annotations

import inspect
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.security import _get_nested_claim


def test_get_nested_claim_has_no_unreachable_code() -> None:
    """P0-1: _get_nested_claim must not contain leftover unreachable ip_address code."""
    source = inspect.getsource(_get_nested_claim)
    assert "ip_address(host)" not in source, (
        "Unreachable ip_address(host) block found in _get_nested_claim — "
        "leftover from a refactor. Remove the dead try/except."
    )


def test_get_nested_claim_returns_none_for_missing_path() -> None:
    claims = {"a": {"b": 1}}
    assert _get_nested_claim(claims, "a.c") is None


def test_get_nested_claim_returns_deep_value() -> None:
    claims = {"a": {"b": {"c": 42}}}
    assert _get_nested_claim(claims, "a.b.c") == 42
