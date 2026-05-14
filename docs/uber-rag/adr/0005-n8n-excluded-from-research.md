# ADR-0005: n8n Excluded from the Research and Production Substrate

Status: Accepted
Date: 2026-05-14

## Context

n8n was considered as a rapid-iteration scaffold for the RAG ingestion, retrieval, generation, and evaluation pipelines during the research phase. After a method-fusion analysis (Spine → Roles → Why-clean → Where-not → Trap → Next artifact), the user explicitly rejected this approach.

The architectural reasoning: n8n cannot host Uber-RAG's defining invariants — API-first contract, ACL at every layer, citation discipline, audit log, sub-second query latency, air-gapped readiness. Building research workflows in n8n would either (a) produce a paid prototype that is discarded when production starts, or (b) couple the project to two systems with constant schema drift and impedance mismatch.

This ADR closes the question so no future planning session reopens it without an explicit superseding ADR.

## Decision

n8n is **not** used as the substrate for Uber-RAG, in any phase (research, MVP, production, post-MVP).

The research substrate is the project's own Python code (FastAPI modules, Celery stages, Postgres tables) plus the evaluation harness. Comparison and bake-off experiments run inside the eval harness, not inside n8n.

## Consequences

### Positive

- One system to learn, debug, and operate end-to-end.
- Code written during research is the code that goes to production — no rewrite tax.
- ACL, citation, and audit invariants are exercised from day one, not bolted on later.
- No impedance mismatch between a workflow-flavored prototype and a contract-flavored product.

### Negative

- Slower initial iteration than a visual-flow prototype. The first ingestion experiment takes hours, not minutes.
- Requires writing code for things n8n nodes would provide off-the-shelf (Qdrant insert, embedding call, etc.).
- Loses n8n's free comparison-branching; must build equivalent in the eval harness.

## What this does NOT exclude

- n8n remains valid for **non-Uber-RAG** workflows (operational automation, integrations unrelated to the platform, side projects). This decision is scoped to Uber-RAG only.
- The `n8n-mcp` MCP tooling configured in OpenCode remains available for those other use cases.
- If a future ADR identifies a specific Uber-RAG-adjacent workflow where n8n clearly beats code AND does not touch the query, ingestion, or ACL paths (e.g., admin-side back-office automation), it may be reopened with explicit narrow scope.

## Alternatives considered

- **n8n as research scaffolding** — rejected. Captured in this session's method-fusion analysis on 2026-05-14. Core reason: Uber-RAG's invariants are exactly the parts n8n does not provide.
- **n8n as production ingestion substrate** — rejected. Latency floor and contract mismatch.
- **Hybrid n8n + FastAPI** — rejected. Two systems for one product is worse than either single system.

## Revisit triggers

Reopen this ADR only if:

- A specific Uber-RAG-adjacent workflow is identified where n8n's strengths (visual orchestration of unrelated SaaS APIs) clearly beat code AND the workflow does not touch the query, ingestion, or ACL paths.
- A material change in n8n's architecture (real per-document ACL primitives, OpenAPI-first contracted responses, sub-100 ms hot-path latency, true multi-tenant isolation) inverts the tradeoffs above.

## References

- Internal: method-fusion analysis (Spine, Roles, Why-clean, Where-not, Trap, Next artifact) — this session, 2026-05-14
- Internal: `docs/uber-rag/STACK_REFERENCES.md` — intentionally no n8n entry
- Internal: `docs/uber-rag/RESEARCH_PROTOCOL.md` § Substrate exclusions
- n8n documentation: https://docs.n8n.io/ — referenced for evaluation only; not adopted
