# Uber-RAG

**API-first, ACL-aware RAG platform for textbooks and loose documents.**
Indexes structured and unstructured content, enforces per-tenant access
control at the retrieval layer, and answers questions with sentence-level
evidence verification and citations.

![Python](https://img.shields.io/badge/python-3.12+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-316192)
![Qdrant](https://img.shields.io/badge/Qdrant-vector-DC244C)
![OpenSearch](https://img.shields.io/badge/OpenSearch-lexical-005EB8)
![Keycloak](https://img.shields.io/badge/Keycloak-OIDC-4D4D4D)
![License](https://img.shields.io/badge/license-MIT-brightgreen)

---

## Overview

Uber-RAG is a commercial-grade document understanding and question-answering
platform built around a single assertion: **retrieval without access control is
non-viable for multi-tenant deployments.** Every document, chunk, vector, and
search result is filtered through tenant-scoped ACL policies before it reaches
the answer layer.

The platform handles two document profiles — textbooks (hierarchical,
structure-aware chunking) and loose documents (paragraph-split with
parent-child relationships) — through a shared retrieval and answer core.

### What it does

- **Ingestion** — upload documents via REST API, dispatch through a 7-stage
  async pipeline (parse → chunk → embed → index_dense → index_sparse →
  quality_report), with configurable backends for every stage
- **Parsing** — supports local CPU parsing, local GPU parsing, and remote
  HTTP-backed parser adapters; deployment profile selected at config time
- **Chunking** — structure-aware splitting for textbooks (chapter/section
  hierarchy) and paragraph-based splitting for loose documents with two-level
  parent-child relationships; deterministic chunk UUIDs via `uuid5`
- **Embedding** — BGE-M3 for dense (1024-dim L2-normalized) and sparse
  (lexical token-weight) vectors, with a stub embedder for fast testing
- **Indexing** — Qdrant for vector search (cosine similarity on
  dense + sparse named vectors), OpenSearch for BM25 / phrase / exact lexical
  search, both with real and mock test backends
- **Retrieval** — ACL-safe `/search` with pre- and post-filtering, query
  hashing for audit, retriever protocol seam; hybrid retrieval, reranking,
  and context building are next
- **Auth & ACL** — OIDC via Keycloak with JWKS-backed token verification,
  loopback dev fallback for local development, bootstrap ACL policies with
  stable keys, deterministic `sensitivity_rank`, and tenant-scoped visibility
- **Answering** — evidence verification at sentence level, citation linking
  back to source chunks
- **Temporal orchestration** — optional workflow dispatch via Temporal with
  fire-and-forget semantics; in-process dispatch remains the default for
  simpler deployments

---

## Architecture

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

### Ingestion Pipeline

```
upload ──► parse ──► persist ──► chunk ──► embed ──► index_qdrant ──► index_opensearch ──► quality_report
            │                                                         │
            ├── local-cpu (Docling)                                   ├── BGE-M3 (1024d dense)
            ├── local-gpu (Docling GPU)                               ├── BGE-M3 (lexical sparse)
            └── remote-api (HTTP adapter)                             └── deterministic UUID5 keys
```

### ACL Model

Every document carries an ACL grant with:
- **Owner** — user who uploaded
- **Explicit users/groups** — whitelist grants
- **Visibility** — `private | group | tenant | public`
- **Sensitivity rank** — deterministic, policy-derived
- **Policy id/version** — for audit trail and policy drift detection

ACL filters are applied at ingestion (who can see the run) and at retrieval
(who can find the chunks). Index payloads carry full ACL metadata for
server-side filtering.

---

## Tech Stack

| Layer | Technology | Role |
|-------|-----------|------|
| API | FastAPI + Pydantic v2 | REST endpoints, validation, OpenAPI 3.1 |
| Auth | Keycloak + PyJWT + OIDC | Bearer token verification, JWKS, scope mapping |
| Database | PostgreSQL 16 + SQLAlchemy 2.0 + Alembic | Metadata, ACL, jobs, audit log |
| File storage | Local FS / MinIO (SeaweedFS-ready adapter) | Originals, parsed artifacts |
| Vector DB | Qdrant | Dense (cosine) + sparse named vectors |
| Search engine | OpenSearch | BM25, phrase, exact, fielded |
| Parsing | Docling (local) / HTTP adapter (remote) | Deployment-profile-aware |
| Embedding | BGE-M3 | 1024-dim dense + lexical sparse |
| Orchestration | Temporal (optional) | Workflow dispatch, retry, observability |
| Frontend | Next.js 15 + Tailwind v4 | Upload, document list, login |
| Infra | Docker Compose | Postgres, MinIO, Keycloak, Temporal |
| Tests | pytest + httpx | 203/203 passing (unit + integration) |

---

## Quick Start

See `AGENTS.md` for agent orientation and `docs/uber-rag/PROJECT_STATE.md`
for full implementation status.

### Local development

```bash
# 1. Clone and set up
git clone https://github.com/lostsock1/RAG.git
cd RAG
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,temporal]"

# 2. Configure
cp .env.example .env
# Set AUTH_MODE=dev for local dev (loopback-only bearer tokens)
# Set LOCAL_STORAGE_DIR=/absolute/path/for/document-storage

# 3. Start infrastructure
docker compose -f infra/docker/docker-compose.yml up -d

# 4. Verify
pytest apps/api/app/tests/integration/test_health.py -v
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

### Temporal (optional, Phase 2)

```bash
# Start Temporal dev server
temporal server start-dev --headless --ip 127.0.0.1 --port 7233 --ui-port 8233

# Verify
temporal operator cluster health --address 127.0.0.1:7233

# Run live proof
pytest apps/api/app/tests/integration/test_temporal_live_ingestion.py -q
```

### VPS deployment

Deployed and verified on a Debian VPS (`vm-1485.lnvps.cloud`).
Full 12-point end-to-end verification passed (2026-05-16).

```bash
ssh rag                                         # vm-1485.lnvps.cloud
cd ~/RAG
sudo docker compose -f infra/docker/docker-compose.yml up -d
source .venv/bin/activate
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > uvicorn.log 2>&1 &
curl -s http://localhost:8000/api/v1/system/health
# {"status":"ok"}
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
│   │       ├── services/       # document, ingestion, retrieval, chunking, embedding
│   │       ├── db/             # SQLAlchemy models, repositories, migrations
│   │       ├── core/           # config, security, ACL, OIDC verifier
│   │       └── tests/          # unit + integration (203 passing)
│   └── web/                    # Next.js frontend
├── infra/
│   ├── docker/                 # Compose stack, Keycloak realm import
│   │   └── keycloak/           # uber-rag-realm.json (test users, clients)
│   └── migrations/             # Alembic
├── packages/
│   └── clients/                # TypeScript API client
├── docs/
│   ├── uber-rag/               # Architecture, ADRs, API contract, project state
│   └── superpowers/            # Planning and design documents
├── tests/                      # Cross-cutting integration tests
├── pyproject.toml              # Backend dependencies + entry points
└── AGENTS.md                   # AI agent orientation
```

---

## Test Users (Keycloak dev realm)

| User | Password | Group | Roles | Permissions |
|------|----------|-------|-------|-------------|
| `alice` | `alicepass` | `alpha` | `editor` | `documents:read documents:write` |
| `bob` | `bobpass` | `beta` | `editor` | `documents:read documents:write` |
| `admin` | `adminpass` | — | `admin` | `documents:read documents:write` |

Bootstrap realm config at `infra/docker/keycloak/uber-rag-realm.json`.

---

## Implementation Status

| Phase | Status |
|-------|--------|
| Phase 1 — Core API, auth, ingestion foundation | ✅ Complete |
| Phase 2 — Document understanding, chunking, embedding, indexing | ✅ Complete |
| Temporal orchestration hardening | ✅ Complete (live proof passed) |
| ACL bootstrap policy | ✅ Complete |
| Retrieval kickoff (`/search`) | ✅ Complete |
| Full hybrid retrieval, reranking, context building | 🔜 Next |
| Evaluation harness | 🔜 Next |

See `docs/uber-rag/PROJECT_STATE.md` for detailed per-component status.

---

## License

MIT — see [LICENSE](LICENSE).
