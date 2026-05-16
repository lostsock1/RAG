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

## Required ACL fields

```json
{
  "tenant_id": "string",
  "owner_user_id": "string",
  "allowed_user_ids": ["string"],
  "allowed_group_ids": ["string"],
  "visibility": "private|group|tenant|public",
  "sensitivity": "public|internal|confidential|restricted",
  "expires_at": "timestamp|null"
}
```

## Gate A explicit ACL test cases

- **Disjoint-group isolation:** user A in group alpha cannot retrieve, search, list, or cite documents that are only visible to group beta; user B in group beta cannot retrieve, search, list, or cite documents that are only visible to group alpha.
- **Owner visibility:** the document owner can list, retrieve, and update ACL for their own document even when visibility is `private`.
- **Explicit user grant visibility:** a user listed in `allowed_user_ids` can access the document without sharing the owner's groups.
- **Tenant visibility inside tenant only:** `tenant` visibility grants access to authenticated users from the same tenant only; users from other tenants receive no results and no metadata leakage.
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
