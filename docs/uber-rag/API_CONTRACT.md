# API Contract

The Web UI, CLI, automations, and external systems use the same public API.

**Canonical specification:** `docs/uber-rag/api/openapi.yaml` — OpenAPI 3.1. This markdown document is a summary.

## Design principles

- OpenAPI-first.
- Versioned routes, e.g. `/api/v1`.
- Token-authenticated by OIDC/JWT.
- Every request is associated with user, tenant, groups, and scopes.
- Every security-relevant action emits audit events.
- Long-running work returns job ids.

## Phase 1 frozen subset

Gate A freezes the minimum Phase 1 API surface so Gate B-Gate D implementation work does not expand scope implicitly.

- `GET /api/v1/system/health`
- `POST /api/v1/documents/upload`
- `GET /api/v1/documents`
- `GET /api/v1/documents/{document_id}/acl`
- `PUT /api/v1/documents/{document_id}/acl`

All other endpoints in this document remain part of the broader target contract, but they are not in the Phase 1 delivery subset unless a later gate explicitly pulls them in.

## Core endpoints

### Documents

```text
POST   /api/v1/documents/upload
GET    /api/v1/documents
GET    /api/v1/documents/{document_id}
PATCH  /api/v1/documents/{document_id}
DELETE /api/v1/documents/{document_id}
GET    /api/v1/documents/{document_id}/quality-report
GET    /api/v1/documents/{document_id}/chunks
GET    /api/v1/documents/{document_id}/sources
```

### Collections

```text
POST   /api/v1/collections
GET    /api/v1/collections
GET    /api/v1/collections/{collection_id}
PATCH  /api/v1/collections/{collection_id}
DELETE /api/v1/collections/{collection_id}
POST   /api/v1/collections/{collection_id}/documents
DELETE /api/v1/collections/{collection_id}/documents/{document_id}
```

### Ingestion

```text
POST   /api/v1/documents/{document_id}/parse
POST   /api/v1/documents/{document_id}/index
POST   /api/v1/documents/{document_id}/reindex
GET    /api/v1/ingestion/jobs/{job_id}
GET    /api/v1/ingestion/jobs
POST   /api/v1/ingestion/jobs/{job_id}/retry
POST   /api/v1/ingestion/jobs/{job_id}/cancel
```

Phase 2 ingestion note:
- `GET /api/v1/ingestion/jobs` is the canonical list route.
- `GET /api/v1/ingestion/runs` remains a compatibility alias during the foundation slice, but it is not the published contract route.
- Current foundation payload returns persisted ingestion-run metadata only: `id`, `document_id`, `tenant_id`, `status`, `workflow_backend`, `parser_backend`, `source_hash`, `created_at`, `updated_at`.
- Internal persistence note only: parsed artifacts now store deployment-truthful parser provenance (`parser_backend`, `parser_version`, `parser_profile`) plus normalized OCR provenance (`status`, `applied`, `engine`, `provider`, `page_numbers`) in the DB artifact contract.
- Internal persistence note only: quality reports now store richer structured counts (`page_count`, `table_count`, `non_empty_text_pages`, `empty_text_pages`, `block_count`, `table_page_count`, `ocr_page_count`), warnings, parser provenance, OCR summary, and a raw JSON payload in `quality_reports.raw_report_text` without requiring a schema migration. This does **not** yet change the public `/documents/{document_id}/quality-report` OpenAPI schema.
- Internal persistence note only: document ACL grants now snapshot `acl_policy_id`, `acl_policy_version`, and `sensitivity_rank`, and index ACL payloads now include policy-aware normalized fields plus empty placeholder arrays for inactive future dimensions (`allowed_role_ids`, `allowed_org_unit_ids`, `allowed_project_ids`). The public document ACL request/response schema is unchanged in this slice.
- `POST /api/v1/ingestion/jobs/{job_id}/retry` requires `documents:write`, reuses the existing stored object, returns `404` for not-found/denied runs plus `409` for non-retryable states (`running`, `completed`), and emits retry audit events for success (`ingestion.job.retry`), denied/not-found (`ingestion.job.retry.denied`), and conflict (`ingestion.job.retry.conflict`) outcomes.
- Runs are dispatched through the workflow-backend-neutral dispatcher seam. `workflow_backend="scaffold"` still means the run record is orchestration-agnostic rather than Temporal-specific.
- **Workflow backend selection:** In-process remains the default workflow backend (`WORKFLOW_BACKEND=in_process`). Temporal dispatch is explicit opt-in via `WORKFLOW_BACKEND=temporal` plus `TEMPORAL_HOST_PORT`. When `temporal` is selected without required config, startup fails clearly — no silent fallback to in-process. The Temporal worker skeleton reuses the shared pipeline runner (`PipelineRunner`) and does not redefine stage business logic.

