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
- [ADR-0003 — LLM Selection: Benchmark plan](adr/0003-llm-selection-benchmark.md) — Proposed 2026-05-14 (auto-closes via ADR-0004)
- [ADR-0005 — n8n Excluded from Research and Production Substrate](adr/0005-n8n-excluded-from-research.md) — Accepted 2026-05-14

## Proposed decisions

- ADR-0004 — LLM model winner — closes ADR-0003 after benchmark.
- ADR-0006 — OCR stack (Tesseract vs PaddleOCR vs hybrid vs alternatives).
- ADR-0007 — Frontend configuration (Next.js App Router routing, auth wrapper, layout patterns).
- Future ADR: llama.cpp vs vLLM serving runtime (ADR-0003 uses vLLM as the working default; confirm via benchmark).
