# Uber-RAG Phase 1 Balanced Foundation Design

Date: 2026-05-15
Status: Approved in conversation, pending user review of written spec

## Goal

Define a deliberate, well-researched, and debate-friendly Phase 1 for Uber-RAG that prioritizes security correctness, architecture stability, and operational readiness before broader implementation velocity.

## Summary

Phase 1 should not be treated as a pure speed run or as a full implementation of all early-platform concerns. Instead, it should be executed as a **gate-led foundation phase** with explicit exit criteria. This keeps the project aligned with the core invariants already accepted in project memory: API-first architecture, backend ACL enforcement, group separation, evidence discipline, and frontend as an unprivileged client.

The intent is to reduce expensive reversals later by closing the most important design, security, and operational questions before broad implementation expands the surface area.

## Why this shape

Three candidate shapes were considered:

1. **Security-led balanced Phase 1**
   - Strongest early protection against ACL leakage.
   - Weakness: can under-spec service boundaries and migration/contract stability.

2. **Contract-led balanced Phase 1**
   - Strongest at reducing backend/frontend churn.
   - Weakness: can delay meaningful runtime proof and produce slow visible progress.

3. **Gate-led balanced Phase 1**
   - Organizes work by decision closure and proof obligations rather than by layer.
   - Chosen because it best matches the user preference for a solid, researched, debated foundation.

## Phase 1 structure

Phase 1 is split into four gates.

### Gate A — Design closure

Close the implementation-critical planning questions before coding expands the surface area.

#### Produces

- narrowed Phase 1 endpoint list
- minimum schema subset for Phase 1
- auth/ACL enforcement flow
- audit event shape
- explicit list of unresolved ADR or document gaps

#### Exit criteria

- Phase 1 endpoint list is frozen
- table and field names align with `docs/uber-rag/DOMAIN_MODEL.md`
- ACL rules are expressed in testable form
- no known architecture contradiction remains open

### Gate B — Security/data foundation

Build the minimum substrate that proves ACL, identity, ownership, and audit behavior before feature breadth increases.

#### Produces

- auth request-context seam
- initial Postgres migration
- ACL filter builder
- audit event persistence
- mandatory leakage tests

#### Exit criteria

- two disjoint-group test cases pass
- unauthorized documents do not appear in list results
- ACL updates are audited
- upload-created documents receive default owner ACL

### Gate C — Operational foundation

Prove that the system is practical to run locally and is disciplined enough for later growth.

#### Produces

- local Postgres/MinIO/Keycloak stack
- config and environment loading discipline
- health checks
- storage adapter boundary
- baseline CI for unit, integration, and ACL leakage tests

#### Exit criteria

- fresh developer setup works from docs
- API starts cleanly against local dependencies
- tests run repeatably
- no secrets are committed

### Gate D — First product slice

Only after the earlier gates are closed should the first end-user-facing slice be implemented.

#### Produces

- authenticated upload
- document ACL read/update
- ACL-filtered document list
- minimal UI for login, upload, and list

#### Exit criteria

- user can log in and upload a file
- uploaded file lands in object storage and metadata DB
- authorized user sees the document
- unauthorized user does not
- audit trail exists for upload, list, and ACL change

## Recommended sequencing within the gates

### Gate A sequencing

1. Confirm the exact Phase 1 endpoint subset.
   - likely subset: `/api/v1/system/health`, `/api/v1/documents/upload`, `/api/v1/documents`, `/api/v1/documents/{document_id}/acl`
2. Confirm the minimum schema subset.
   - `tenants`, `users`, `groups`, `user_groups`, `documents`, `acl_grants`, `acl_allowed_users`, `acl_allowed_groups`, `audit_events`
3. Translate ACL rules into explicit tests.
4. Check whether any ADR or decision note is still needed for:
   - Keycloak claim mapping details
   - audit payload minimum contract
   - any Phase 1 scope split ambiguity

### Gate B sequencing

1. request context and auth seam
2. migration and DB models
3. ACL filter builder
4. audit writer
5. leakage tests
6. only then document endpoints

### Gate C sequencing

1. docker/dev stack
2. env/config discipline
3. MinIO adapter boundary
4. health checks
5. CI baseline

### Gate D sequencing

1. upload API
2. ACL read/update API
3. document list API
4. minimal web client for login/upload/list

## Scope boundary

This is **not** all of early Uber-RAG implementation. It is also **not** merely a speed-first vertical slice. It is best described as:

**Phase 1 balanced foundation with a first product slice at the end.**

That means:

- it belongs to Phase 1
- it includes a first usable product slice
- it deliberately holds back broader ingestion, retrieval, and chat work until the foundation is proven

## What is intentionally deferred

The following are not part of this Phase 1 design target:

- ingestion jobs and resumable parsing/indexing flows
- Docling parser integration and OCR quality handling
- chunking, indexing, Qdrant, and OpenSearch implementation
- retrieval, reranking, citations, and chat APIs
- evaluation harness implementation beyond baseline CI setup
- richer admin/system surface beyond the minimal health and audit-relevant paths

## Tradeoffs

### Positive consequences

- reduces risk of ACL and group-separation reversals
- stabilizes contracts before frontend and backend breadth increases
- forces operational discipline early
- gives the builder clear gate-based proof obligations rather than vague progress markers

### Negative consequences

- slower visible feature progress than a pure speed-first build order
- requires deliberate pauses for review at each gate
- may feel heavier than necessary if no major ambiguities remain in practice

## Recommended immediate next step

Before implementation starts, project memory should be reconciled to this gate-led Phase 1 framing:

1. update `PROJECT_STATE.md` so the recommended next action is balanced and gate-led, not speed-first
2. add a short Phase 1 gate checklist to project memory
3. identify whether claim mapping or audit contract details need an ADR or lightweight decision note

After that, the `uber-rag` primary builder can implement Gate A first and proceed gate by gate.
