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
- `POST /api/v1/ingestion/jobs/{job_id}/retry` requires `documents:write`, reuses the existing stored object, returns `404` for not-found/denied runs plus `409` for non-retryable states (`running`, `completed`), and emits retry audit events for success (`ingestion.job.retry`), denied/not-found (`ingestion.job.retry.denied`), and conflict (`ingestion.job.retry.conflict`) outcomes.
- Runs are dispatched through the workflow-backend-neutral dispatcher seam. `workflow_backend="scaffold"` still means the run record is orchestration-agnostic rather than Temporal-specific.
- **Workflow backend selection:** In-process remains the default workflow backend (`WORKFLOW_BACKEND=in_process`). Temporal dispatch is explicit opt-in via `WORKFLOW_BACKEND=temporal` plus `TEMPORAL_HOST_PORT`. When `temporal` is selected without required config, startup fails clearly — no silent fallback to in-process. The Temporal worker skeleton reuses the shared pipeline runner (`PipelineRunner`) and does not redefine stage business logic.

Upload foundation note:
- `POST /api/v1/documents/upload` currently returns document metadata plus `ingestion_run_id` so API clients can poll the persistence/status scaffolding endpoints.

### ACL

```text
GET    /api/v1/documents/{document_id}/acl
PUT    /api/v1/documents/{document_id}/acl
GET    /api/v1/collections/{collection_id}/acl
PUT    /api/v1/collections/{collection_id}/acl
GET    /api/v1/users/me/permissions
```

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

## Search request sketch

```json
{
  "query": "string",
  "collections": ["uuid"],
  "source_types": ["book", "loose_document"],
  "document_types": ["textbook", "report"],
  "filters": {
    "language": ["de", "en", "pt"],
    "date_from": "2026-01-01",
    "date_to": "2026-12-31"
  },
  "retrieval_mode": "auto|exact|semantic|book|table|formula|hybrid",
  "top_k": 20,
  "include_sources": true
}
```

## Chat response sketch

```json
{
  "answer": "string",
  "status": "answered|partial|not_found|denied",
  "citations": [
    {
      "citation_id": "string",
      "document_id": "uuid",
      "title": "string",
      "page_start": 1,
      "page_end": 2,
      "section": "string",
      "chunk_id": "uuid"
    }
  ],
  "verification": {
    "unsupported_claims": [],
    "confidence": "high|medium|low"
  },
  "audit_id": "uuid"
}
```
