# Uber-RAG

**API-first, ACL-aware RAG platform for textbooks and loose documents — backend
pipeline, hybrid retrieval, chat, sentence-incrementally verified streaming, and
eval harness implemented. Phases 0–4 closed with measured evidence; active roadmap
in `docs/superpowers/plans/2026-06-10-sota-master-plan.md` (Phases A–H; A+B complete).**

![Python](https://img.shields.io/badge/python-3.12+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-316192)
![Qdrant](https://img.shields.io/badge/Qdrant-vector-DC244C)
![OpenSearch](https://img.shields.io/badge/OpenSearch-lexical-005EB8)
![Keycloak](https://img.shields.io/badge/Keycloak-OIDC-4D4D4D)
![Status](https://img.shields.io/badge/status-backend%20MVP%20%2B%20verified%20streaming%20(ADR--0018)%2C%20retrieval%20measurement%20next-yellow)
![License](https://img.shields.io/badge/license-MIT-brightgreen)

---

> **⚠️ This project is not production-ready.** The backend MVP is substantial:
> upload → parse → chunk → embed → index, hybrid retrieval, reranking, chat,
> citation resolution, sentence-incrementally verified streaming (ADR-0018:
> every sentence verified before emission, P50 first-verified-token 3.1s under
> 5-concurrent load, ADR-0017 SLA passing), ACL leakage tests, and an eval
> harness. The big gaps are retrieval-quality measurement, a true support-metric
> verifier, the book profile, and the frontend. See
> [What's Missing](#whats-missing).

---

## What's Built

### Ingestion Pipeline ✅

A 7-stage async pipeline processes uploaded documents end-to-end:

```
upload ──► parse ──► persist ──► chunk ──► embed ──► index_qdrant ──► index_opensearch ──► quality_report
```

| Stage | Implementation | Status |
|-------|---------------|--------|
| Parse | Docling (local CPU), remote HTTP adapter | ✅ Real, tested |
| Chunk | `LooseDocumentChunker` — structure-aware paragraph splitting, atomic tables, parent-child hierarchy | ✅ Real, tested (150 tests) |
| Embed | BGE-M3 — 1024-dim L2-normalized dense + lexical sparse vectors | ✅ Real, tested |
| Index (dense) | Qdrant — cosine similarity on named vectors, auto-collection creation | ✅ Real, tested |
| Index (sparse) | OpenSearch — BM25/phrase/exact, standard analyzer, auto-index creation | ✅ Real, tested |
| Quality report | Per-run quality metadata with OCR provenance | ✅ Real, tested |

The pipeline runs in-process by default. Temporal workflow dispatch is available
as an explicit opt-in (`workflow_backend: temporal`) — live proof passed against
a local Temporal dev server.

### Auth & ACL ✅

- OIDC via Keycloak with JWKS-backed token verification
- Loopback dev fallback for local development (`AUTH_MODE=dev`)
- Per-tenant ACL bootstrap policies with deterministic `sensitivity_rank`
- Tenant-scoped visibility (`private | group | tenant | public`)
- ACL filtering at upload, list, and search layers
- Verified: Alice can list her documents; Bob sees `[]`

### API Endpoints ✅

| Endpoint | Status |
|----------|--------|
| `GET /api/v1/system/health` | ✅ |
| `POST /api/v1/documents/upload` | ✅ |
| `GET /api/v1/documents` | ✅ ACL-filtered |
| `GET /api/v1/documents/{id}/acl` | ✅ |
| `POST /api/v1/ingestion/jobs/{id}/retry` | ✅ |
| `GET /api/v1/ingestion/jobs` | ✅ |
| `POST /api/v1/search` | ✅ Hybrid retrieval path behind explicit config; truthful `503` when unavailable |
| `GET /api/v1/search/sources/{chunk_id}` | ✅ ACL-rechecked source viewer |
| `POST /api/v1/chat` | ✅ Blocking chat with retrieval, context, LLM, verification, citations |
| `POST /api/v1/chat/stream` | ✅ Sentence-incrementally verified SSE (ADR-0018): each sentence verified before emission; retract/truncate policy on failure |
| `POST /api/v1/citations/resolve` | ✅ ACL-safe citation resolution |
| `POST /api/v1/answers/verify` | ✅ Sentence-level answer verification |

### Retrieval, Answering, and Evaluation ⚠️

Implemented backend slices:

- Query router, OpenSearch lexical retrieval, Qdrant dense/sparse retrieval, reciprocal-rank fusion, and source viewer.
- BGE-M3 embedder and BGE-reranker-v2-m3 adapter behind explicit runtime config.
- Context builder, LLM backend seam with deterministic stub and ppq/OpenAI-compatible adapter.
- Blocking chat and SSE chat endpoints share the same ACL-safe search path.
- Streaming chat is evidence-safe and incremental (ADR-0018): every sentence is verified before its text is emitted; a mid-stream verification failure retracts (default) or truncates per `stream_verification_policy`.
- Eval harness exists with fixture corpus, negative-answer tests, NLI verifier tests, and load-test scaffolding.

Honest caveats:

- The current headline “faithfulness” number is measured with ADR-0016 `not_contradicted` mode. That is a contradiction guardrail, not a true source-support metric. The Phase D grounding-verifier candidate (MiniCheck, ADR-0019) was measured 2026-06-11 and **rejected with data**: it catches 100% of fabrications the guardrail misses (the blind spot is real and total), but answer meta-discourse (incl. a `rank=N` label leak from the prompt into user-visible answers — logged for fixing) and ~4 s/sentence CPU latency failed the frozen promotion bars. The grounding backend remains config-selectable, and a hallucination canary suite now guards the blind spot in nightly CI.
- Streaming latency (5 concurrent, real ppq + NLI, 2026-06-10 after ADR-0018): **P50 first-verified-token 3.11s, P95 3.22s — ADR-0017 SLA (5s/10s) passing**, with every emitted sentence individually verified. “First token” means “first verified sentence.” The ADR-0008 ~2s ambition remains provider-bound (local LLM serving is master plan Phase G).
- The streaming path is deliberately stricter than blocking `/chat`: it gates every sentence, while blocking tolerates up to `nli_unsupported_ratio` unsupported sentences (ADR-0016/0018).
- Qdrant payload ACL filtering now enforces expiry via a numeric `expires_at_ts` field (2026-06-10). Fail-closed: corpora indexed before that date (including the VPS) return no Qdrant results until re-ingested.

### Storage ✅

- Local filesystem adapter (default)
- S3-compatible adapter (SeaweedFS-ready)
- Storage materialization seam for parsers (yields local path regardless of backend)

### Deployment ✅

- VPS deployed and verified (12-point check passed 2026-05-23, against alembic head `20260523_0009`)
- Docker Compose stack: Postgres, MinIO, Keycloak, Temporal
- 12-point end-to-end verification passed (2026-05-23 — earliest re-verified after Phase 1+2 hardening landed)
- 440 backend tests green, 3 skipped (was 203 at Phase 1; +237 from Phase 2/3/4/audit/Phase-A work)
- Note: the VPS Qdrant corpus predates the 2026-06-10 `expires_at_ts` change and needs re-ingest before Qdrant retrieval returns results there

---

## What's Missing

### Not Yet Complete

| Component | Status | Notes |
|-----------|--------|-------|
| **Retrieval quality measurement** | ❌ Not started | No recall@k/nDCG yet; 155 of 170 heldout questions skeletal — master plan Phase C |
| **True support-metric verifier** | ❌ Not started | `not_contradicted` is a guardrail; grounding verifier (MiniCheck-class) is master plan Phase D |
| **Frontend E2E verification** | ❌ Not done | Next.js pages exist; current local build was not re-verified because dependencies were not installed — master plan Phase F |
| **Book profile chunking** | ❌ Not started | Only `LooseDocumentChunker` implemented — master plan Phase F |
| **Graph RAG / advanced retrieval** | ❌ Not started | Eval-gated menu — master plan Phase H |

Resolved in the 2026-06-10 Phase A pass: load-evidence refresh, faithfulness
metric wording (ADR-0016 re-measurement note), docs reconciliation, eval-artifact
policy (canonical JSON committed, logs ignored), P2 operability items 7/7, Qdrant
payload expiry enforcement (`expires_at_ts`).

Resolved in the 2026-06-10 Phase B pass: streaming TTFT — sentence-incremental
verified streaming (ADR-0018) + process-wide NLI verification gate restored the
ADR-0017 SLA (P50 3.11s / P95 3.22s first-verified-token at 5 concurrent) with
per-sentence evidence discipline, and fixed per-request NLI model reloading in
production.

### Partially Implemented

| Component | Status | Notes |
|-----------|--------|-------|
| **Search** | ⚠️ Config-gated | Hybrid retriever implemented; returns `503` when runtime dependencies/config are unavailable |
| **Frontend** | ⚠️ Scaffold only | Login, upload, documents pages exist; not tested E2E |
| **TS client** | ⚠️ Minimal | 1 test passing (`vitest`) |

---

## Architecture (Target)

```
┌──────────────────────────────────────────────────┐
│                    CLIENTS                        │
│   Web UI (Next.js)  │  API consumers  │  SDK     │
└──────────────────────┬───────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────┐
│              PUBLIC API (FastAPI)                 │
│   /auth  /documents  /collections  /ingestion    │
│   /search  /retrieve  /chat  /citations          │
│   /answers/verify  /eval  /audit  /admin         │
│   /system/health                                  │
└───────┬──────────────────────────────┬───────────┘
        │                              │
   ┌────▼─────┐                  ┌────▼──────┐
   │  Auth    │                  │  Ingestion│
   │  OIDC    │                  │  Pipeline │
   │  JWKS    │                  │  7-stage  │
   │  ACL     │                  │  async    │
   └──────────┘                  └─────┬─────┘
                                       │
        ┌──────────────────────────────┼──────────────────┐
        │                              │                  │
   ┌────▼─────┐  ┌──────────┐  ┌──────▼──────┐  ┌───────▼──────┐
   │ Postgres │  │  MinIO   │  │   Qdrant    │  │  OpenSearch  │
   │ metadata │  │  files   │  │   dense +   │  │  BM25/phrase │
   │ ACL      │  │  parsed  │  │   sparse    │  │  exact       │
   │ audit    │  │  output  │  │   vectors   │  │  fielded     │
   └──────────┘  └──────────┘  └─────────────┘  └──────────────┘
```

The ingestion path and the main query/answer path are implemented as backend
slices. `/retrieve`, `/eval`, admin/audit listing, and production-grade frontend
flows remain incomplete.

---

## Tech Stack

| Layer | Technology | Status |
|-------|-----------|--------|
| API | FastAPI + Pydantic v2 | ✅ Active |
| Auth | Keycloak + PyJWT + OIDC | ✅ Active |
| Database | PostgreSQL 16 + SQLAlchemy 2.0 + Alembic | ✅ Active |
| File storage | Local FS / MinIO (S3 adapter) | ✅ Active |
| Vector DB | Qdrant | ✅ Active |
| Search engine | OpenSearch | ✅ Active |
| Parsing | Docling (local CPU) / HTTP adapter (remote) | ✅ Active |
| Embedding | BGE-M3 (1024-dim + sparse) | ✅ Active |
| Orchestration | Temporal (optional, opt-in) | ✅ Working |
| Frontend | Next.js 15 + React 19 | ⚠️ Scaffold only |
| LLM Answering | ppq.ai + Llama 3.3 70B via internal adapter | ✅ Wired behind config |
| Reranking | BGE-reranker-v2-m3 | ✅ Wired behind config |
| Tests | pytest + httpx | ✅ 440 passed, 3 skipped locally (post Phase A) |

---

## Quick Start

See `AGENTS.md` for agent orientation and `docs/uber-rag/PROJECT_STATE.md`
for full implementation status.

### Local development

```bash
git clone https://github.com/lostsock1/RAG.git
cd RAG
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,temporal]"

cp .env.example .env
# Set AUTH_MODE=dev for local dev (loopback-only bearer tokens)
# Set LOCAL_STORAGE_DIR=/absolute/path/for/document-storage

docker compose -f infra/docker/docker-compose.yml up -d

# Run tests
pytest apps/api/app/tests/ -v
```

### OIDC mode (with Keycloak)

```bash
# .env
AUTH_MODE=oidc
OIDC_ISSUER_URL=http://localhost:8080/realms/uber-rag
OIDC_AUDIENCE=uber-rag-api
OIDC_JWKS_URL=http://localhost:8080/realms/uber-rag/protocol/openid-connect/certs
LOCAL_STORAGE_DIR=/absolute/path/for/document-storage

# Request a token
curl -X POST http://localhost:8080/realms/uber-rag/protocol/openid-connect/token \
  -d 'grant_type=password' -d 'client_id=uber-rag-api' \
  -d 'username=alice' -d 'password=alicepass'
```

### VPS deployment

Deployed on a Debian VPS. Full 12-point verification
passed (2026-05-23 against alembic head `20260523_0009` after the Phase 1+2
hardening pass).

```bash
ssh rag
cd ~/RAG
sudo docker compose -f infra/docker/docker-compose.yml up -d
source .venv/bin/activate
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > uvicorn.log 2>&1 &
curl -s http://localhost:8000/api/v1/system/health
```

---

## Project Structure

```
RAG/
├── apps/
│   ├── api/                    # FastAPI backend
│   │   └── app/
│   │       ├── main.py         # application factory
│   │       ├── routers/        # /auth, /documents, /ingestion, /search, ...
│   │       ├── services/       # document, ingestion, chunking, embedding, indexing
│   │       ├── db/             # SQLAlchemy models, repositories, migrations
│   │       ├── core/           # config, security, ACL, OIDC verifier
│   │       └── tests/          # 417 passing locally (unit + integration, excluding live Temporal)
│   └── web/                    # Next.js frontend (scaffold)
├── infra/
│   ├── docker/                 # Compose stack, Keycloak realm import
│   └── migrations/             # Alembic
├── packages/
│   └── clients/                # TypeScript API client (minimal)
├── docs/
│   ├── uber-rag/               # Architecture, ADRs, API contract, project state
│   └── superpowers/            # Planning and design documents
├── pyproject.toml              # Backend dependencies
└── AGENTS.md                   # AI agent orientation
```

---

## License

MIT
