# Uber-RAG — Project Reference for AI Agents

## What This Is

Uber-RAG is a commercial-grade, API-first, ACL-aware RAG platform that reliably indexes and answers from both textbooks and loose documents. This file is the entry point for any AI agent entering this repository.

## GitHub Repository

- **Repo:** `https://github.com/lostsock1/RAG.git` (owner: `lostsock1`, repo: `RAG`)
- **Branch:** `main`
- **GitHub MCP:** All GitHub operations are available through the GitHub MCP server (`@modelcontextprotocol/server-github`). Prefer `github_push_files` for multi-file commits over raw `git push`. Review via `github_create_pull_request_review`.

## Project Memory Location

All architecture, decisions, tasks, and state live in:

```
docs/uber-rag/
├── PROJECT_STATE.md          # Current implementation state, open risks, next actions
├── TASKS.md                  # Full task backlog across all phases
├── ARCHITECTURE.md           # System architecture and component design
├── ARCHITECTURE_DECISIONS.md # ADR index and decision log
├── API_CONTRACT.md           # API design principles and endpoint inventory
├── SECURITY_ACL.md           # ACL model, enforcement layers, audit requirements
├── RETRIEVAL_QUALITY.md      # Retrieval pipeline design and quality standards
├── EVALUATION_PLAN.md        # Evaluation strategy, datasets, metrics
├── INGESTION_PIPELINES.md    # Document profiles and parsing pipelines
├── STACK_REFERENCES.md       # Technology choices with sources and versions
├── ROADMAP.md                # High-level timeline and milestones
├── RESEARCH_PROTOCOL.md      # Research methodology and source tracking
├── DEEPEYE_INTEGRATION.md    # DeepEye deep-research dispatch protocol
├── DEVELOPMENT_RULES.md      # Coding standards and quality gates
├── adr/                      # Architecture Decision Records
├── research/                 # Research notes and findings
└── templates/                # API spec, quality report, research note templates
```

## Agent Roles

This project uses a five-agent split. Pick or invoke the agent that matches the work:

| Agent | When to use | Edit scope |
|---|---|---|
| `uber-rag-planner` | ADRs, stack decisions, architecture invariants, evaluation design, API contracts, memory updates. Cannot edit code; cannot dispatch implementer. | `docs/uber-rag/**` only. |
| `uber-rag` (primary builder) | Active implementation sessions; orchestrates researcher, implementer, reviewer. | Full, with `ask` on risky paths. |
| `uber-rag-researcher` | Targeted source-backed research lookups. | `docs/uber-rag/research/**`, `STACK_REFERENCES.md`, `RESEARCH_PROTOCOL.md`. |
| `uber-rag-implementer` | Concrete code, tests, docs updates within an implementation session. | `apps/services/packages/tests` allowed; `infra/migrations/docs/lockfiles` ask; secrets denied. |
| `uber-rag-reviewer` | Read-only audit before merge or shipping. | None (read-only). |

For deep multi-source research (decision-critical, ADR-bound), planner and primary builder both dispatch `search/deepeye`. Researcher and reviewer flag DeepEye candidates but do not dispatch directly.

**Default for the current phase (no code yet): `uber-rag-planner`.** Switch to `uber-rag` (primary builder) when actual implementation work begins.

## Startup Protocol (Required)

At the start of every task:

1. **Detect read-only mode** — if the prompt starts with `ro`, treat the entire session as read-only.
2. **Read the project memory files** — at minimum `PROJECT_STATE.md` and `TASKS.md`.
3. **Classify the task** as one or more of: research, planning, architecture, backend implementation, frontend implementation, ingestion/parser, retrieval, security/ACL, evaluation/quality, review/audit.
4. **Produce a short plan** before multi-step work.
5. **Execute incrementally** and verify each significant step.
6. **Update project memory files** after meaningful decisions or code changes.

## Architecture Invariants (Never Violate)

1. **API-first** — the Web UI is only a client of the public API. Every UI action must be possible through the API.
2. **Security and ACL** — enforced in the backend at multiple layers: auth, query construction, pre-rerank, pre-fetch, LLM context, citation, and audit log.
3. **Hybrid retrieval** — multi-stage: BM25 + dense (BGE-M3) + sparse (BGE-M3) → fusion (RRF/DBSF) → parent-child expansion → cross-encoder reranking → context builder → answer generation → sentence-level evidence verification.
4. **Document profiles** — Book profile (deep hierarchy, chapters, page anchors) and Loose document profile (metadata-driven, type routing).
5. **Evidence discipline** — answers must be source-bound. If evidence is missing, respond with a clear not-found. No improvisation.

## Default Stack

| Component | Default |
|-----------|---------|
| Frontend | Next.js / React / TypeScript |
| Backend | FastAPI (OpenAPI-first) |
| Auth | Keycloak (OIDC) |
| Database | PostgreSQL |
| Object store | MinIO |
| Vector store | Qdrant |
| Search engine | OpenSearch |
| Embeddings | BGE-M3 |
| Reranker | BGE-reranker-v2-m3 |
| LLM | Llama 3.3 70B (llama.cpp or vLLM) |
| Ingestion workers | Temporal or Celery |
| Document parser | Docling |

## Development Workflow

```
Read → Research → Plan → Implement → Test → Verify → Document → Update state
```

- Research before decisions (check Awesome-AI-Memory first, then Exa, DeepEye for critical decisions)
- Test after implementation
- Update PROJECT_STATE.md and TASKS.md after meaningful changes
- Create/update ADRs for architecture decisions
- Record sources in STACK_REFERENCES.md

## Tone

Be direct, technical, and precise. Prefer concrete files, APIs, interfaces, schemas, tests, and acceptance criteria over generic advice. Explain the "why" behind decisions — the user is not a RAG specialist.
