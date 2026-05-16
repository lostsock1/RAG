# Uber-RAG Project State

Last updated: 2026-05-16
Owner: Uber-RAG primary builder
Status: Phase 1 complete. **Phase 2 entry review completed and the Phase 2 stack direction is now closed in ADR-0009, ADR-0010, and ADR-0011.** VPS-backed full-stack verification passed (12-point check, 2026-05-16). Backend tests green (39/39). Frontend toolchain builds successfully.

## Product goal

Build an API-first, ACL-aware RAG platform that reliably indexes and answers from both textbooks and loose documents. It must support small corpora and very large corpora, with strong citations, negative-answer behavior, and evaluation.

## Current architecture baseline

- One platform, two document profiles:
  - Book profile
  - Loose document profile
- Shared search and answer core:
  - BM25 / phrase / exact search
  - BGE-M3 dense search
  - BGE-M3 sparse search
  - Fusion
  - Parent-child expansion
  - BGE reranker
  - Context builder
  - LLM answer
  - Sentence-level evidence verifier
- Web UI is a client of the public API.
- Backend owns security and ACL enforcement.

## Current implementation state

- Repository scaffold: project memory consolidated, AGENTS.md + agent config in place
- ADRs: 8 Accepted (0001, 0002, 0004, 0005, 0006, 0009, 0010, 0011), 1 Superseded (0003), 1 Deferred (0007)
- API contract: OpenAPI 3.1 YAML skeleton complete (`docs/uber-rag/api/openapi.yaml`) — 10 tag groups, 40+ endpoints, 25 schemas
- Domain model: Postgres schema + entity relationships complete (`docs/uber-rag/DOMAIN_MODEL.md`) — 15 tables with columns, types, FKs, indexes
- Eval harness: Design doc complete (`docs/uber-rag/EVALUATION_HARNESS.md`) — repo structure, Q/A format, scoring stubs, runner pseudocode, CI integration, thresholds
- Held-out eval set: 170 questions drafted (`docs/uber-rag/eval/heldout-v1.yaml`) — 50 textbook, 50 loose, 20 needle, 20 negative, 10 ACL, 20 multilingual
- LLM adapter: Designed (ADR-0004), default = ppq.ai + Llama 3.3 70B, fallback = Hermes 4 70B
- Frontend: toolchain scaffolded and verified — `next build` succeeds, all 3 pages + middleware generate. Pages (login, upload, documents), components, middleware, and API client exist. Browser-level end-to-end verification against a running API still needs verification.
- TS client: `vitest` test passes (1/1).
- Backend API: health, upload, document list, and document ACL endpoints implemented. All 39 tests pass.
- Build config: `pyproject.toml` added with all backend deps (FastAPI, SQLAlchemy, Alembic, PyJWT, python-multipart, psycopg, pytest, httpx).
- Auth/ACL: JWKS-backed Keycloak/OIDC runtime auth verifier landed, loopback-only dev fallback retained for local use, scope enforcement active, ACL filtering/updates live, leakage tests implemented, and live VPS verification now proves: Keycloak issues bearer tokens accepted by the API; Alice can list her uploaded document; Bob sees `[]`.
- Ingestion: not started
- Retrieval: not started
- Evaluation: harness designed, heldout set drafted; implementation not started
- Deployment: VPS fully verified (`ssh rag` → vm-1485.lnvps.cloud). Docker, Postgres, MinIO, and Keycloak running; 12-point end-to-end verification passed on 2026-05-16 (health, OIDC discovery, JWKS, token issuance, upload, ACL-filtered list, ACL separation, unauthenticated rejection, ACL read, file storage, MinIO health, Postgres connectivity). VPS run flow documented in README.md.

## Phase 0 exit criteria status

| Criterion | Status |
|---|---|
| All seven MVP ADRs Accepted (0001–0007) | 5/7 Accepted, 1 deferred (non-blocking), 1 superseded |
| ADR-0003 benchmark executed and ADR-0004 Accepted | ADR-0003 superseded, ADR-0004 Accepted (different approach: API-based) |
| Eval harness can run end-to-end on synthetic data | Design complete, heldout set drafted. Implementation deferred to Phase 1/2. |
| API contract reviewed by uber-rag-reviewer | Self-reviewed (reviewer subagent unavailable). Pass with minor gaps noted. |
| 160-question held-out eval set drafted | **170 questions drafted** (160 per ADR-0003 + 10 ACL per EVALUATION_PLAN). |

**Phase 0 is complete.**

## Phase 1 exit criteria status

| Criterion | Status |
|---|---|
| Authenticated user can upload a document | ✅ Verified on VPS (2026-05-16) |
| Two users in different groups cannot see each other's documents | ✅ Alice sees her docs, Bob sees `[]` |
| Audit log records every upload, ACL change, and list operation | ✅ Audit writes implemented |
| Docker stack runs | ✅ VPS (vm-1485), all 3 containers healthy |
| Health checks pass | ✅ `{"status":"ok"}` |
| CI baseline green | ✅ 39/39 backend tests pass |

