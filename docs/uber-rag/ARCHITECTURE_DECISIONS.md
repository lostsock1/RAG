# Architecture Decision Ledger

Use this file for lightweight decisions. Use `docs/uber-rag/adr/` for full ADRs.

## Accepted decisions

### D-0001: One platform with two document profiles

Status: Accepted
Date: TBD

Decision: Build one shared platform with separate book and loose-document ingestion profiles, not two independent RAG systems.

Rationale: Shared API, ACL, retrieval, audit, evaluation, and cross-corpus questions are easier and safer in one platform.

### D-0002: API-first architecture

Status: Accepted
Date: TBD

Decision: Every Web UI action must be available through the public API.

Rationale: The UI must be replaceable, automation-friendly, and non-privileged.

### D-0003: Hybrid retrieval before graph RAG

Status: Accepted
Date: TBD

Decision: MVP uses BM25/phrase/exact + dense + sparse + reranking + verification. Graph RAG is optional after the core is measured.

Rationale: Reliable textbook and loose-document retrieval requires exact and semantic retrieval before graph complexity.

### D-0004: Source-bound answer generation

Status: Accepted
Date: TBD

Decision: Answers must be generated only from authorized retrieved evidence and verified at sentence level.

Rationale: Commercial reliability requires low unsupported-claim rate and clear not-found behavior.

## Full ADRs

Full ADRs live in `adr/`. Index:

- [ADR-0001 — Lexical Search Engine: OpenSearch over Tantivy](adr/0001-lexical-search-engine.md) — Accepted 2026-05-14
- [ADR-0002 — Ingestion Orchestration: Celery now, Temporal-ready design](adr/0002-ingestion-orchestration.md) — Accepted 2026-05-14
- [ADR-0003 — LLM Selection: Benchmark plan](adr/0003-llm-selection-benchmark.md) — Superseded 2026-05-14 (superseded by ADR-0004)
- [ADR-0004 — LLM Adapter Contract and Default API Provider](adr/0004-llm-adapter-and-provider.md) — Accepted 2026-05-14
- [ADR-0005 — n8n Excluded from Research and Production Substrate](adr/0005-n8n-excluded-from-research.md) — Accepted 2026-05-14
- [ADR-0008 — Fast Hot Path, Async Quality Path](adr/0008-fast-hot-path-async-quality.md) — Accepted 2026-05-15
- [ADR-0006 — OCR Stack: Docling Built-in as Default, PaddleOCR as Upgrade Path](adr/0006-ocr-stack.md) — Accepted 2026-05-14
- [ADR-0009 — Object Storage Direction for Phase 2 — SeaweedFS as Lead Candidate](adr/0009-object-storage-direction.md) — Accepted 2026-05-16
- [ADR-0010 — Ingestion Orchestration Direction for Phase 2 — Temporal as Lead Candidate](adr/0010-ingestion-orchestration-direction.md) — Accepted 2026-05-16
- [ADR-0011 — Structured Document-Understanding Architecture for Phase 2](adr/0011-structured-document-understanding-architecture.md) — Accepted 2026-05-16

## Proposed / Deferred decisions

- ADR-0007 — Frontend configuration (Next.js App Router routing, auth wrapper, layout patterns). **Deferred** — not blocking. Will be drafted before Phase 1 frontend code starts. Current rationale: frontend is a client of the API; API backbone comes first.
- ADR-0002 — Ingestion orchestration: Celery now, Temporal-ready design. **Accepted but constrained to earlier MVP assumptions** — supersession pressure now exists from ADR-0010 for the approved Phase 2 profile.
- Future ADR: llama.cpp vs vLLM serving runtime — deferred until local GPU hardware becomes available (see ADR-0004 revisit triggers).
- Future ADR: Local model production benchmark — deferred until local GPU hardware becomes available.
