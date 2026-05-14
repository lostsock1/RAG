# Uber-RAG Project State

Last updated: 2026-05-14
Owner: Uber-RAG agent
Status: Initial scaffold — project memory consolidated, agent configured

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
- Frontend: not started
- Backend API: not started
- Auth/ACL: not started
- Ingestion: not started
- Retrieval: not started
- Evaluation: not started
- Deployment: not started

## Active assumptions

- Target deployment may be air-gapped.
- Default stack: Next.js, FastAPI, Keycloak, PostgreSQL, MinIO, Qdrant, OpenSearch, BGE-M3, BGE reranker, llama.cpp or vLLM, Temporal or Celery.
- Graph RAG is optional after the hybrid retrieval core is proven.

## Recent changes

| Date | Change | Files | Notes |
|---|---|---|---|---|
| 2026-05-14 | Project memory consolidated into repo | `docs/uber-rag/*` → `RAG/docs/uber-rag/*` | Single source of truth. Removed stale `docs/uber-rag/`. |
| 2026-05-14 | Agent reference files created | `AGENTS.md`, `.opencode/agent/uber-rag.md` | Agents auto-discover project memory at repo root. |
| TBD | Initial agent scaffold | `.opencode/agents/*`, `docs/uber-rag/*` | Created planning memory. |

## Open risks

- Exact target corpus size not yet measured.
- Hardware plan not finalized.
- Model serving runtime not benchmarked.
- OCR quality requirements not validated.
- ACL model not mapped to real organization roles/groups.

## Next recommended actions

1. Create repository structure.
2. Define API contracts and domain models.
3. Build minimal document upload, metadata, ACL, and ingestion status API.
4. Build parser adapter interface and Docling integration.
5. Build Qdrant/OpenSearch indexing adapters.
6. Build `/search` and `/chat` with ACL filters.
7. Build evaluation seed dataset.
