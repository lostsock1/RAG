# Security and ACL Model

## Principle

ACL is enforced server-side and in retrieval filters. The frontend is not trusted.

## Identity inputs

- tenant id
- user id
- group ids
- roles
- scopes
- clearance level where applicable
- collection membership
- document ownership

## Enforcement path

```text
JWT/OIDC token
  -> backend authentication
  -> permission resolver
  -> ACL filter
  -> OpenSearch/Qdrant query filters
  -> fusion
  -> ACL recheck
  -> source fetch ACL check
  -> generation context
  -> answer/citation ACL check
  -> audit log
```

## ACL bootstrap policy

Each tenant now has one bootstrap ACL policy that is intended to be configured before first ingest.

- Policy shape: `policy_id`, `policy_version`, `status` (`draft|locked`), `locked_at`, `default_visibility_mode`.
- Visibility modes use stable internal keys with renameable display names and active flags: `private`, `group`, `tenant`, `public`.
- Sensitivity levels use stable internal keys with renameable display names, active flags, and deterministic ranks: `public=100`, `internal=200`, `confidential=300`, `restricted=400`.
- Dimensions use stable internal keys with renameable display names. Current defaults are active `user` + `group`, plus inactive placeholders `role`, `org_unit`, and `project`.
- First document creation / ingest locks the tenant policy if it is still `draft`. After lock, semantic edits are rejected.
- The bootstrap policy is API-first: clients use `GET /api/v1/acl/bootstrap-policy` and `PUT /api/v1/acl/bootstrap-policy` rather than repository-only wiring.
- Current truthful `public` semantics are tenant-scoped to authenticated users in the same tenant. `public` does not bypass tenant isolation and does not mean anonymous internet access.

## Required ACL fields

```json
{
  "tenant_id": "string",
  "owner_user_id": "string",
  "allowed_user_ids": ["string"],
  "allowed_group_ids": ["string"],
  "visibility": "private|group|tenant|public",
  "sensitivity": "public|internal|confidential|restricted",
  "sensitivity_rank": 200,
  "expires_at": "timestamp|null",
  "expires_at_ts": "int epoch seconds — Qdrant payload only; sentinel 4102444800 (2100-01-01Z) when no expiry",
  "acl_policy_id": "string",
  "acl_policy_version": 1,
  "allowed_role_ids": [],
  "allowed_org_unit_ids": [],
  "allowed_project_ids": []
}
```

### Expiry enforcement by layer

- **SQL** (`build_document_acl_filter`): enforces `acl_grants.expires_at` — primary gate.
- **OpenSearch**: native `date`-type range clause with missing-field short-circuit.
- **Qdrant** (since 2026-06-10, master plan A5): unconditional `Range(gt=now)` on the
  numeric `expires_at_ts` payload field. No-expiry documents carry the far-future
  sentinel rather than null, because the in-memory Qdrant backend does not reliably
  match `is_null`/`is_empty` against JSON-null payloads. **Fail-closed:** points
  indexed before this change lack `expires_at_ts` and stop matching the dense/sparse
  payload filter until their corpus is re-ingested (or reindexed once the reindex CLI
  from master plan task E4 exists). Leakage tests:
  `test_qdrant_payload_acl_blocks_expired_doc_even_for_owner_in_allowed_list`,
  `test_qdrant_acl_filter_fails_closed_for_points_missing_expires_at_ts`.

## Gate A explicit ACL test cases

- **Disjoint-group isolation:** user A in group alpha cannot retrieve, search, list, or cite documents that are only visible to group beta; user B in group beta cannot retrieve, search, list, or cite documents that are only visible to group alpha.
- **Owner visibility:** the document owner can list, retrieve, and update ACL for their own document even when visibility is `private`.
- **Explicit user grant visibility:** a user listed in `allowed_user_ids` can access the document without sharing the owner's groups.
- **Tenant visibility inside tenant only:** `tenant` visibility grants access to authenticated users from the same tenant only; users from other tenants receive no results and no metadata leakage.
- **Public visibility inside tenant only:** `public` visibility grants access to any authenticated user from the same tenant even without shared group membership; users from other tenants still receive no results and no metadata leakage.
- **Hidden docs omitted from counts and titles:** unauthorized documents do not appear in list counts, search counts, autocomplete, document titles, or error text.

## Mandatory tests

- User cannot search unauthorized document by semantic query.
- User cannot search unauthorized document by exact phrase.
- User cannot retrieve unauthorized source by citation id.
- User cannot receive generated answer based on unauthorized context.
- User cannot infer hidden document existence from result counts or error messages.
- Deletion/tombstone removes document from search and chat.
- Version ACL changes apply immediately to search and source fetch.

## Audit events

Record:

- login/session id if available
- user id
- tenant id
- endpoint
- query text hash and optionally encrypted raw query
- filters applied
- retrieved document ids
- denied document ids count, not titles
- citations returned
- model used
- verification status
- timestamp

## Frontend rules

- Do not store access decisions as truth.
- Do not call storage/index/LLM services directly.
- Show denied and not-found states clearly.
- Do not leak hidden collection names or document titles.
