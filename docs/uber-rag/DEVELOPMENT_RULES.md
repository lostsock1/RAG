# Development Rules

## Non-negotiables

- API-first: all UI operations must be API operations.
- Backend enforces ACL; frontend never enforces security alone.
- No direct frontend access to PostgreSQL, MinIO, Qdrant, OpenSearch, LLM, embeddings, reranker, or workers.
- Every generated answer must be backed by authorized evidence or return not-found.
- Every ingestion artifact must be traceable to original source, parser version, page, and chunk.
- Every destructive operation requires tombstone/audit behavior.
- Every architecture change requires an ADR or decision ledger update.

## Code organization preference

```text
apps/
  web/                 Next.js frontend
  api/                 FastAPI public API
services/
  ingestion/
  parser/
  embedding/
  indexing/
  retrieval/
  reranking/
  generation/
  verifier/
packages/
  shared-schemas/
  clients/
infra/
  docker/
  k8s/
  migrations/
docs/
  uber-rag/
tests/
  unit/
  integration/
  eval/
```

## Backend rules

- Use typed request/response models.
- Keep adapters behind interfaces.
- Add explicit error models.
- Error messages must be user-actionable in plain language — state what happened and what to do next (e.g. "Document parsing failed: the uploaded file does not contain extractable text. Try running OCR first or upload a text-based PDF."), never a bare stack trace or internal code. Reviewer gate: user-facing clarity. Phase F's exit criterion ("a non-engineer can…") makes this testable in the UI.
- Add idempotency keys for ingestion and reindexing operations.
- Log audit events for security-relevant actions.
- Avoid long synchronous operations in API handlers.

## Frontend rules

- All data via public API client.
- Show loading, error, denied, empty, and partial states.
- Show citations and source details.
- Upload and ingestion UI must surface parser warnings and quality reports.
- ACL UI must display effective access, not just assigned groups.

## Ingestion rules

- Original file is immutable after upload.
- Store source hash.
- Store parser version and options.
- Store parsed artifacts.
- Generate quality report.
- Chunking must preserve heading path, page range, coordinates when possible, and source id.
- Reindexing must not break old audit records.

## Retrieval rules

- Always apply ACL filters before retrieval.
- Recheck ACL after fusion and before source fetch.
- Use exact/phrase route for IDs, quotes, page requests, and rare terms.
- Use dense/sparse route for conceptual questions.
- Use book hierarchy route for textbook questions.
- Use table/formula route when the query implies structured content.
- Use reranking before generation.
- Keep source passages small enough to cite but expand to parent context when needed.

## Testing rules

Minimum test types:

- unit tests for ACL filter construction
- integration tests for document upload and ingestion status
- retrieval tests for exact and semantic queries
- negative answer tests
- citation resolver tests
- ACL leakage tests
- deletion/tombstone tests
- API contract tests

## Change discipline

These rules earn the project the right to change its mind without breaking continuity.

- **No stack swap without an ADR and a benchmark result.** Swapping a vector store, lexical engine, embedding model, reranker, LLM, parser, or orchestration framework requires (a) an Accepted ADR explaining the trigger, and (b) a measured result on the project's own evaluation harness showing the new choice wins on the metrics that matter. Public benchmarks alone are not sufficient evidence.
- **No ACL-touching feature without a leakage test in the same PR.** Any change to authentication, authorization, retrieval filters, citation rendering, source fetch, or audit logging must include at least one test that proves a forbidden document does not leak through the changed path. The leakage test must fail without the new code and pass with it. The PR description names the threat scenario in plain language.
- **No new runtime dependency without a `STACK_REFERENCES.md` entry.** Adding a Python or npm package that is more than a small utility — anything that becomes a service, model runtime, database client, parser, workflow engine, or security primitive — requires a `STACK_REFERENCES.md` entry recording: name, version pinned, official-doc URL, access date, why this over the alternatives, and implementation impact. Tiny utilities (typing helpers, formatters) do not require this.
- **No architecture change without an ADR.** Restated from Non-negotiables for emphasis. "Architecture change" includes: introducing or removing a service boundary, changing a public API contract, modifying an ACL enforcement layer, changing the retrieval pipeline shape, or changing the persistence model for a core entity (documents, chunks, runs, audit events, ACL grants).
