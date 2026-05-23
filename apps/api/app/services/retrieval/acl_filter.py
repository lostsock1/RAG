"""Payload-side ACL filter builders for Qdrant and OpenSearch.

These functions mirror ``app.services.acl_service.build_document_acl_filter``
(the SQLAlchemy version) but produce filter objects that are evaluated inside
the vector store / search engine rather than in Postgres.  This is the
defense-in-depth layer: even if the pre-fetched ``allowed_document_ids`` list
is wrong or bypassed, the retriever will not return documents the caller is
not allowed to see.

ACL rules (same as the SQL version):
  - owner: payload.owner_user_id == user_id
  - explicit user grant: user_id in payload.allowed_user_ids
  - group grant: any(group_ids) in payload.allowed_group_ids
  - tenant-wide: payload.visibility == "tenant"
  - public: payload.visibility == "public"

Tenant scoping is always applied.

Expiry asymmetry between backends:
  - OpenSearch enforces expiry natively at the payload level (date type
    + bool.must_not[exists] short-circuit for the missing-field case).
  - The Qdrant payload filter does NOT enforce expiry. The in-memory
    Qdrant implementation does not match ``is_null`` / ``is_empty``
    against JSON null values, and the payload stores ``expires_at`` as
    either an ISO string or null — there is no numeric field that
    ``Range(lt=now)`` could compare against without re-indexing every
    chunk. The SQL-side ``build_document_acl_filter`` already enforces
    expiry against ``acl_grants.expires_at`` and produces the
    ``allowed_document_ids`` narrow filter, so expired documents are
    excluded before the retriever ever sees them. If the payload ACL
    filter is ever exercised in isolation (e.g. allowed_document_ids
    bypassed), expiry would not be enforced at the Qdrant layer — this
    is a known accepted gap until Qdrant gains reliable null-field
    matching or the indexer is changed to store a numeric
    ``expires_at_ts`` field.
"""
from __future__ import annotations

from datetime import UTC, datetime

from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
)


def build_qdrant_acl_filter(
    *,
    tenant_id: str,
    user_id: str,
    group_ids: list[str],
) -> Filter:
    """Return a Qdrant ``Filter`` that enforces the Phase 1 ACL rules.

    The filter is structured as::

        must: [
            tenant_id == tenant_id,
            NOT is_tombstoned,
            (owner OR explicit_user OR group_match OR visibility=tenant OR visibility=public),
        ]

    Expiry is enforced by the SQL ACL filter upstream (see module
    docstring for why the Qdrant layer does not duplicate it).
    """
    # Tenant scoping — always required
    tenant_clause = FieldCondition(
        key="tenant_id",
        match=MatchValue(value=tenant_id),
    )

    # Tombstone guard
    not_tombstoned = Filter(
        must_not=[
            FieldCondition(key="is_tombstoned", match=MatchValue(value=True))
        ]
    )

    # Access clauses (OR-of-clauses)
    access_clauses: list[FieldCondition] = [
        # Owner
        FieldCondition(key="owner_user_id", match=MatchValue(value=user_id)),
        # Explicit user grant
        FieldCondition(key="allowed_user_ids", match=MatchValue(value=user_id)),
        # Tenant-wide visibility
        FieldCondition(key="visibility", match=MatchValue(value="tenant")),
        # Public visibility
        FieldCondition(key="visibility", match=MatchValue(value="public")),
    ]

    if group_ids:
        access_clauses.append(
            FieldCondition(key="allowed_group_ids", match=MatchAny(any=group_ids))
        )

    access_filter = Filter(should=access_clauses)

    return Filter(
        must=[
            tenant_clause,
            not_tombstoned,
            access_filter,
        ]
    )


def build_opensearch_acl_filter(
    *,
    tenant_id: str,
    user_id: str,
    group_ids: list[str],
) -> list[dict]:
    """Return a list of OpenSearch ``bool.filter`` clauses enforcing the ACL.

    Usage::

        {
            "query": {
                "bool": {
                    "must": [text_clause],
                    "filter": build_opensearch_acl_filter(...),
                }
            }
        }
    """
    now_iso = datetime.now(UTC).isoformat()

    # Tenant scoping
    tenant_clause: dict = {"term": {"tenant_id": tenant_id}}

    # Tombstone guard
    not_tombstoned: dict = {"term": {"is_tombstoned": False}}

    # Expiry: expires_at missing OR expires_at > now
    unexpired: dict = {
        "bool": {
            "should": [
                {"bool": {"must_not": [{"exists": {"field": "expires_at"}}]}},
                {"range": {"expires_at": {"gt": now_iso}}},
            ],
            "minimum_should_match": 1,
        }
    }

    # Access clauses (OR-of-clauses)
    access_should: list[dict] = [
        {"term": {"owner_user_id": user_id}},
        {"term": {"allowed_user_ids": user_id}},
        {"term": {"visibility": "tenant"}},
        {"term": {"visibility": "public"}},
    ]
    if group_ids:
        access_should.append({"terms": {"allowed_group_ids": group_ids}})

    access_clause: dict = {
        "bool": {
            "should": access_should,
            "minimum_should_match": 1,
        }
    }

    return [tenant_clause, not_tombstoned, unexpired, access_clause]
