# Domain Model and Database Schema

## Principle

The domain model is the source of truth for data shape. It maps to Postgres tables (metadata, ACL, jobs, audit, eval), Qdrant collections (vectors), OpenSearch indices (lexical), and document storage objects/files. The Postgres schema is detailed here; other stores reference entities by UUID.

## Entity Relationship Summary

```text
Tenant 1──* User
User   *──* Group
Group  *──* Collection
User   1──* Document (owner)
Document 1──* Chunk
Document 1──* IngestionRun
IngestionRun 1──* IngestionStage
Document 1──* AclGrant
Document *──* Collection
User   1──* AuditEvent
EvalDataset 1──* EvalQuestion
EvalRun 1──* EvalResult
```

## Phase 1 minimum schema subset

Gate A freezes the minimum schema that Phase 1 implementation may create before later retrieval and ingestion tables are introduced.

```text
tenants
users
groups
user_groups
documents
acl_grants
acl_allowed_users
acl_allowed_groups
audit_events
```

All other tables in this document remain planned, but they are outside the minimum Gate A subset.

## Tables

### tenants

Central multi-tenancy anchor. Every entity belongs to exactly one tenant.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `UUID PK DEFAULT gen_random_uuid()` | |
| `name` | `VARCHAR(255) NOT NULL` | Human-readable tenant name |
| `slug` | `VARCHAR(64) NOT NULL UNIQUE` | URL-safe identifier |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |
| `updated_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

### users

OIDC-authenticated user. Keycloak is the identity provider; this table mirrors the Keycloak user ID.

| Column | Type | Notes |
|--------|------|--------|
| `id` | `UUID PK` | Mirrors Keycloak user ID |
| `tenant_id` | `UUID NOT NULL REFERENCES tenants(id)` | |
| `email` | `VARCHAR(255) NOT NULL` | |
| `display_name` | `VARCHAR(255)` | |
| `roles` | `JSONB NOT NULL DEFAULT '[]'` | e.g., `["admin", "editor", "viewer"]` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

UNIQUE: `(tenant_id, email)`

### groups

Named groups for ACL assignment.

| Column | Type | Notes |
|--------|------|--------|
| `id` | `UUID PK DEFAULT gen_random_uuid()` | |
| `tenant_id` | `UUID NOT NULL REFERENCES tenants(id)` | |
| `name` | `VARCHAR(255) NOT NULL` | |
| `description` | `TEXT` | |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

UNIQUE: `(tenant_id, name)`

### user_groups

Many-to-many join.

| Column | Type | Notes |
|--------|------|--------|
| `user_id` | `UUID NOT NULL REFERENCES users(id)` | |
| `group_id` | `UUID NOT NULL REFERENCES groups(id)` | |

PK: `(user_id, group_id)`

### documents

The core entity. Represents an uploaded file before, during, and after ingestion.

| Column | Type | Notes |
|--------|------|--------|
| `id` | `UUID PK DEFAULT gen_random_uuid()` | |
| `tenant_id` | `UUID NOT NULL REFERENCES tenants(id)` | |
| `owner_user_id` | `UUID NOT NULL REFERENCES users(id)` | |
| `title` | `VARCHAR(1024) NOT NULL` | Display title |
| `source_type` | `VARCHAR(32) NOT NULL` | `book` or `loose_document` |
| `document_type` | `VARCHAR(64)` | `textbook`, `contract`, `report`, `email`, `manual`, `memo`, `other` |
| `language` | `VARCHAR(8)` | ISO 639-1 (e.g., `de`, `en`, `pt`) |
| `source_hash` | `VARCHAR(128) NOT NULL` | SHA-256 of original file |
| `file_name` | `VARCHAR(1024)` | Original filename |
| `file_size_bytes` | `BIGINT` | |
| `object_key` | `VARCHAR(1024)` | Storage object key for original file |
| `ingestion_status` | `VARCHAR(32) NOT NULL DEFAULT 'uploaded'` | `uploaded`, `parsing`, `parsed`, `indexing`, `indexed`, `failed` |
| `parser_version` | `VARCHAR(64)` | Set after parsing |
| `embedding_model` | `VARCHAR(128)` | Set after embedding |
| `is_tombstoned` | `BOOLEAN NOT NULL DEFAULT false` | Soft delete |
| `tombstoned_at` | `TIMESTAMPTZ` | |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |
| `updated_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

### acl_grants

Per-document access control. Enforced at query construction, retrieval, and generation layers.