Upload foundation note:
- `POST /api/v1/documents/upload` currently returns document metadata plus `ingestion_run_id` so API clients can poll the persistence/status scaffolding endpoints.

### ACL

```text
GET    /api/v1/acl/bootstrap-policy
PUT    /api/v1/acl/bootstrap-policy
GET    /api/v1/documents/{document_id}/acl
PUT    /api/v1/documents/{document_id}/acl
GET    /api/v1/collections/{collection_id}/acl
PUT    /api/v1/collections/{collection_id}/acl
GET    /api/v1/users/me/permissions
```

Bootstrap ACL policy note:
- `GET /api/v1/acl/bootstrap-policy` returns `404` until the tenant policy is first configured.
- `PUT /api/v1/acl/bootstrap-policy` creates or updates the tenant draft policy, requires `documents:write`, returns `409` after lock, and returns `422` for invalid policy combinations such as an inactive default visibility.
- Truthful current visibility semantics: `public` is still tenant-scoped in the current deployment model. It grants access to any authenticated user in the same tenant, not cross-tenant or anonymous access.

### Retrieval and chat

```text
POST   /api/v1/search
POST   /api/v1/retrieve
POST   /api/v1/chat
POST   /api/v1/chat/stream
POST   /api/v1/rerank
POST   /api/v1/citations/resolve
POST   /api/v1/answers/verify
```

### Evaluation

```text
POST   /api/v1/eval/datasets
GET    /api/v1/eval/datasets
POST   /api/v1/eval/runs
GET    /api/v1/eval/runs/{run_id}
GET    /api/v1/eval/results/{run_id}
```

### Admin and system

```text
GET    /api/v1/system/health
GET    /api/v1/system/models
GET    /api/v1/system/indexes
GET    /api/v1/system/queues
GET    /api/v1/audit/events
POST   /api/v1/admin/rebuild-index
POST   /api/v1/admin/snapshot
```

## Current thin /search slice

The current `POST /api/v1/search` implementation is intentionally narrow while the real retrieval pipeline is still being built. It accepts only a free-text query plus `top_k`, applies ACL before and after the retriever seam, and returns ranked hits only.

Current request shape:

```json
{
  "query": "string",
  "top_k": 5
}
```

Current response shape:

```json
{
  "items": [
    {
      "document_id": "uuid",
      "document_title": "string",
      "source_type": "book|loose_document",
      "chunk_id": "string|null",
      "citation_id": "string|null",
      "source_viewer_url": "/api/v1/search/sources/chunk-1",
      "route": "exact|semantic",
      "score": 0.91,
      "text": "string",
      "page_start": 3,
      "page_end": 3,
      "heading_path": ["Section B"]
    }
  ],
  "total": 1
}
```

Truthful current semantics:
- If no search retriever is configured, `/api/v1/search` returns `503 Service Unavailable` with: `Search retrieval is not configured yet. Configure a search retriever before using /search.` This avoids a false-success `200` empty result. Setting `SEARCH_BACKEND=hybrid` now wires the Phase 3 runtime retriever into the app startup path.
- Quoted queries go through the lexical exact lane and are executed as an OpenSearch `match_phrase` query, not a plain `match` query.
- `citation_id` and `source_viewer_url` are returned only when the retrieval hit has a resolvable chunk id. If a hit cannot be tied back to a chunk, the API omits those fields instead of emitting a broken source-viewer URL.
- `route` exposes the query route chosen by the current retrieval stack (`exact` or `semantic` in the current MVP).
- Search audit events store `query_sha256` plus non-sensitive metadata such as `query_length`, `top_k`, allowed document ids, and result document ids. Raw query text is not stored in plaintext.
- Richer planned search filters (`collections`, `source_types`, `document_types`, `retrieval_mode`, `include_sources`, date/language filters) remain future contract work and are not part of the current public `/search` slice.

