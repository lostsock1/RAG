# Uber-RAG Architecture

## Principle

One modular RAG platform with two document profiles and one shared retrieval/answer API.

```text
Web UI / CLI / Integrations
        |
        v
Public FastAPI API
        |
Auth + ACL + Audit
        |
+-------------------+--------------------+
|                                        |
Ingestion pipeline                       Query pipeline
|                                        |
Parser -> Chunker -> Embedder -> Index   Router -> Retrieval -> Rerank -> Verify
|                                        |
Storage and indexes                      LLM and citations
```

## Public API modules

- `/auth`
- `/documents`
- `/collections`
- `/ingestion`
- `/search`
- `/retrieve`
- `/chat`
- `/citations`
- `/answers/verify`
- `/eval`
- `/audit`
- `/admin`
- `/system`

## Internal services

- document service
- ingestion service
- parser service
- chunking service
- embedding service
- indexing service
- retrieval service
- reranking service
- generation service
- verifier service
- evaluation service
- audit service

## Storage layer

- PostgreSQL: metadata, ACL, users mapping, jobs, versions, audit, eval results.
- MinIO/filesystem: originals, parsed artifacts, page images, quality reports.
- Qdrant: dense/sparse vectors and metadata filters.
- OpenSearch/Tantivy: BM25, phrase, exact search, fielded search, optional DLS.

## Core data model

```json
{
  "source_id": "uuid",
  "source_type": "book|loose_document",
  "title": "string",
  "document_type": "textbook|contract|report|email|manual|memo|other",
  "language": "string",
  "version": "string",
  "tenant_id": "string",
  "acl": {
    "owner_user_id": "string",
    "group_ids": ["string"],
    "user_ids": ["string"],
    "visibility": "private|group|tenant|public"
  },
  "unit_id": "uuid",
  "unit_type": "chapter|section|paragraph|table|formula|figure|definition|page",
  "parent_id": "uuid|null",
  "heading_path": ["string"],
  "page_start": 1,
  "page_end": 2,
  "text": "string",
  "source_coordinates": {
    "page": 1,
    "bbox": [0, 0, 0, 0]
  }
}
```

## Book profile

Deep structure:

```text
Book
  -> chapters
  -> sections
  -> subsections
  -> definitions
  -> formulas
  -> tables
  -> figures
  -> examples
  -> page anchors
  -> child chunks
  -> parent sections
```

## Loose document profile

Metadata-heavy structure:

```text
Document
  -> type
  -> date
  -> author/source
  -> version
  -> tenant
  -> ACL
  -> sections
  -> tables
  -> attachments
  -> chunks
```

## Retrieval pipeline

```text
Query
  -> ACL resolver
  -> Query router
  -> exact/BM25/phrase search
  -> dense vector search
  -> sparse vector search
  -> table/formula/definition search when relevant
  -> fusion
  -> ACL recheck
  -> parent-child expansion
  -> reranking
  -> context construction
  -> LLM answer
  -> sentence-level evidence verification
  -> audited response
```