| Column | Type | Notes |
|--------|------|--------|
| `id` | `UUID PK DEFAULT gen_random_uuid()` | |
| `document_id` | `UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE` | |
| `owner_user_id` | `UUID NOT NULL REFERENCES users(id)` | |
| `tenant_id` | `UUID NOT NULL REFERENCES tenants(id)` | Denormalized for query performance |
| `visibility` | `VARCHAR(16) NOT NULL DEFAULT 'private'` | `private`, `group`, `tenant`, `public` |
| `sensitivity` | `VARCHAR(16) NOT NULL DEFAULT 'internal'` | `public`, `internal`, `confidential`, `restricted` |
| `expires_at` | `TIMESTAMPTZ` | NULL = no expiry |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |
| `updated_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

### acl_allowed_users

Users explicitly granted access beyond group/tenant membership.

| Column | Type | Notes |
|--------|------|--------|
| `acl_grant_id` | `UUID NOT NULL REFERENCES acl_grants(id) ON DELETE CASCADE` | |
| `user_id` | `UUID NOT NULL REFERENCES users(id)` | |

PK: `(acl_grant_id, user_id)`

### acl_allowed_groups

Groups granted access.

| Column | Type | Notes |
|--------|------|--------|
| `acl_grant_id` | `UUID NOT NULL REFERENCES acl_grants(id) ON DELETE CASCADE` | |
| `group_id` | `UUID NOT NULL REFERENCES groups(id)` | |

PK: `(acl_grant_id, group_id)`

### collections

Logical groupings of documents for search scoping and ACL inheritance.

| Column | Type | Notes |
|--------|------|--------|
| `id` | `UUID PK DEFAULT gen_random_uuid()` | |
| `tenant_id` | `UUID NOT NULL REFERENCES tenants(id)` | |
| `name` | `VARCHAR(255) NOT NULL` | |
| `description` | `TEXT` | |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |
| `updated_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

### collection_documents

Many-to-many join.

| Column | Type | Notes |
|--------|------|--------|
| `collection_id` | `UUID NOT NULL REFERENCES collections(id) ON DELETE CASCADE` | |
| `document_id` | `UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE` | |

PK: `(collection_id, document_id)`

### collection_acl

Collection-level ACL. If a document is in a collection, the collection ACL is unioned with the document's own ACL for access decisions.

| Column | Type | Notes |
|--------|------|--------|
| `id` | `UUID PK DEFAULT gen_random_uuid()` | |
| `collection_id` | `UUID NOT NULL REFERENCES collections(id) ON DELETE CASCADE` | |
| `visibility` | `VARCHAR(16) NOT NULL DEFAULT 'private'` | Same enum as document ACL |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

### chunks

Postgres shadow copy of indexed chunks for citation resolution and audit. The primary source of truth for search is Qdrant + OpenSearch; this table is the stable reference.

| Column | Type | Notes |
|--------|------|--------|
| `id` | `UUID PK DEFAULT gen_random_uuid()` | Stable chunk ID across reindexes |
| `document_id` | `UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE` | |
| `unit_type` | `VARCHAR(32) NOT NULL` | `chapter`, `section`, `subsection`, `paragraph`, `table`, `formula`, `figure`, `definition`, `page` |
| `heading_path` | `JSONB NOT NULL DEFAULT '[]'` | e.g., `["Ch 3", "Sec 3.2", "Definition 3.2.1"]` |
| `page_start` | `INTEGER` | |
| `page_end` | `INTEGER` | |
| `text` | `TEXT NOT NULL` | |
| `parent_id` | `UUID REFERENCES chunks(id)` | NULL for top-level chunks |
| `embedding_model` | `VARCHAR(128)` | |
| `parser_version` | `VARCHAR(64)` | |
| `chunk_index` | `INTEGER NOT NULL` | Position within document (for dedup) |
| `is_tombstoned` | `BOOLEAN NOT NULL DEFAULT false` | |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

UNIQUE: `(document_id, chunk_index, parser_version, embedding_model)` — enables idempotent reindexing (ADR-0002 rule 1).

### ingestion_runs

Top-level ingestion job. Created when a document is submitted for parsing or indexing.

| Column | Type | Notes |
|--------|------|--------|
| `id` | `UUID PK DEFAULT gen_random_uuid()` | |
| `document_id` | `UUID NOT NULL REFERENCES documents(id)` | |
| `run_type` | `VARCHAR(32) NOT NULL` | `parse`, `index`, `reindex` |
| `status` | `VARCHAR(32) NOT NULL DEFAULT 'pending'` | `pending`, `running`, `completed`, `failed`, `cancelled` |
| `error` | `TEXT` | Set on failure |
| `started_at` | `TIMESTAMPTZ` | |
| `completed_at` | `TIMESTAMPTZ` | |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

### ingestion_stages

Checkpointed stages within a run. Enables resumability (ADR-0002 rule 4).

| Column | Type | Notes |
|--------|------|--------|
| `id` | `UUID PK DEFAULT gen_random_uuid()` | |
| `run_id` | `UUID NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE` | |
| `name` | `VARCHAR(64) NOT NULL` | e.g., `parse`, `ocr`, `chunk`, `embed`, `index_qdrant`, `index_opensearch` |
| `status` | `VARCHAR(32) NOT NULL DEFAULT 'pending'` | `pending`, `running`, `completed`, `failed`, `skipped` |
| `error` | `TEXT` | |
| `output_artifacts` | `JSONB` | References to stored artifacts, chunk counts, etc. |
| `started_at` | `TIMESTAMPTZ` | |
| `completed_at` | `TIMESTAMPTZ` | |