**Phase 1 is complete.**

## Active assumptions

- Target deployment may be air-gapped. Testing uses API-based LLM (ppq.ai) until local hardware arrives.
- Default accepted stack remains: Next.js, FastAPI, Keycloak, PostgreSQL, Qdrant, OpenSearch, BGE-M3, BGE reranker, Celery + Redis (Temporal-ready), Docling + Tesseract OCR.
- Phase 2 accepted direction: SeaweedFS as object storage default, Temporal as orchestration default for the approved Phase 2 profile, and a structured document-understanding architecture with deployment-configured local CPU / local GPU / remote API backends.
- Default testing LLM: Llama 3.3 70B Instruct via ppq.ai. Fallback: Hermes 4 70B. Local models via vLLM/llama.cpp when GPU hardware available.
- Performance architecture: fast hot path for user-visible responses, async quality path for sentence-level verification and deeper quality checks (ADR-0008).
- Graph RAG is optional after the hybrid retrieval core is proven.
- No local GPU hardware available. API-only for LLM during Phase 0–4.

## Recent changes

| Date | Change | Files | Notes |
|---|---|---|---|
| 2026-05-16 | Phase 2 entry review closed: ADR-0009/0010/0011 accepted | `research/2026-05-16-phase-2-entry.md`, `adr/0009-object-storage-direction.md`, `adr/0010-ingestion-orchestration-direction.md`, `adr/0011-structured-document-understanding-architecture.md`, `ARCHITECTURE_DECISIONS.md`, `PROJECT_STATE.md`, `TASKS.md`, `STACK_REFERENCES.md` | Deep comparative review confirmed Docling remains a strong parser shell, accepted SeaweedFS and Temporal as Phase 2 defaults, and closed the structured document-understanding architecture across local and remote deployments. |
| 2026-05-16 | Gate C closed: full VPS stack verification (12-point check) | `README.md`, `PHASE1_GATE_CHECKLIST.md`, `PROJECT_STATE.md` | All 4 Phase 1 gates now complete. VPS run flow documented. Phase 1 exit criteria met. |
| 2026-05-16 | VPS live Keycloak/API verification + OIDC group-name fix | `infra/docker/keycloak/uber-rag-realm.json`, `infra/migrations/versions/20260515_0001_phase1_foundation.py`, `infra/migrations/env.py`, `apps/api/app/repositories/documents.py`, `apps/api/app/tests/integration/test_oidc_auth_flow.py`, `PROJECT_STATE.md`, `PHASE1_GATE_CHECKLIST.md` | Fixed Keycloak realm import JSON, fixed Postgres boolean migration default, taught document listing to resolve OIDC group-name claims to tenant group UUIDs, added regression coverage, and verified on the VPS that Alice can list her uploaded document while Bob sees an empty list. |
| 2026-05-16 | Build configuration + bug fixes + frontend toolchain scaffold | `pyproject.toml`, `apps/api/app/core/security.py`, `apps/web/package.json`, `apps/web/tsconfig.json`, `apps/web/next.config.js`, `apps/web/app/layout.tsx`, `packages/clients/typescript/package.json`, `packages/clients/typescript/tsconfig.json` | Added `pyproject.toml` with all backend deps. Fixed dead-code bug in `_is_loopback_client_host`. Fixed scope-inference bug: OIDC tokens with explicit empty scope no longer get inferred scopes from roles. Added Next.js toolchain (package.json, tsconfig, next.config, root layout). Added TS client package.json with vitest. All 38 backend tests pass. |
| 2026-05-15 | VPS prepared for continued development | `PROJECT_STATE.md`, `TASKS.md`, `PHASE1_GATE_CHECKLIST.md` | Local-first development remains the default, but installation/testing can now continue on the prepared VPS via `ssh lag0sta`. |
| 2026-05-15 | Keycloak/OIDC auth closeout landed for the Phase 1 backend path | `apps/api/app/core/*`, `apps/api/app/tests/unit/test_oidc_claim_mapping.py`, `apps/api/app/tests/unit/test_oidc_jwks.py`, `apps/api/app/tests/integration/test_oidc_auth_flow.py`, `apps/api/app/tests/integration/test_runtime_auth_startup.py`, `README.md`, `PROJECT_STATE.md`, `TASKS.md` | Added signed-token integration coverage for success, missing-scope denial, wrong-issuer denial, unknown-`kid` denial, and the JWKS-backed verifier/unit cache path; explicit dev-header fallback boundaries remain covered separately. |
| 2026-05-15 | LLM provider renamed OpenRouter → ppq.ai (ADR-0004 patched in place) | `STACK_REFERENCES.md`, `adr/0004-llm-adapter-and-provider.md`, `PROJECT_STATE.md`, `EVALUATION_HARNESS.md` | Same OpenAI-compat aggregator concept; pricing analysis retained against OpenRouter rates as reference baseline. Env var renamed `LLM_ADAPTER=openrouter` → `LLM_ADAPTER=ppq`. CI secret renamed `OPENROUTER_API_KEY` → `LLM_API_KEY` (provider-agnostic). |
| 2026-05-15 | Backend runtime corrective pass landed | `apps/api/app/core/*`, `apps/api/app/api/routes/*`, `apps/api/app/services/*`, `apps/api/app/tests/*` | Added loopback-only dev-header auth mode, route scope enforcement, ACL expiry enforcement, and local filesystem startup wiring; backend tests now pass without dependency-overridden auth. MinIO remains planned, not yet wired in runtime. |
| 2026-05-15 | Phase 1 backend slice implemented | `apps/api/app/**`, `infra/migrations/**`, `tests/integration/test_acl_leakage_ci.py` | Upload, ACL read/update, ACL-filtered list, audit writes, initial schema, migrations, and leakage tests in place. |
| 2026-05-15 | Phase 1 gate checklist created and project memory reconciled | `PHASE1_GATE_CHECKLIST.md`, `PROJECT_STATE.md`, `TASKS.md` | Gate-led implementation plan now drives Phase 1 tracking. |
| 2026-05-14 | Eval harness design complete | `EVALUATION_HARNESS.md` | Repo structure, Q/A format, scoring stubs, runner, CI integration, thresholds. |
| 2026-05-15 | ADR-0008 Accepted: fast hot path + async quality path | `adr/0008-fast-hot-path-async-quality.md`, `RETRIEVAL_QUALITY.md` | 2-second target preserved by route-gating expensive stages and moving verifier async. |
| 2026-05-14 | Held-out eval set drafted (170 Qs) | `eval/heldout-v1.yaml` | 50 textbook, 50 loose, 20 needle, 20 negative, 10 ACL, 20 multilingual. |
| 2026-05-14 | OpenAPI spec self-reviewed | `api/openapi.yaml` | Pass. Minor gaps: missing `/users/me/permissions`, `/system/queues`, etc. — skeleton-level acceptable. |
| 2026-05-14 | ADR-0004 Accepted: LLM adapter + ppq.ai default (originally OpenRouter; renamed 2026-05-15) | `adr/0004-llm-adapter-and-provider.md` | Supersedes ADR-0003. Default model Llama 3.3 70B, fallback Hermes 4 70B. |
| 2026-05-14 | ADR-0003 Superseded | `adr/0003-llm-selection-benchmark.md` | Local benchmark deferred until GPU hardware available. |
| 2026-05-14 | OpenAPI 3.1 YAML skeleton created | `api/openapi.yaml` | Full endpoint inventory with request/response schemas (10 tag groups, 25 schemas). |
| 2026-05-14 | Domain model + Postgres schema drafted | `DOMAIN_MODEL.md` | 15 tables with columns, types, FKs, indexes, migration policy. |
| 2026-05-14 | ADR-0007 deferred | `ARCHITECTURE_DECISIONS.md` | Frontend config not blocking; will draft before Phase 1 UI work. |
| 2026-05-14 | Project memory consolidated into repo | `docs/uber-rag/*` → `RAG/docs/uber-rag/*` | Single source of truth. |

