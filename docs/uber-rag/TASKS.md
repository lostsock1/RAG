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

## Phase 1+2 hardening (audit 2026-05-23)

Closed 2026-05-23. Source: `docs/superpowers/plans/2026-05-23-phase-1-2-audit-and-fixes.md`.

### P0 — correctness and security (8/8 done)

- [x] P0-1 — Remove dead `try/except` block in `_get_nested_claim` (`apps/api/app/core/security.py`).
- [x] P0-2 — Delete committed `phase1.db`; add `*.db`/`*.sqlite`/`*.sqlite3` to `.gitignore`.
- [x] P0-3 — UUID-validate `tenant_id` and `user_id` from claims and dev-auth headers before they reach `build_object_key`. (OIDC group names remain string-allowed per the existing `resolve_group_ids_for_context` path.)
- [x] P0-4 — `OidcTokenVerifier.verify_bearer_token` is now async (`httpx.AsyncClient`), has a TTL cache (`oidc_jwks_ttl_seconds`, default 600), and uses `leeway=oidc_clock_skew_seconds` (default 30) for clock skew. `get_request_context` is `async def`.
- [x] P0-5 — New migration `20260523_0008_chunks_postgres_compat.py` fixes the `chunks` FK type mismatch on Postgres (was `varchar` → `uuid`). No-op on SQLite. New `test_chunks_columns_use_uuid_on_postgres` (skips when not Postgres).
- [x] P0-6 — New migration `20260523_0009_worker_id_ingestion.py` adds `worker_id` to `ingestion_runs` and `ingestion_stages`. `recover_orphaned_runs` only resets stale runs whose `worker_id != current_worker_id`. Two-runner leakage test in `test_ingestion_repository.py` proves no in-flight reclaim.
- [x] P0-7 — `create_ingestion_run` takes a `workflow_backend` parameter; upload route passes `settings.workflow_backend`; retry path preserves the original value.
- [x] P0-8 — Upload streams to `NamedTemporaryFile` in 256 KB chunks while updating a single-pass SHA-256 + byte counter; `StorageAdapter.put_object_stream` on both adapters; `UploadPayload` carries the temp path + pre-computed hash. `tracemalloc` regression test bounds peak heap delta.

### P1 — correctness gaps (8/8 done)

- [x] P1-1 — `StorageAdapter.delete_object`; `upload_document` best-effort cleanup on DB failure.
- [x] P1-2 — **Payload-side ACL filter restored for Qdrant and OpenSearch.** New `apps/api/app/services/retrieval/acl_filter.py` mirrors `build_document_acl_filter`. Retrievers now apply the ACL filter first; `allowed_document_ids` is an opt-in narrow filter on top. New ACL leakage test in `test_acl_leakage_ci.py` proves a forbidden doc cannot return even when injected into `allowed_document_ids`.
- [x] P1-3 — `LocalFilesystemStorageAdapter.materialize_for_read` copies to a `NamedTemporaryFile` (immutable source rule from `DEVELOPMENT_RULES.md`).
- [x] P1-4 — `RemoteDocumentParser` lazy `httpx.Client`, explicit `close()`, lifespan shutdown wired.
- [x] P1-5 — `DoclingDocumentParser` caches `DocumentConverter` on the instance (lazy-init).
- [x] P1-6 — `assert_dev_auth_bind_is_loopback(server_host)` at app factory; dev-auth runtime rejects when `X-Forwarded-For` is present; loud warning log on every dev-auth request.
- [x] P1-7 — `persist_chunks` atomicity: single flush after parents, single commit at end, explicit rollback on any exception. Asserts single-parent for current loose-doc shape. Rollback test induces a duplicate-`chunk_index` `IntegrityError` and proves prior chunks survive.
- [x] P1-8 — Removed unused `oidc_username_claim` setting from `Settings`.

### P2 — operability and performance (0/7 done — deferred)

