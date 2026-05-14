# Uber-RAG Roadmap

The project is structured in phases. Each phase has:

- **Entry gate** — mandatory re-evaluation of the stack against current evidence before the phase begins.
- **Goal** — the single outcome the phase delivers.
- **Deliverables** — what gets built.
- **Exit criteria** — what must be true to advance.

A phase cannot begin until the entry gate completes AND the previous phase's exit criteria are met.

## Phase entry gate (applies to every phase)

Before starting any phase, dispatch `uber-rag-planner` (or `uber-rag-researcher` for targeted lookups, `search/deepeye` for decision-critical reviews) to:

1. **Scan [IAAR-Shanghai/Awesome-AI-Memory](https://github.com/IAAR-Shanghai/Awesome-AI-Memory)** for new papers, projects, or techniques relevant to this phase's deliverables.
2. **Check official docs** of every pinned dependency in scope (FastAPI, Qdrant, OpenSearch, Docling, BGE-M3, BGE-Reranker, vLLM, llama.cpp, Celery, Keycloak, Postgres, MinIO) for breaking changes, new versions, deprecated APIs.
3. **Check official repos** of those dependencies — release notes, security advisories, high-signal issues.
4. **Re-validate model choices** against current model cards on Hugging Face (or equivalent primary source). Note any successor models as candidates.
5. **Demote blog posts and tutorials.** They may inform discovery but never serve as primary evidence in an ADR. Only Tier 1 and Tier 2 sources (per `RESEARCH_PROTOCOL.md`) can be cited.
6. **Update `STACK_REFERENCES.md`** with any version pins, new candidates, or deprecation notes discovered.
7. **Produce a one-page phase-entry research note** at `docs/uber-rag/research/YYYY-MM-DD-phase-N-entry.md` summarizing what was checked, what changed, what must be reopened, what was confirmed unchanged.

If the entry gate surfaces a material change (new SOTA reranker, breaking change in vLLM, deprecated Docling API, security advisory), pause the phase and open or reopen the relevant ADR before proceeding.

## Source authority (referenced from `RESEARCH_PROTOCOL.md`)

- **Tier 1** (citable as primary evidence in ADRs): official documentation, official repositories, primary papers, vendor model cards, standards/specs, official release notes.
- **Tier 2** (citable with caveat): maintainer-authored issues/posts, recorded talks by maintainers, reproducible benchmarks with code.
- **Tier 3** (discovery only, never sole evidence): third-party blogs, tutorials, aggregators, AI-generated summaries, forum posts.

---

## Phase 0: Foundations and Decisions (current)

Entry gate: not applicable — this is the bootstrap phase.

Goal: close every MVP-blocking decision so Phase 1 builds against a settled stack.

Deliverables:

- ADR-0001 Lexical search (Accepted: OpenSearch)
- ADR-0002 Ingestion orchestration (Accepted: Celery, Temporal-ready)
- ADR-0003 LLM benchmark plan (Proposed)
- ADR-0004 LLM model winner (closes ADR-0003 after benchmark)
- ADR-0005 n8n excluded from substrate (Accepted)
- ADR-0006 OCR stack (Tesseract vs PaddleOCR vs hybrid vs alternatives)
- ADR-0007 Frontend configuration (Next.js App Router shape, auth wrapper, layout patterns)
- API contract skeleton — OpenAPI YAML for MVP endpoints
- Domain model skeleton — Postgres schema for documents, chunks, ACL grants, audit events, ingestion runs/stages, eval results
- Evaluation harness skeleton — repository structure, ground-truth Q/A format, scoring stubs
- 160-question held-out eval set drafted (per ADR-0003)

Exit criteria:

- All seven MVP ADRs Accepted (0001–0007).
- ADR-0003 benchmark executed and ADR-0004 Accepted.
- Eval harness can run end-to-end on synthetic data, even with stub retrievers.
- API contract reviewed by `uber-rag-reviewer`.

---

## Phase 1: Secure document management

Entry gate: re-evaluate Keycloak (alternatives: Authentik, Zitadel), Postgres RLS patterns, MinIO; confirm OIDC client libraries are current.

Goal: a document can be uploaded by an authenticated, authorized user and retrieved through ACL-enforced API endpoints. No parsing yet.

Deliverables:

- FastAPI app skeleton with Keycloak OIDC
- Postgres + Alembic migrations for documents, ACL grants, audit events
- MinIO upload endpoint with source hashing
- ACL editor API (collections, groups, scopes)
- Audit log table and write path
- Document list and metadata API
- Web UI: upload form, document list (read-only)

Exit criteria:

- Authenticated user can upload a document; unauthenticated request denied.
- Two users in different ACL groups cannot see each other's documents through `/documents`.
- ACL leakage test in CI fails without enforcement code, passes with it.
- Audit log records every upload, ACL change, and list operation.

---

## Phase 2: Ingestion MVP

Entry gate: re-evaluate Docling release notes, OCR engines (Tesseract/PaddleOCR/alternatives), Celery + Redis combo, Temporal community momentum.

Goal: an uploaded document is parsed, chunked, embedded, indexed, and visible in a quality report. Idempotent and resumable.

Deliverables:

- Docling parser adapter behind a `Parser` interface
- OCR adapter interface (initial implementation per ADR-0006)
- Celery worker with the 6 idempotency rules from ADR-0002
- `ingestion_runs` and `ingestion_stages` tables
- Chunking with parent-child hierarchy
- BGE-M3 dense + sparse embeddings behind `Embedder` interface
- Qdrant + OpenSearch write paths (ACL metadata included)
- Quality report (parser confidence, OCR signal, table/formula counts)
- Ingestion dashboard endpoint
- One document profile fully wired (start with loose-doc; book profile in Phase 5)

Exit criteria:

- Uploading the same file twice produces no duplicate chunks (idempotency proven).
- Killing a worker mid-run and restarting completes the run without manual cleanup (resumability proven).
- Quality report visible per document.
- All ingested chunks carry ACL metadata matching the source document.

---

## Phase 3: Search MVP

Entry gate: re-evaluate Qdrant hybrid/fusion features, OpenSearch hybrid plugins, BGE-M3 (check for newer BAAI models), RRF vs DBSF fusion research.

Goal: a query returns ranked, ACL-filtered, citation-bound chunks via the public API.

Deliverables:

- Query router (exact / phrase / BM25 vs dense vs sparse)
- ACL filter construction (Qdrant payload filters + OpenSearch filters)
- Hybrid fusion (RRF or DBSF — close in an ADR if not already)
- Parent-child expansion
- Citation pointer tracking (chunk ID stable from index → response)
- `/search` endpoint with OpenAPI spec
- Source viewer endpoint (returns chunk with surrounding context)
- No reranker yet, no verifier yet (Phase 4)

Exit criteria:

- ACL leakage test: forbidden documents never appear in `/search` results regardless of query.
- Citation pointers in `/search` responses resolve to indexed chunks.
- Exact-string queries (quoted strings, IDs) route through lexical and succeed on a needle test.
- P50 latency under 500 ms for typical queries on the dev corpus.

---

## Phase 4: Reranking, generation, verification

Entry gate: re-evaluate BGE-Reranker-v2-m3 (check for newer rerankers), vLLM/llama.cpp release notes, the model winner from ADR-0004, citation/verification techniques on Awesome-AI-Memory.

Goal: end-to-end answer with citations. Stage 1 evidence discipline (citation required per paragraph) and negative-answer behavior.

Deliverables:

- Cross-encoder reranker behind `Reranker` interface
- Exact-match query routing that bypasses reranker
- LLM adapter against the OpenAI-compatible internal API (model = ADR-0004 winner)
- Prompt template with citation rendering
- `/chat` endpoint (non-streaming first, then streaming)
- Sentence-level evidence verifier — Stage 1 (citation required per paragraph)
- Negative-answer handling: "insufficient evidence in the indexed sources" + optional scope-widening suggestion
- Citation resolver endpoint

Exit criteria:

- Faithfulness ≥ threshold defined in `EVALUATION_PLAN.md` on the held-out eval set.
- Negative-answer compliance ≥ threshold on the 20 negative questions.
- ACL leakage test passes end-to-end (forbidden docs never reach LLM context).
- Streaming `/chat` works under realistic load.

---

## Phase 5: Second profile, UI, evaluation polish

Entry gate: re-evaluate Open WebUI release notes, Next.js App Router stable features, citation-UX patterns, eval frameworks (DeepEval, RAGAS, custom).

Goal: real users can use the system. Both document profiles supported. Evaluation runs on every commit.

Deliverables:

- Book profile ingestion (hierarchy, chapters, page anchors, glossary, index)
- Open WebUI deployed for chat (off-the-shelf)
- Custom Next.js UI for: ingestion, ACL admin, citation viewer, audit log, eval dashboard
- Eval harness running on CI for every PR touching retrieval, generation, or ACL
- Synthetic needle-test generator
- Cross-corpus question generator

Exit criteria:

- A non-engineer can upload a textbook + a loose document, ask questions, see citations, see audit.
- CI fails any PR that regresses faithfulness, citation accuracy, or negative-answer compliance by more than a defined threshold.

---

## Phase 6: Operational hardening

Entry gate: re-evaluate Qdrant/OpenSearch backup/restore docs, vLLM scaling docs, Keycloak production patterns, air-gapped deployment best practices, observability stack (OpenTelemetry maturity).

Goal: deployable, observable, restorable, air-gapped-ready.

Deliverables:

- Snapshot/restore for Postgres, Qdrant, OpenSearch, MinIO
- OpenTelemetry tracing across API, workers, retrieval, LLM
- Structured logging with audit-event integration
- Metrics dashboards
- Performance benchmarks under realistic load (concurrency, latency, throughput)
- Air-gapped deployment bundle (signed artifacts, all model weights, container digests)
- Security review (dependency CVE scan, secret audit, threat model)
- Runbooks (incident response, backup/restore, rollback)

Exit criteria:

- Restoring from snapshot is exercised in a dry-run and recorded in a runbook.
- Performance benchmark report committed; SLA targets met or escalated.
- Air-gapped bundle installs and runs in a network-isolated VM.

---

## Phase 7: Advanced retrieval (post-MVP, opt-in only)

Entry gate: re-evaluate Graph RAG, HippoRAG, LightRAG, multivector retrieval, domain-specific fine-tunes, sentence-level NLI verifiers — every one of these is an ADR before any code lands.

Goal: incremental quality gains where measured eval data justifies them.

Each candidate is gated by:

1. A measured weakness in the Phase 4/5 eval (e.g., multi-hop recall < 60 %).
2. An ADR proposing the technique with expected impact.
3. A bake-off in the eval harness against the current baseline.
4. ADR closure (Accepted with measurable improvement, or Rejected with reasoning preserved).

Candidates:

- Concept graph for textbook content
- HippoRAG-style multi-hop retrieval
- LightRAG comparison benchmark
- Multivector rerank stage (using BGE-M3 multivector output)
- Domain-specific embedding/reranker fine-tuning
- Stage 3 sentence-level NLI verifier
- True table/formula reasoning (not just anchored indexing)

Exit criteria: not applicable — this phase is open-ended and feature-additive.