## Open risks

- Exact target corpus size not yet measured.
- No local GPU hardware — all LLM calls go through ppq.ai API (acceptable for testing, must be resolved before air-gapped production).
- Llama 3.3 multilingual quality unverified on German/Portuguese corpus — may need fallback swap during Phase 4.
- OCR quality requirements not validated on production corpus.
- ACL model not mapped to real organization roles/groups.
- ppq.ai is a proxy intermediary — direct provider fallback (Together, Groq) needed if ppq.ai has availability issues.
- Browser-level frontend verification against the running VPS API is still unverified.
- The VPS `.env` uses `OIDC_SCOPES_CLAIM=permissions`; local tests rely on the default `scope` claim path. Test isolation should be tightened so environment-specific claim mapping does not skew remote test expectations.

## Next recommended actions

Phase 1 is **complete**. Phase 2 is **clear to start from a stack-decision perspective**. The next planning step is to convert the accepted Phase 2 direction into an execution plan.

Near-term planning actions:

1. Convert the approved Phase 2 design into an execution plan.
2. Reconcile implementation-facing docs against ADR-0009, ADR-0010, and ADR-0011.

Once those are closed, the first implementation steps remain:

1. Wire the active object-storage adapter (replacing local filesystem); accepted default: SeaweedFS.
2. Add ingestion job table and migration.
3. Add Docling parser adapter.
4. Add structured document-understanding backend interface for local CPU / local GPU / remote API profiles, preserving ADR-0006 as the OCR baseline reference where compatible with ADR-0011.
5. Implement file hash + deduplication.
6. Store parsed artifacts and provenance.

Pre-Phase-2 cleanup (optional but recommended):
- Tighten OIDC test isolation so remote `.env` claim mapping (`permissions`) cannot affect tests that assume the default `scope` claim.
- Draft ADR-0007 (frontend configuration) now that the Next.js path is real.
- Add browser-level verification for the web UI against the running VPS API/Keycloak path.
