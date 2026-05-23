"""P1-2 ACL leakage regression tests.

These tests prove that the payload-side ACL filter in the Qdrant and
OpenSearch retrievers blocks forbidden documents even when the pre-fetched
``allowed_document_ids`` list contains the forbidden document's ID.

This is the defense-in-depth requirement from SECURITY_ACL.md:
"No ACL-touching feature without a leakage test in the same PR."
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from qdrant_client.models import FieldCondition, Filter, MatchValue

from app.services.retrieval.acl_filter import (
    build_opensearch_acl_filter,
    build_qdrant_acl_filter,
)
from app.services.retrieval.base import RetrievalHit, RetrievalQuery
from app.services.retrieval.opensearch_retriever import OpenSearchRetriever
from app.services.retrieval.qdrant_retriever import QdrantRetriever


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_qdrant_point(*, document_id: str, tenant_id: str, owner_user_id: str, visibility: str = "private") -> SimpleNamespace:
    """Simulate a Qdrant point with ACL payload fields."""
    return SimpleNamespace(
        score=0.9,
        payload={
            "document_id": document_id,
            "chunk_id": str(uuid4()),
            "text": f"text from {document_id}",
            "tenant_id": tenant_id,
            "owner_user_id": owner_user_id,
            "allowed_user_ids": [owner_user_id],
            "allowed_group_ids": [],
            "visibility": visibility,
            "is_tombstoned": False,
            "expires_at": None,
        },
    )


class _FilteringQdrantClient:
    """Fake Qdrant client that applies the ACL filter against in-memory points."""

    def __init__(self, points: list[SimpleNamespace]) -> None:
        self._points = points

    def query_points(self, **kwargs: object) -> list[SimpleNamespace]:
        query_filter: Filter | None = kwargs.get("query_filter")  # type: ignore[assignment]
        if query_filter is None:
            return list(self._points)
        return [p for p in self._points if _matches_qdrant_filter(p.payload, query_filter)]


def _matches_qdrant_filter(payload: dict, f: Filter) -> bool:
    """Minimal recursive Qdrant filter evaluator for test purposes."""
    if f.must:
        for clause in f.must:
            if isinstance(clause, FieldCondition):
                if not _matches_field_condition(payload, clause):
                    return False
            elif isinstance(clause, Filter):
                if not _matches_qdrant_filter(payload, clause):
                    return False
    if f.must_not:
        for clause in f.must_not:
            if isinstance(clause, FieldCondition):
                if _matches_field_condition(payload, clause):
                    return False
            elif isinstance(clause, Filter):
                if _matches_qdrant_filter(payload, clause):
                    return False
    if f.should:
        if not any(
            _matches_field_condition(payload, clause) if isinstance(clause, FieldCondition)
            else _matches_qdrant_filter(payload, clause)
            for clause in f.should
        ):
            return False
    return True


def _matches_field_condition(payload: dict, cond: FieldCondition) -> bool:
    value = payload.get(cond.key)
    if cond.is_null is not None:
        is_null = value is None
        return is_null == cond.is_null
    if cond.match is not None:
        from qdrant_client.models import MatchAny, MatchValue
        if isinstance(cond.match, MatchValue):
            if isinstance(value, list):
                return cond.match.value in value
            return value == cond.match.value
        if isinstance(cond.match, MatchAny):
            if isinstance(value, list):
                return any(v in cond.match.any for v in value)
            return value in cond.match.any
    if cond.range is not None:
        if value is None:
            return False
        r = cond.range
        if r.gt is not None and not (value > r.gt):
            return False
        if r.gte is not None and not (value >= r.gte):
            return False
        if r.lt is not None and not (value < r.lt):
            return False
        if r.lte is not None and not (value <= r.lte):
            return False
        return True
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_search_payload_acl_blocks_forbidden_doc_even_when_in_allowed_list() -> None:
    """P1-2 acceptance criterion: a forbidden document must not appear in
    search results even when ``allowed_document_ids`` contains its ID.

    Setup:
    - Alice (user_id=alice) owns doc-alice in tenant-A.
    - Bob (user_id=bob) owns doc-bob in tenant-A (private, not shared with Alice).
    - The pre-fetched allowed_document_ids list is injected to contain BOTH
      doc-alice AND doc-bob (simulating a bypass / stale cache).
    - The Qdrant retriever must still block doc-bob because the payload-side
      ACL filter sees that Alice is not the owner and has no grant.
    """
    tenant_id = "tenant-a"
    alice_id = str(uuid4())
    bob_id = str(uuid4())
    doc_alice_id = str(uuid4())
    doc_bob_id = str(uuid4())

    alice_point = _make_qdrant_point(
        document_id=doc_alice_id,
        tenant_id=tenant_id,
        owner_user_id=alice_id,
        visibility="private",
    )
    bob_point = _make_qdrant_point(
        document_id=doc_bob_id,
        tenant_id=tenant_id,
        owner_user_id=bob_id,
        visibility="private",
    )

    client = _FilteringQdrantClient([alice_point, bob_point])
    retriever = QdrantRetriever(client=client, collection_name="test-collection")

    # Inject Bob's doc into allowed_document_ids — simulating a bypass
    query = RetrievalQuery(
        query="test query",
        tenant_id=tenant_id,
        user_id=alice_id,
        group_ids=[],
        allowed_document_ids=[doc_alice_id, doc_bob_id],  # Bob's doc injected!
        top_k=10,
    )

    hits = retriever.search_dense(query, [0.1, 0.2, 0.3])

    returned_doc_ids = {hit.document_id for hit in hits}
    assert doc_bob_id not in returned_doc_ids, (
        f"Bob's document {doc_bob_id} was returned to Alice — ACL leakage detected!"
    )
    assert doc_alice_id in returned_doc_ids, (
        f"Alice's own document {doc_alice_id} was not returned — over-filtering."
    )


def test_qdrant_acl_filter_allows_tenant_wide_visibility() -> None:
    """A document with visibility='tenant' must be accessible to any user in
    the same tenant, even without an explicit grant."""
    tenant_id = "tenant-b"
    alice_id = str(uuid4())
    bob_id = str(uuid4())
    doc_id = str(uuid4())

    # Bob owns a tenant-wide document
    tenant_point = SimpleNamespace(
        score=0.8,
        payload={
            "document_id": doc_id,
            "chunk_id": str(uuid4()),
            "text": "tenant-wide content",
            "tenant_id": tenant_id,
            "owner_user_id": bob_id,
            "allowed_user_ids": [bob_id],
            "allowed_group_ids": [],
            "visibility": "tenant",
            "is_tombstoned": False,
            "expires_at": None,
        },
    )

    client = _FilteringQdrantClient([tenant_point])
    retriever = QdrantRetriever(client=client, collection_name="test-collection")

    # Alice queries — she has no explicit grant but the doc is tenant-wide
    query = RetrievalQuery(
        query="tenant doc",
        tenant_id=tenant_id,
        user_id=alice_id,
        group_ids=[],
        allowed_document_ids=[],
        top_k=5,
    )

    hits = retriever.search_dense(query, [0.1])
    assert any(h.document_id == doc_id for h in hits), (
        "Tenant-wide document was not returned to a tenant member."
    )


def test_qdrant_acl_filter_blocks_cross_tenant_access() -> None:
    """A document in tenant-A must never be returned to a user in tenant-B."""
    tenant_a = "tenant-a"
    tenant_b = "tenant-b"
    alice_id = str(uuid4())
    doc_id = str(uuid4())

    # Alice's doc in tenant-A with public visibility
    public_point = SimpleNamespace(
        score=0.9,
        payload={
            "document_id": doc_id,
            "chunk_id": str(uuid4()),
            "text": "public content",
            "tenant_id": tenant_a,
            "owner_user_id": alice_id,
            "allowed_user_ids": [alice_id],
            "allowed_group_ids": [],
            "visibility": "public",
            "is_tombstoned": False,
            "expires_at": None,
        },
    )

    client = _FilteringQdrantClient([public_point])
    retriever = QdrantRetriever(client=client, collection_name="test-collection")

    # Bob from tenant-B queries
    bob_id = str(uuid4())
    query = RetrievalQuery(
        query="public doc",
        tenant_id=tenant_b,  # different tenant!
        user_id=bob_id,
        group_ids=[],
        allowed_document_ids=[],
        top_k=5,
    )

    hits = retriever.search_dense(query, [0.1])
    assert not hits, (
        f"Cross-tenant document {doc_id} was returned to a user in {tenant_b} — "
        "tenant isolation violated!"
    )


def test_opensearch_acl_filter_structure_includes_required_clauses() -> None:
    """The OpenSearch ACL filter must include tenant, tombstone, expiry, and
    access clauses."""
    tenant_id = "tenant-c"
    user_id = str(uuid4())
    group_ids = [str(uuid4()), str(uuid4())]

    clauses = build_opensearch_acl_filter(
        tenant_id=tenant_id,
        user_id=user_id,
        group_ids=group_ids,
    )

    assert len(clauses) == 4, f"Expected 4 ACL clauses, got {len(clauses)}"

    # Tenant scoping
    assert clauses[0] == {"term": {"tenant_id": tenant_id}}

    # Tombstone guard
    assert clauses[1] == {"term": {"is_tombstoned": False}}

    # Expiry clause (bool with should)
    expiry = clauses[2]
    assert "bool" in expiry
    assert "should" in expiry["bool"]
    assert expiry["bool"]["minimum_should_match"] == 1

    # Access clause (bool with should containing owner, user, group, visibility)
    access = clauses[3]
    assert "bool" in access
    access_should = access["bool"]["should"]
    assert {"term": {"owner_user_id": user_id}} in access_should
    assert {"term": {"allowed_user_ids": user_id}} in access_should
    assert {"term": {"visibility": "tenant"}} in access_should
    assert {"term": {"visibility": "public"}} in access_should
    assert {"terms": {"allowed_group_ids": group_ids}} in access_should
