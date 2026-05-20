# Uber-RAG

**API-first, ACL-aware RAG platform for textbooks and loose documents — early
stage, core ingestion pipeline working, retrieval and answering not yet built.**

![Python](https://img.shields.io/badge/python-3.12+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-316192)
![Qdrant](https://img.shields.io/badge/Qdrant-vector-DC244C)
![OpenSearch](https://img.shields.io/badge/OpenSearch-lexical-005EB8)
![Keycloak](https://img.shields.io/badge/Keycloak-OIDC-4D4D4D)
![Status](https://img.shields.io/badge/status-ingestion%20working%2C%20retrieval%20stub-yellow)
![License](https://img.shields.io/badge/license-MIT-brightgreen)

---

> **⚠️ This project is not ready for use.** The ingestion pipeline (upload →
> parse → chunk → embed → index) is fully implemented and tested. Retrieval
> is a thin stub. Answer generation, reranking, evaluation, and the full
> query pipeline have not been built. See [What's Missing](#whats-missing).

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
| `POST /api/v1/search` | ⚠️ Thin stub — ACL-safe route with pre/post filtering, but no hybrid retrieval or reranking |

### Storage ✅

- Local filesystem adapter (default)
- S3-compatible adapter (SeaweedFS-ready)
- Storage materialization seam for parsers (yields local path regardless of backend)

### Deployment ✅

- VPS deployed and verified (12-point check passed 2026-05-16)
- Docker Compose stack: Postgres, MinIO, Keycloak, Temporal
- 12-point end-to-end verification passed (2026-05-16)
- 203/203 backend tests green

---

## What's Missing

### Not Yet Implemented

| Component | Status | Notes |
|-----------|--------|-------|
| **Answer generation / LLM** | ❌ Not started | ADR-0004 designed (ppq.ai + Llama 3.3 70B), not wired |
| **Full retrieval pipeline** | ❌ Not started | Hybrid retrieval, fusion, reranking, context building all pending |
| **Reranking** | ❌ Not started | BGE reranker selected but not integrated |
| **Evaluation harness** | ❌ Not started | Design doc complete, 170-question heldout set drafted, no code |
| **Frontend E2E verification** | ❌ Not done | Next.js toolchain builds, pages exist, never tested against running API |
| **Book profile chunking** | ❌ Not started | Only `LooseDocumentChunker` implemented |
| **Sentence-level verification** | ❌ Not started | Architecture only |
| **Graph RAG** | ❌ Not started | Deferred until hybrid retrieval core is proven |

### Partially Implemented

| Component | Status | Notes |
|-----------|--------|-------|
| **Search** | ⚠️ Kickoff only | Thin `/search` route with ACL filtering; returns `503` when no retriever configured |
| **Frontend** | ⚠️ Scaffold only | Login, upload, documents pages exist; `next build` succeeds; not tested E2E |
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

Grayed-out sections above (`/retrieve`, `/chat`, `/answers/verify`, `/eval`)
are planned but not implemented. Only the ingestion path (upload → vector
store) and thin search route are functional.

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
| Frontend | Next.js 15 + Tailwind v4 | ⚠️ Scaffold only |
| LLM Answering | ppq.ai + Llama 3.3 70B (planned) | ❌ Not wired |
| Reranking | BGE reranker (planned) | ❌ Not wired |
| Tests | pytest + httpx | ✅ 203/203 green |

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
passed (2026-05-16).

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
│   │       └── tests/          # 203 passing (unit + integration)
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