### audit_events

Immutable audit log. Records every security-relevant action.

| Column | Type | Notes |
|--------|------|--------|
| `id` | `UUID PK DEFAULT gen_random_uuid()` | |
| `tenant_id` | `UUID NOT NULL REFERENCES tenants(id)` | |
| `user_id` | `UUID REFERENCES users(id)` | NULL for unauthenticated actions |
| `action` | `VARCHAR(64) NOT NULL` | e.g., `document.upload`, `document.delete`, `acl.update`, `search.execute`, `chat.generate` |
| `resource_type` | `VARCHAR(64)` | e.g., `document`, `collection`, `acl_grant` |
| `resource_id` | `UUID` | |
| `details` | `JSONB NOT NULL DEFAULT '{}'` | Action-specific payload (query hash, filters applied, retrieved IDs count, denied IDs count, model used, verification status) |
| `ip_address` | `INET` | |
| `timestamp` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

Index: `(tenant_id, timestamp DESC)` for queries. Index: `(user_id, timestamp DESC)` for per-user queries. Index: `(resource_type, resource_id)` for resource-scoped queries.

### eval_datasets

Evaluation datasets for regression testing.

| Column | Type | Notes |
|--------|------|--------|
| `id` | `UUID PK DEFAULT gen_random_uuid()` | |
| `name` | `VARCHAR(255) NOT NULL` | |
| `description` | `TEXT` | |
| `dataset_type` | `VARCHAR(32) NOT NULL` | `goldset`, `synthetic_needles`, `negative_test`, `acl_leakage` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

### eval_questions

Individual questions within a dataset.

| Column | Type | Notes |
|--------|------|--------|
| `id` | `UUID PK DEFAULT gen_random_uuid()` | |
| `dataset_id` | `UUID NOT NULL REFERENCES eval_datasets(id) ON DELETE CASCADE` | |
| `query` | `TEXT NOT NULL` | |
| `expected_answer` | `TEXT` | Ground-truth answer |
| `expected_chunk_ids` | `UUID[]` | Expected source chunks |
| `expected_status` | `VARCHAR(32)` | `answered`, `not_found`, `denied` |
| `question_type` | `VARCHAR(32)` | `definition`, `exact_lookup`, `formula`, `table`, `multi_hop`, `negative`, `acl_leakage`, `multilingual` |
| `language` | `VARCHAR(8)` | |
| `metadata` | `JSONB` | |

### eval_runs

An evaluation execution.

| Column | Type | Notes |
|--------|------|--------|
| `id` | `UUID PK DEFAULT gen_random_uuid()` | |
| `dataset_id` | `UUID NOT NULL REFERENCES eval_datasets(id)` | |
| `status` | `VARCHAR(32) NOT NULL DEFAULT 'pending'` | `pending`, `running`, `completed`, `failed` |
| `config` | `JSONB NOT NULL` | Model, retrieval settings, thresholds used |
| `started_at` | `TIMESTAMPTZ` | |
| `completed_at` | `TIMESTAMPTZ` | |

### eval_results

Per-question evaluation results.

| Column | Type | Notes |
|--------|------|--------|
| `id` | `UUID PK DEFAULT gen_random_uuid()` | |
| `run_id` | `UUID NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE` | |
| `question_id` | `UUID NOT NULL REFERENCES eval_questions(id)` | |
| `retrieved_chunk_ids` | `UUID[]` | |
| `generated_answer` | `TEXT` | |
| `citations` | `JSONB` | |
| `faithfulness_score` | `NUMERIC(5,4)` | |
| `citation_accuracy` | `NUMERIC(5,4)` | |
| `status_match` | `BOOLEAN` | Did answer status match expected? |
| `acl_leak` | `BOOLEAN` | Did a forbidden chunk appear? |
| `latency_ms` | `INTEGER` | |
| `error` | `TEXT` | |

## Index conventions

- Every table: PK is UUID, generated by default.
- Foreign keys: always indexed.
- Timestamps: `TIMESTAMPTZ`, default `now()`.
- Soft deletes: `is_tombstoned` boolean + `tombstoned_at` timestamp. Search/retrieval always filters `WHERE is_tombstoned = false`.
- ACL enforcement: application-level, not RLS (though RLS is available as defense-in-depth). ACL filter construction is a dedicated service that produces Qdrant filters + OpenSearch filters + SQL WHERE clauses.

## Migration policy

- Use Alembic for all schema changes.
- Every migration is reversible (`downgrade()` must be implemented).
- No destructive column drops without an ADR and a tombstone period.
- Schema changes that affect retrieval or ACL must include an eval run against the regression dataset.