- [ ] P2-1 — `OpenSearchLexicalIndexer` honors `settings.opensearch_verify_certs` and `opensearch_use_ssl` (currently hard-coded `verify_certs=False`).
- [ ] P2-2 — Add `reset_dependency_caches()` helper that clears `get_settings.cache_clear()` and `get_oidc_token_verifier.cache_clear()`; wire into conftest fixtures.
- [ ] P2-3 — `get_or_create_document_by_source_hash` IntegrityError fallback adds a 3-attempt retry loop (50 ms apart) reopening a fresh session.
- [ ] P2-4 — Narrow `recover_orphaned_runs` startup exception swallow in `main.py` to `sqlalchemy.exc.OperationalError`/`ProgrammingError`; re-raise others.
- [ ] P2-5 — `TemporalDispatcher` caches the client across `dispatch` calls; `close()` in FastAPI lifespan shutdown.
- [ ] P2-6 — `build_temporal_worker` detects real Temporal client by `isinstance(client, temporalio.client.Client)` inside `try/except ImportError` instead of the brittle `hasattr(client, "config")` check.
- [ ] P2-7 — App startup fails fast when `parser_backend=docling` + `workflow_backend=in_process` but storage is `None`.

### Out-of-scope tracking from this audit

- [ ] Pre-existing trio failure: `apps/api/app/tests/unit/test_temporal_worker.py::test_ingestion_activity_bridge_calls_pipeline_runner[trio]` (`RuntimeError: no running event loop`). Predates this work; needs separate triage.
- [ ] Exercise migration `20260523_0008` against a real Postgres on the VPS (it is no-op on SQLite where CI runs).

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
- [x] Implement streaming API (real token-level streaming via SSE).
- [x] Implement citation resolver.
- [x] Implement sentence-level verifier (substring + NLI).
- [x] Implement not-found behavior.
- [x] Implement eval harness skeleton (loader, scorer, reporter, CLI — ADR-0015).
- [x] Measure negative-answer compliance (1.00 on 23/23 questions).
- [x] Implement NLI-based answer verifier (`cross-encoder/nli-deberta-v3-base`).
- [x] Create fixture corpus (8 documents, 15 ground-truth questions).
- [ ] Wire full ingestion pipeline in test fixture (SQLite + Qdrant in-memory + OpenSearch mock + BGE-M3).
- [ ] Run baseline faithfulness measurement against substring verifier.
- [ ] Run NLI faithfulness measurement and iterate until ≥ 0.85 (or write ADR-0016).
- [ ] Run streaming load test (5 concurrent users, 30 queries, P50/P95 first-token).

**Phase 4 status (2026-05-23):** All deliverables implemented. Exit criteria: negative-answer compliance ✅ (1.00), ACL leakage ✅, streaming ✅ (real tokens). Faithfulness measurement and load testing require full pipeline fixture + running stack — tracked as remaining items above.

## Phase 5: Web UI

- [ ] Login flow.
- [ ] Upload UI.
- [ ] Ingestion status dashboard.
- [ ] ACL editor.
- [ ] Chat UI.
- [ ] Source viewer.
- [ ] Evaluation dashboard.

## Phase 6: Evaluation

- [x] Create seed goldset (heldout-v1.yaml — 170 questions).
- [x] Create eval harness (loader, scorer, reporter, runner, CLI).
- [x] Create negative tests (23 negative questions, compliance 1.00).
- [x] Create ACL leakage tests (10 questions, group-separation verified).
- [ ] Wire full pipeline ingestion fixture for faithfulness measurement.
- [ ] Run baseline faithfulness measurement.
- [ ] Run NLI faithfulness measurement and iterate.
- [ ] Backfill remaining 155 heldout questions with ground-truth chunk IDs.
- [ ] Add recall@k measurement to harness.
- [ ] Run multilingual subset (German, Portuguese).
- [ ] Add metrics dashboard.
