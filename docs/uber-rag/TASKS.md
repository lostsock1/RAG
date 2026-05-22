# Uber-RAG Tasks

## Legend

- [ ] Not started
- [~] In progress
- [x] Done
- [!] Blocked

## Phase 0: Project scaffold

- [x] Create backend app skeleton.
- [x] Create frontend app skeleton.
- [x] Add docker compose for local services.
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

- [x] Close ADR-0009 (object storage direction).
- [x] Close ADR-0010 (ingestion orchestration direction).
- [x] Close ADR-0011 (structured parsing / document-understanding architecture).
- [x] Add a SeaweedFS-ready S3-compatible storage adapter seam.
- [x] Hash uploads and reuse existing documents for serial same-user same-tenant duplicates.
- [x] Add ingestion run/stage/artifact/report tables and migrations.
- [x] Add ingestion jobs list/detail API scaffold with ACL and audit coverage.
- [x] Add parser adapter interfaces and foundation stubs for Docling/local/remote parsing.
- [x] Generate a foundation quality report summary.
- [x] Store parsed artifacts and provenance foundation records.
- [x] Enforce one canonical parsed artifact and quality report per run.
- [x] Wire active uploads to the real accepted workflow dispatcher.
- [x] Populate and expose ingestion stage progression.
- [x] Exercise the live SeaweedFS backend in runtime/integration coverage.
- [x] Replace parser stubs with real Docling-backed conversion.
- [x] Add OCR adapter execution path compatible with ADR-0011.
- [x] Harden dedup for concurrent uploads with DB-backed conflict handling.
- [x] Add retry/re-dispatch support for existing queued or failed ingestion runs.
- [x] Expand quality report fields to the richer contract-level report.
- [x] Add Temporal dispatch adapter and worker skeleton (explicit opt-in, in-process default preserved).
- [x] Prove the Temporal worker/dispatcher path against a real local Temporal service.

## Phase 3: Indexing and retrieval

- [x] Create chunking interfaces.
- [ ] Implement book profile chunking.
- [x] Implement loose document profile chunking.
- [x] Create Embedder protocol + StubEmbedder.
- [x] Create VectorIndexer + LexicalIndexer protocols with stubs.
- [x] Wire embed + index stages into PipelineRunner (7-stage pipeline).
- [x] Implement BGE-M3 real embedder adapter.
- [x] Implement Qdrant real vector indexer adapter.
- [x] Implement OpenSearch real lexical indexer adapter.
- [x] Add thin ACL-safe `/search` kickoff route and retriever seam.
- [x] Add tenant ACL bootstrap policy locking + normalized policy-aware index ACL payloads.
- [x] Implement query router.
- [x] Implement hybrid retrieval and fusion.
- [x] Add source viewer endpoint.

**Phase 3 exit criteria verified (2026-05-20):** ACL leakage ✅, citation resolution ✅, exact-string routing ✅, p50 latency 5.07 ms ✅.

## Phase 4: Reranking, generation, verification

- [x] Close the Phase 4 reranker stack decision (`bge-reranker-v2-m3` vs `bge-reranker-v2-gemma` vs `bge-reranker-v2-minicpm-layerwise`) with comparative synthesis and an ADR or explicit reconfirmation.
- [x] Implement reranker adapter behind a model-swappable `Reranker` interface (`bge-reranker-v2-m3` is the accepted Phase 4 default; the seam remains swappable for future reopen candidates).
- [x] Implement context builder.
- [x] Implement LLM adapter.
- [x] Implement chat API.
- [x] Implement streaming API.
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
