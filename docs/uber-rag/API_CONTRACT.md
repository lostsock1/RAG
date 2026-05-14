# API Contract

The Web UI, CLI, automations, and external systems use the same public API.

## Design principles

- OpenAPI-first.
- Versioned routes, e.g. `/api/v1`.
- Token-authenticated by OIDC/JWT.
- Every request is associated with user, tenant, groups, and scopes.
- Every security-relevant action emits audit events.
- Long-running work returns job ids.

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
POST   /api/v1/ingestion/jobs/{job_id}/cancel
```

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
