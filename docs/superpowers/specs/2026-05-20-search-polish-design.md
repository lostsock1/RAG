# Search Polish Design

**Date:** 2026-05-20
**Status:** Proposed
**Scope:** Narrow follow-up to the Phase 3 Search MVP slice

## Goal

Improve search correctness and user experience with two low-risk fixes:

1. reject whitespace-only `/api/v1/search` queries
2. make source-viewer `is_focus` comparison stable for equivalent UUID strings

## Non-goals

- no ACL redesign
- no retrieval ranking changes
- no query router expansion
- no OpenSearch/Qdrant contract changes
- no API response shape changes

## Current context

The first Phase 3 Search MVP slice is now passing targeted verification and reviewer checks except for non-blocking follow-up polish. The remaining small issues are:

- `SearchRequest.query` currently only enforces `min_length=1`, so whitespace-only input is accepted
- source-viewer focus comparison normalizes stored UUIDs but compares against the raw incoming path string, which can mis-mark `is_focus`

These are correctness and UX issues, not architecture blockers.

## Approach

### 1. Trim-aware search query validation

Keep `query` as a plain string field in `SearchRequest`, but add validation that rejects values whose trimmed content is empty.

Expected behavior:

- `"abc"` → allowed
- `"  abc  "` → allowed
- `"   "` → rejected with `422`
- `"\n\t "` → rejected with `422`

Design choice:

- reject at schema-validation time, before retrieval or routing runs
- use a plain-language validation message so the failure is understandable in API clients and tests

Why here:

- it is the narrowest truthful fix
- it prevents wasted retrieval work
- it keeps route and service code simpler

### 2. Canonical UUID comparison for source-viewer focus marking

Normalize the incoming `chunk_id` path value to the same canonical form already used for stored IDs before setting `is_focus`.

Expected behavior:

- the same logical UUID should mark the focus chunk consistently even if formatting differs in case or representation accepted by the route layer
- response shape remains unchanged

Design choice:

- normalize once at repository comparison time
- do not change stored data or public response schema

Why here:

- the issue is localized to focus-flag derivation
- no broader retrieval or ACL behavior needs to change

## Files likely to change

- `apps/api/app/schemas/search.py`
- `apps/api/app/repositories/search_sources.py`
- `apps/api/app/tests/integration/test_search_route.py`
- `apps/api/app/tests/unit/test_search_sources_repository.py` or `apps/api/app/tests/integration/test_search_source_viewer.py`
- `docs/uber-rag/PROJECT_STATE.md` if implemented

## Testing strategy

Add focused regression coverage:

1. `/api/v1/search` returns `422` for whitespace-only queries
2. source-viewer marks exactly one chunk as `is_focus=True` when the requested chunk identifier is equivalent after normalization

Keep the existing Phase 3 search suite green after the change.

## Risks

- low risk of changing validation expectations for clients that currently send invalid blank queries
- very low risk in source-viewer comparison because the change is read-only and response-shaping only

## Alternatives considered

### Alternative A: handle blank queries inside `SearchService`

Rejected because validation belongs earlier than service execution and would duplicate schema responsibilities.

### Alternative B: silently trim and accept blank queries as empty result sets

Rejected because it hides invalid input and makes client behavior less explicit.

### Alternative C: leave `is_focus` as-is until broader source-viewer work

Rejected because the fix is cheap, local, and improves correctness now.

## Recommended order

1. add failing validation test for whitespace-only queries
2. make schema validation trim-aware
3. add failing focus-normalization test
4. normalize requested chunk ID before `is_focus` comparison
5. rerun targeted Phase 3 verification

## Implementation note

This slice is intentionally separate from the larger search ACL-scaling redesign. The scalability issue should get its own spec/plan because it changes retrieval filtering architecture rather than polishing the current MVP behavior.
