from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.repositories import documents as documents_module


class _FakeSession:
    bind = object()

    def scalar(self, stmt):
        return None


class _FakeSessionFactory:
    def __call__(self):
        return self

    def __enter__(self):
        return _FakeSession()

    def __exit__(self, *args):
        return False


def _call_get_or_create():
    return documents_module.get_or_create_document_by_source_hash(
        tenant_id=uuid4(),
        owner_user_id=uuid4(),
        title="t",
        source_type="upload",
        source_hash="hash-1",
        file_name="f.txt",
        file_size_bytes=1,
        object_key="k",
    )


def _raise_integrity_error(**kwargs):
    raise IntegrityError("INSERT INTO documents", {}, Exception("duplicate"))


def test_dedup_integrity_fallback_retries_until_live_document_visible(monkeypatch):
    """P2-3: the IntegrityError fallback retries the live-document lookup
    (fresh session per attempt, 50 ms apart) instead of giving up after one read."""
    sentinel = object()
    lookups: list[int] = []
    sleeps: list[float] = []

    def fake_lookup(**kwargs):
        lookups.append(1)
        return sentinel if len(lookups) >= 3 else None

    monkeypatch.setattr(documents_module, "session_factory", _FakeSessionFactory())
    monkeypatch.setattr(documents_module, "create_document_with_owner_acl", _raise_integrity_error)
    monkeypatch.setattr(documents_module, "get_live_document_by_source_hash", fake_lookup)
    monkeypatch.setattr(documents_module.time, "sleep", lambda s: sleeps.append(s))

    assert _call_get_or_create() is sentinel
    assert len(lookups) == 3
    assert sleeps == [0.05, 0.05]


def test_dedup_integrity_fallback_reraises_after_exhausted_retries(monkeypatch):
    """P2-3: when the live document never becomes visible, the original
    IntegrityError propagates after three attempts."""
    lookups: list[int] = []

    def fake_lookup(**kwargs):
        lookups.append(1)
        return None

    monkeypatch.setattr(documents_module, "session_factory", _FakeSessionFactory())
    monkeypatch.setattr(documents_module, "create_document_with_owner_acl", _raise_integrity_error)
    monkeypatch.setattr(documents_module, "get_live_document_by_source_hash", fake_lookup)
    monkeypatch.setattr(documents_module.time, "sleep", lambda s: None)

    with pytest.raises(IntegrityError):
        _call_get_or_create()
    assert len(lookups) == 3
