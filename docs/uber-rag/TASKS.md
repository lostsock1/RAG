# Uber-RAG Tasks

## Legend

- [ ] Not started
- [~] In progress
- [x] Done
- [!] Blocked

## Phase 0: Project scaffold

- [ ] Create backend app skeleton.
- [ ] Create frontend app skeleton.
- [ ] Add docker compose for local services.
- [ ] Add `.env.example` but never commit secrets.
- [ ] Add lint, tests, formatting.
- [ ] Add ADR process.

## Phase 1: API and security foundation

- [ ] Define auth middleware.
- [ ] Define tenant, user, group, role, scope, and ACL domain model.
- [ ] Define document and collection metadata model.
- [ ] Implement audit log model.
- [ ] Implement public API skeleton with OpenAPI docs.

## Phase 2: Ingestion foundation

- [ ] Upload original files to MinIO/filesystem.
- [ ] Hash and deduplicate files.
- [ ] Add ingestion job table.
- [ ] Add Docling parser adapter.
- [ ] Add OCR adapter interface.
- [ ] Generate quality report.
- [ ] Store parsed artifacts and provenance.

## Phase 3: Indexing and retrieval

- [ ] Create chunking interfaces.
- [ ] Implement book profile chunking.
- [ ] Implement loose document profile chunking.
- [ ] Implement OpenSearch indexing.
- [ ] Implement Qdrant indexing.
- [ ] Implement query router.
- [ ] Implement hybrid retrieval and fusion.
- [ ] Implement reranker adapter.
- [ ] Implement context builder.

## Phase 4: Chat and verification

- [ ] Implement LLM adapter.
- [ ] Implement chat API.
- [ ] Implement streaming API.
- [ ] Implement citation resolver.
- [ ] Implement sentence-level verifier.
- [ ] Implement not-found behavior.

## Phase 5: Web UI

- [ ] Login flow.
- [ ] Upload UI.
- [ ] Ingestion status dashboard.
- [ ] ACL editor.
- [ ] Chat UI.
- [ ] Source viewer.
- [ ] Evaluation dashboard.

## Phase 6: Evaluation

- [ ] Create seed goldset.
- [ ] Create synthetic needles.
- [ ] Create negative tests.
- [ ] Create ACL leakage tests.
- [ ] Create regression runner.
- [ ] Add metrics dashboard.
