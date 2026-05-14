# ADR-0002: Ingestion Orchestration — Celery Now, Temporal-Ready Design

Status: Accepted
Date: 2026-05-14

## Context

The ingestion pipeline has multiple stages: upload → parse (Docling) → optional OCR → quality report → chunking → embedding (BGE-M3) → indexing into Qdrant + OpenSearch → metadata commit in Postgres. It must support retries, partial-failure resumption, idempotent reindex, parser-version-aware reruns, and an audit trail.

`STACK_REFERENCES.md` lists Temporal and Celery as candidates.

- **Temporal** — durable workflow engine: native retries, deterministic replay, versioning, history, signals. Requires running a Temporal cluster (server + Postgres-or-Cassandra + UI).
- **Celery** — task queue with Redis or RabbitMQ broker. Simpler. Retries supported. No durable workflow semantics — resumption is implemented in application code.

The project is pre-implementation, one developer, no production load yet. Stated priorities: lean + modular + scalable. Temporal at MVP means two extra services, a new SDK, and a new programming model. Celery means one broker (Redis is already a dependency for caching) and a familiar Python decorator pattern.

## Decision

Use **Celery** with **Redis** as the broker for MVP. Design the ingestion pipeline as a sequence of **idempotent, checkpointed stages** so that a future migration to Temporal is a wrapping exercise, not a rewrite.

## Consequences

### Positive

- One less service to run in dev, CI, and prod.
- Familiar tooling — Flower for monitoring, well-documented retry/backoff config.
- Redis is already needed for FastAPI rate-limiting and short-lived caches; no incremental dependency.
- Faster MVP delivery — fewer moving parts to learn and configure.

### Negative

- No durable workflow history out of the box. We record stage state in Postgres ourselves (`ingestion_runs`, `ingestion_stages` tables).
- Long-running workflows (multi-hour OCR jobs) require careful timeout and visibility-timeout tuning. Temporal would handle this natively.
- Resumption logic is application code, not framework. Bugs in resumption are our bugs.
- If/when we migrate to Temporal, every stage function must already be idempotent and externally checkpointed. This is a discipline cost, not a code cost.

## Implementation rules that earn the right to migrate later

Every ingestion stage MUST:

1. **Be idempotent** — running the stage twice with the same input produces the same output and no duplicate side effects. Use natural keys (source hash + parser version + chunk index) for deduplication.
2. **Take a `run_id` and a `stage_id` as inputs** — never rely on Celery task IDs for identity.
3. **Write checkpoint state to Postgres before returning** — stage status, timestamps, error info, output artifact references.
4. **Be resumable** — if a run is restarted, each stage reads its own checkpoint and either re-runs (idempotently) or skips (if completed).
5. **Use Celery's retry/backoff for transient failures** and surface permanent failures to the run record, not just the broker.
6. **Be testable in isolation** — each stage function callable directly with synthetic inputs in a unit test.

If these rules hold, swapping Celery for Temporal is a 1–2 week project: re-wrap stages as Temporal activities, replace the run/stage tables with Temporal workflow history (or keep them as an audit shadow), migrate the worker entrypoint.

## Alternatives considered

- **Temporal** — rejected for MVP. Architecturally the right answer for durable workflows; operationally heavy for a pre-revenue project with one developer. Kept on the roadmap with explicit migration path above.
- **Arq** — rejected. Lighter than Celery but smaller community, fewer integrations, no mature monitoring UI.
- **RQ** — rejected. Simpler than Celery but weaker retry/scheduling semantics for our needs.
- **Prefect** — rejected. Closer to Temporal in capability but introduces a Prefect-specific programming model. If we want durable workflows, Temporal is the better long-term bet.
- **Native FastAPI background tasks** — rejected. No retries, no persistence, no observability. Not viable past prototype.

## Revisit triggers

Reopen this ADR if any of the following happens:

- A single ingestion run regularly exceeds 30 minutes wall time AND has more than 3 failure-prone stages — durable resumption stops being a nice-to-have.
- More than 10 % of ingestion runs require manual operator intervention to resume — sign that application-level resumption is failing.
- Multi-tenant SLA requirements demand workflow-level audit history that our Postgres shadow cannot reasonably reconstruct.
- We need to fan out a single ingestion run across more than ~50 parallel stages (e.g., per-chapter parallel embedding for very large textbooks) — Temporal's child workflow model handles this better.

## References

- Celery documentation — https://docs.celeryq.dev/en/stable/ (accessed 2026-05-14)
- Temporal documentation — https://docs.temporal.io/ (accessed 2026-05-14)
- Flower (Celery monitoring) — https://flower.readthedocs.io/ (accessed 2026-05-14)
- Internal: `docs/uber-rag/INGESTION_PIPELINES.md`
- Internal: `docs/uber-rag/STACK_REFERENCES.md` § Orchestration
