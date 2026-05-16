# ADR-0010: Ingestion Orchestration Direction for Phase 2 — Temporal as Lead Candidate
Status: Accepted
Date: 2026-05-16

## Context

ADR-0002 accepted Celery + Redis for MVP with Temporal-ready discipline. Since then, the approved Phase 2 design direction became more demanding than the original leanest-path assumption:

- high expected ingestion volume
- rich structured parsing artifacts as first-class outputs
- local CPU, local GPU, and remote API deployment profiles
- preference for resumability/correctness over lowest possible ops complexity

These constraints increase the cost of application-owned recovery logic. Long-running parse flows, backend-specific failures, and artifact-stage checkpointing all favor a more durable workflow engine than the original minimum-complexity starting point.

## Decision

Make **Temporal** the lead orchestration direction for Phase 2 ingestion runs and stage coordination.

This decision is **reversible** if the operational burden proves too high relative to the actual ingestion scale or if the team chooses to keep Celery + Redis longer while preserving Temporal-ready stage discipline.

## Consequences

### Positive

- Better fit for durable, resumable ingestion at higher volume.
- Reduces the amount of recovery/correctness logic owned only in application code.
- Matches the need to checkpoint around parse artifacts and other long-running stages.
- Cleaner long-term path for heterogeneous parser/document-understanding backends.

### Negative

- Higher operational complexity than Celery + Redis.
- Higher team learning cost because Temporal introduces a different workflow model.
- Changes the current default direction set by ADR-0002 if later accepted.

## Alternatives considered

- **Celery + Redis** — not selected as the lead candidate for the approved Phase 2 profile. Still viable as the lighter fallback, especially if the team deliberately chooses lower ops complexity and accepts more application-owned resumption logic.
- **Prefect** — not selected. Plausible middle ground, but not currently the strongest fit for the user’s preference ordering.
- **Dagster / Airflow / lighter queues** — not selected. Either too scheduling-oriented or not strong enough on the specific resumable-ingestion problem.

## References

- Temporal docs — https://docs.temporal.io/ (accessed 2026-05-16)
- Celery docs — https://docs.celeryq.dev/en/stable/ (accessed 2026-05-16)
- Internal ADR — `docs/uber-rag/adr/0002-ingestion-orchestration.md`
- Internal research note — `docs/uber-rag/research/2026-05-16-phase-2-entry.md`
- Internal design spec — `docs/superpowers/specs/2026-05-16-phase-2-entry-design.md`

## Revisit triggers

- If actual Phase 2 ingestion volume and failure patterns are low enough that Temporal’s extra complexity is not justified.
- If the team cannot support Temporal operationally in the target deployment environments.
- If a lighter orchestration option proves sufficient while preserving checkpoint/resume guarantees with materially less complexity.
