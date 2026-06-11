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

### P2 — operability and performance (7/7 done — closed 2026-06-10, master plan task A4)

- [x] P2-1 — `OpenSearchLexicalIndexer` honors `verify_certs`/`use_ssl` (constructor params, secure default `verify_certs=True`, warnings suppressed only when verification explicitly disabled).
- [x] P2-2 — `reset_dependency_caches()` helper in `app/core/caches.py` clears both `get_settings` and `get_oidc_token_verifier` caches; named fixture in new `apps/api/app/tests/conftest.py`.
- [x] P2-3 — `get_or_create_document_by_source_hash` IntegrityError fallback retries the live-document lookup 3 times, 50 ms apart (fresh session per attempt), before re-raising.
- [x] P2-4 — `recover_orphaned_runs` startup swallow narrowed to `sqlalchemy.exc.OperationalError`/`ProgrammingError`; other exceptions fail startup.
- [x] P2-5 — `TemporalDispatcher` caches the client across `dispatch` calls; idempotent `close()` awaited in FastAPI lifespan shutdown when the dispatcher has one.
- [x] P2-6 — `build_temporal_worker` detects the real Temporal client by `isinstance(client, temporalio.client.Client)` inside the ImportError guard; duck-typed stubs with a `config` attribute get the skeleton.
- [x] P2-7 — App startup fails fast when `parser_backend=docling` + `workflow_backend=in_process` and no storage is configured (pre-injected `app.state.document_storage` counts as configured; storage-less test apps opt out via `parser_backend=""`).

### Out-of-scope tracking from this audit

- [x] Pre-existing trio failure: `apps/api/app/tests/unit/test_temporal_worker.py::test_ingestion_activity_bridge_calls_pipeline_runner[trio]` — closed by replacing `asyncio.to_thread` with `anyio.to_thread.run_sync` in `temporal_workflow.run_ingestion_activity`. Test suite reaches truly green (415 passed, 1 skipped).
- [x] Exercise migration `20260523_0008` against a real Postgres on the VPS — done 2026-05-23. alembic head reached `20260523_0009`, chunks columns confirmed `uuid`/`boolean` types via `information_schema.columns`. Two follow-on bugs surfaced and fixed during the deploy: 0006 boolean default `'0'` (now dialect-aware) and 0007 `sa.table` reflection missing columns. All committed.
- [x] Add a Postgres-backed `test_migrations` job to CI so the next dialect-specific migration bug surfaces before deploy day. — `.github/workflows/tests.yml` ships two jobs: `tests-sqlite` (full pytest minus live-Temporal) and `tests-postgres` (alembic upgrade head against postgres:17 + `test_chunks_columns_use_uuid_on_postgres`). First CI bootstrap for this repo.

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
- [x] Wire full ingestion pipeline in test fixture (SQLite + Qdrant in-memory + OpenSearch mock + BGE-M3) — done 2026-05-23 (`tests/eval/conftest.py` `eval_stack`).
- [x] Run baseline faithfulness measurement against substring verifier — done 2026-05-23 (0.067).
- [x] Run NLI faithfulness measurement and iterate until ≥ 0.85 (or write ADR-0016) — done 2026-05-23 (not_contradicted 1.000; entailment 0.113/0.133 non-functional; ADR-0016 revised).
- [x] Run streaming load test (5 concurrent, P50/P95 first-token) — done 2026-05-23 (P50 ~2.5s pre-buffering); **re-measured 2026-06-10 post-evidence-safe-buffering: P50 5.97s / P95 10.75s — ADR-0017 SLA fails by design pending ADR-0018** (`tests/eval/reports/load_post_buffering.json`).

**Phase 4 status (reconciled 2026-06-10):** CLOSED. All four exit criteria were met with measured numbers on 2026-05-23. The subsequent evidence-safe streaming fix (`1ce0d30`) deliberately moved verification into the first-token path and temporarily broke the ADR-0017 SLA; **resolved the same day by ADR-0018 sentence-incremental verified streaming (master plan Phase B): P50 first-verified-token 3.11s / P95 3.22s, SLA passing.** Forward work lives in `docs/superpowers/plans/2026-06-10-sota-master-plan.md`.

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
- [x] Wire full pipeline ingestion fixture for faithfulness measurement — done 2026-05-23 (duplicate of the Phase 4 item).
- [x] Run baseline faithfulness measurement — done 2026-05-23 (0.067, substring verifier).
- [x] Run NLI faithfulness measurement and iterate — done 2026-05-23 (ADR-0016; re-measured entailment 0.133 post-hardening).
- [x] Backfill heldout questions with ground truth — span-anchored design + 60 evidence-backed questions (C1+C5, 2026-06-11). Remaining 110 are non-fixture-corpus (contracts/reports/emails) deferred until those corpora exist.
- [x] Add recall@k measurement to harness — done 2026-06-11 (recall@{5,10,20}, MRR@10, nDCG@{5,10,20}, grouped per-span semantics).
- [x] Run multilingual subset (German, Portuguese) — done 2026-06-11. DE n=7, PT n=7; both 1.000 recall@10/nDCG@10/MRR@10 on the C5 corpus (retrieval-only, BGE-M3 dense).
- [ ] Add metrics dashboard.

## Master plan Phase E: eval-gated retrieval upgrades (2026-06-11 →)

Canonical specs: `docs/superpowers/plans/2026-06-10-sota-master-plan.md` § Phase E.

- [x] E0a — answer-style fix: replace `rank=N` machine prompt headers with human `[Source N: title — locator]` labels + anti-meta-discourse system rule — done 2026-06-11 (`llm_backend.py`, suite 494 passed). Follow-up done same day: D3 c1 re-measured — grounding faithfulness 0.578 → **0.9007, c1 PASSES**; then the RoBERTa-L c3 path was executed offline (classification recipe path added to the verifier): c1 0.7632 FAIL / c2 1.00 PASS / c3 1918 ms FAIL — **ADR-0019 rejection confirmed on dual grounds, reopen paths exhausted** (GPU/ONNX-era triggers remain).
- [x] E1 — parent-child expansion: audit and wire (eval-gated) — done 2026-06-11. Audit: expansion existed in production but pre-rerank, id-replacing (whole-doc parents!), uncapped, ungated, eval-stubbed-off. Conformed to spec (after-rerank, leaf chunk_id kept, 2048-char leaf-centered window, content-true dedupe, `retrieval_parent_expansion=True`); repo id-normalization fixed. Eval gate caught parent-id dedupe regression (recall@10 1.0→0.9), content-true dedupe restored parity: ON vs baseline all deltas 0.0000, positive control 1200 parents resolved. Suite 507 passed.
- [ ] E2 — ADR-0020 + contextual chunk augmentation (breadcrumb + LLM arms, bake-off). Blocked on harder distractor corpus or nDCG/MRR-based judging (C5 caveat).
- [ ] E3 — ADR-0021 + query understanding (multi-query + decomposition, route-gated).
- [ ] E4 — reindex CLI + conditional embedder/reranker bake-offs.
- [ ] E5 — answering-LLM bake-off (ADR-0004 scheduled reopen).
