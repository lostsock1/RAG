# Uber-RAG Tasks

## Legend

- [ ] Not started
- [~] In progress
- [x] Done
- [!] Blocked

## Phase 0: Project scaffold

- [x] Create backend app skeleton.
- [x] Create frontend app skeleton.
- [ ] Add docker compose for local services.
- [x] Add `.env.example` but never commit secrets.
- [x] Add lint, tests, formatting.
- [x] Add ADR process.

## Phase 1: Balanced foundation (gate-led)

### Gate A — Design closure

- [x] Create `docs/uber-rag/PHASE1_GATE_CHECKLIST.md`.
- [x] Freeze the Phase 1 endpoint subset in `API_CONTRACT.md`.
- [x] Freeze the Phase 1 minimum schema subset in `DOMAIN_MODEL.md`.
- [x] Translate ACL rules into explicit Gate A test cases in `SECURITY_ACL.md`.
- [x] Record any ADR or memory gaps discovered during Gate A reconciliation.

### Gate B — Security/data foundation

- [x] Implement the request context/auth seam.
- [x] Land the initial Phase 1 migration and minimum schema subset.
- [x] Implement the ACL filter builder.
- [x] Implement audit persistence.
- [x] Add and pass ACL leakage tests.

### Gate C — Operational foundation

- [x] Run the Docker dev stack on VPS (vm-1485.lnvps.cloud, `ssh rag`).
- [x] Add local Keycloak bootstrap assets for the expected realm, client, and token claims.
- [x] Verify the live Keycloak container round-trip against the configured JWKS endpoint in Docker/VPS.
- [x] Prepare a VPS for continued development and installation/testing access (`ssh lag0sta`).
- [x] Document config and environment discipline.
- [x] Make health checks pass locally.
- [x] Wire the local filesystem storage adapter for local runtime.
- [x] Establish a green CI baseline.
- [x] Close the backend auth path with JWKS-backed Keycloak/OIDC runtime verification and local fallback guardrails.

### Gate D — First product slice

- [x] Deliver authenticated document upload.
- [x] Deliver ACL read/update endpoints.
- [x] Deliver ACL-filtered document listing.
- [x] Deliver the minimal login/upload/list web UI using only the public API.

## Phase 2: Ingestion foundation

- [ ] Upload original files to local filesystem or MinIO once the object-storage adapter is implemented.
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
