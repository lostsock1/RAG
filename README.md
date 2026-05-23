# Uber-RAG

**API-first, ACL-aware RAG platform for textbooks and loose documents — backend
pipeline, hybrid retrieval, chat, verification, and eval harness implemented;
Phase 4 closeout still needs fresh post-streaming-fix measurements.**

![Python](https://img.shields.io/badge/python-3.12+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-316192)
![Qdrant](https://img.shields.io/badge/Qdrant-vector-DC244C)
![OpenSearch](https://img.shields.io/badge/OpenSearch-lexical-005EB8)
![Keycloak](https://img.shields.io/badge/Keycloak-OIDC-4D4D4D)
![Status](https://img.shields.io/badge/status-backend%20MVP%20implemented%2C%20Phase%204%20evidence%20refresh%20needed-yellow)
![License](https://img.shields.io/badge/license-MIT-brightgreen)

---

> **⚠️ This project is not production-ready.** The backend MVP is substantial:
> upload → parse → chunk → embed → index, hybrid retrieval, reranking, chat,
> citation resolution, sentence verification, ACL leakage tests, and an eval
> harness exist. Honest Phase 4 closeout still requires fresh load/eval evidence
> after the evidence-safe streaming change and clearer metric wording around
> `not_contradicted` faithfulness. See [What's Missing](#whats-missing).

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
| `POST /api/v1/chat/stream` | ✅ Evidence-safe SSE: generated tokens are buffered until verification passes |
| `POST /api/v1/citations/resolve` | ✅ ACL-safe citation resolution |
| `POST /api/v1/answers/verify` | ✅ Sentence-level answer verification |

### Retrieval, Answering, and Evaluation ⚠️

Implemented backend slices:

- Query router, OpenSearch lexical retrieval, Qdrant dense/sparse retrieval, reciprocal-rank fusion, and source viewer.
- BGE-M3 embedder and BGE-reranker-v2-m3 adapter behind explicit runtime config.
- Context builder, LLM backend seam with deterministic stub and ppq/OpenAI-compatible adapter.
- Blocking chat and SSE chat endpoints share the same ACL-safe search path.
- Streaming chat is now evidence-safe: unsupported generated text is never emitted as token events.
- Eval harness exists with fixture corpus, negative-answer tests, NLI verifier tests, and load-test scaffolding.

Honest caveats:

- The current headline “faithfulness” number is measured with ADR-0016 `not_contradicted` mode. That is a contradiction guardrail, not a true source-support metric.
- Streaming latency numbers need to be re-run after the token-buffering fix because “first token” now means “first verified token,” not raw LLM token.
- Qdrant payload-side ACL filtering intentionally does not enforce expiry; SQL-side ACL filtering and OpenSearch payload filtering do. A numeric `expires_at_ts` payload is the likely future fix.

### Storage ✅

- Local filesystem adapter (default)
- S3-compatible adapter (SeaweedFS-ready)
- Storage materialization seam for parsers (yields local path regardless of backend)

### Deployment ✅

- VPS deployed and verified (12-point check passed 2026-05-23, against alembic head `20260523_0009`)
- Docker Compose stack: Postgres, MinIO, Keycloak, Temporal
- 12-point end-to-end verification passed (2026-05-23 — earliest re-verified after Phase 1+2 hardening landed)
- 415 backend tests green (was 203 at Phase 1; +212 from Phase 2/3/4/audit work)

---

## What's Missing

### Not Yet Complete / Honest Closeout Required

| Component | Status | Notes |
|-----------|--------|-------|
| **Phase 4 load evidence** | ⚠️ Refresh needed | Re-run streaming load test after evidence-safe token buffering; old first-token numbers are stale |
| **Faithfulness metric wording** | ⚠️ Needs honesty pass | ADR-0016 `not_contradicted` is non-contradiction, not true source-support verification |
| **Phase 4 docs reconciliation** | ⚠️ Needed | `PROJECT_STATE.md`, `TASKS.md`, eval reports, and README should agree before declaring closeout |
| **Eval report artifacts** | ⚠️ Needs cleanup | Decide which generated eval reports/logs are canonical and commit or ignore them intentionally |
| **Frontend E2E verification** | ❌ Not done | Next.js pages exist; current local build was not re-verified because dependencies were not installed |
| **Book profile chunking** | ❌ Not started | Only `LooseDocumentChunker` implemented |
| **Graph RAG** | ❌ Not started | Deferred until hybrid retrieval core is proven |

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
| Tests | pytest + httpx | ✅ 417 passed, 1 skipped locally after streaming fix |

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