## Current source viewer slice

`GET /api/v1/search/sources/{chunk_id}` returns the smallest truthful source slice currently available for a cited chunk.

Truthful current semantics:
- The endpoint requires `documents:read`.
- Tenant and allowed-document ACL filtering is applied inside the source-slice repository query before any chunk text is returned; inaccessible or unknown chunks still return `404` with `Search source was not found or you do not have access to it.`
- The response returns the focus chunk plus the immediate same-parent context window around it. Parent chunks return only themselves in this MVP.
- Successful source-viewer fetches are audited as `search.source.view`. Not-found-or-denied attempts are audited as `search.source.view.denied` with non-sensitive details only (`citation_id`, reason).

## Current chat slice

The current `POST /api/v1/chat` and `POST /api/v1/chat/stream` slice is intentionally narrow and reuses the existing ACL-safe search path before any generation happens.

Current request shape:

```json
{
  "question": "string",
  "top_k": 5
}
```

Current response shape (`POST /api/v1/chat` and the `final` SSE event payload):

```json
{
  "answer_text": "string",
  "status": "answered|not_enough_evidence",
  "model_name": "string|null",
  "provider_name": "string|null",
  "context_block_count": 1,
  "retrieval_hit_count": 1,
  "usage": {
    "total_tokens": 7
  }
}
```

Truthful current semantics:
- The endpoint requires `documents:read`.
- `POST /api/v1/chat` returns `503 Service Unavailable` when search retrieval is not configured and separately when the LLM backend is disabled or missing.
- Evidence discipline is enforced before generation. If retrieval returns zero usable hits or context construction yields zero usable blocks, the service does **not** call the LLM and returns `status=not_enough_evidence` with the truthful not-enough-evidence message: `I do not have enough permitted source evidence to answer that yet.`
- Post-generation verification is enforced after the LLM produces a draft answer. The `AnswerVerifier` checks each answer sentence against the authorized context blocks. If verification shows insufficient support, the service returns `status=not_enough_evidence` and omits the unsupported generated text.
- When verification passes, the response includes `citations` (resolved from authorized retrieval hits) and a `verification` summary with per-sentence support status.
- `POST /api/v1/chat/stream` emits an evidence-safe SSE sequence. After retrieval, generated tokens are buffered server-side until post-generation verification completes. Supported answers emit `retrieval` → `verification` (`supported`) → one or more `token` events → `citations` → `final` (`answered`) → `done`. Unsupported answers emit `retrieval` → `verification` (`unsupported`) → `final` (`not_enough_evidence`) → `done` and **must not emit any generated `token` events**.
- Chat audit events are recorded as `chat.answer` with non-sensitive metadata only: query SHA-256, request size/`top_k`, delivery mode, ACL filter marker, retrieved document ids, retrieval/context counts, whether the LLM was invoked, selected model/provider when used, verification status, citation count, and the final outcome status. Raw question text, answer text, and source chunk text are not written to audit details.

## Current citation resolve slice

`POST /api/v1/citations/resolve` resolves citation IDs against ACL-filtered retrieval hits.

Truthful current semantics:
- The endpoint requires `documents:read`.
- Returns `503` when source-slice lookup is not configured.
- Accepts a non-empty list of non-blank citation IDs; empty or blank values are rejected with validation errors.
- Each citation ID is resolved directly as a chunk identifier through the ACL-safe source-slice lookup path. There is no free-text citation search fallback.
- Only citations that resolve to authorized chunks are returned. Unresolvable or unauthorized citation IDs are silently omitted.

## Current answer verify slice

`POST /api/v1/answers/verify` runs deterministic sentence-level verification against ACL-filtered retrieved evidence.

Truthful current semantics:
- The endpoint requires `documents:read`.
- Returns `503` when search retrieval is not configured.
- Accepts non-blank `question`, `answer_text`, and optional `top_k`.
- Runs retrieval and context building, then checks each answer sentence against the authorized context blocks using casefolded substring overlap.
- Returns a `VerificationSummary` with per-sentence support status and matched citation IDs.
