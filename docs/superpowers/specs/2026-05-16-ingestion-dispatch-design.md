# Ingestion Dispatch Design

Date: 2026-05-16
Status: Approved
Scope: Wire active ingestion dispatch from upload into a local async stage runner.

## Context

Phase 2 foundation slice is landed: ingestion run/stage/artifact/report schema, parser adapter interfaces, quality report helper, and parsed-artifact persistence all exist. But nothing executes — uploads create a `queued` run and stop. This design wires the dispatch so that an upload triggers real stage execution.

### Constraints

- ADR-0002: stages must be idempotent, take `run_id`/`stage_id`, checkpoint to Postgres, be resumable, testable in isolation.
- ADR-0010: Temporal is the lead orchestration direction, but a local async dispatcher is acceptable as an interim step.
- ADR-0011: Docling as parser shell, one normalized artifact contract, deployment-configured backends.
- In-process execution for now (no separate worker process).
- Minimal three stages: parse, persist artifact, quality report.

## Design

### 1. Dispatcher interface

A `WorkflowDispatcher` protocol that the upload path calls. One concrete implementation (`InProcessDispatcher`), swappable later for a Redis-queue worker or Temporal.

```python
# app/workflows/dispatcher.py

class WorkflowDispatcher(Protocol):
    async def dispatch(self, run_id: UUID) -> None: ...
```

The dispatcher instance lives on `app.state.dispatcher`, built at startup from settings. If `parser_backend` is configured, the dispatcher is active. If not, dispatch is a no-op.

### 2. Stage execution model

Three stages, executed sequentially inside a single `asyncio.Task`:

| # | Stage name | Input | Output | What it does |
|---|---|---|---|---|
| 1 | `parse` | `run_id`, document metadata, object key | `ParsedArtifact` | Calls `DocumentParser.parse()`. Resolves parser backend from the run's `parser_backend` field. |
| 2 | `persist_artifact` | `run_id`, `ParsedArtifact` | `ParsedArtifactRecord` | Calls `store_parsed_artifact()`. Already exists — wired into the stage flow. |
| 3 | `quality_report` | `run_id`, `ParsedArtifact` | `QualityReport` | The quality report is already generated and persisted inside `store_parsed_artifact` (stage 2). This stage reads it back and records a completed `IngestionStage` entry with report details (quality_score, warnings) for visibility and audit. |

Execution flow:

```
dispatch(run_id)
  -> create 3 IngestionStage records (status=queued)
  -> update run status to "running"
  -> stage 1: parse
      -> update stage status to "running"
      -> call parser.parse(request)
      -> update stage status to "completed", write details (page_count, table_count, parser_backend)
  -> stage 2: persist_artifact
      -> update stage status to "running"
      -> call store_parsed_artifact(run_id, artifact)
      -> update stage status to "completed"
  -> stage 3: quality_report
      -> update stage status to "running"
      -> read back the quality report for this run
      -> update stage status to "completed", write details (quality_score, warnings)
  -> update run status to "completed"
```

Failure handling: if any stage raises, catch the exception, mark that stage as `failed` with error details, mark the run as `failed`, and stop. No retry at this layer — idempotent stages mean a re-dispatch of the same `run_id` picks up where it left off.

Idempotency: before running a stage, check if an `IngestionStage` with that `stage_name` already exists and is `completed`. If so, skip it. This makes re-dispatch safe.

### 3. Startup recovery

On app startup (FastAPI `lifespan`), query for any `IngestionRun` with `status="running"`. These are orphaned — the in-process task died with the server. Reset them to `status="queued"`.

No auto-re-dispatch on startup. The recovery sweep prevents stuck `running` status. A manual re-dispatch endpoint or periodic sweeper can be added later.

### 4. Wiring points

| Where | What changes |
|---|---|
| `app/workflows/dispatcher.py` | New file. `WorkflowDispatcher` protocol + `InProcessDispatcher` implementation. |
| `app/workflows/stages.py` | New file. Three stage functions: `run_parse_stage`, `run_persist_artifact_stage`, `run_quality_report_stage`. Each takes `run_id` + session, reads/writes checkpoints, calls existing services. |
| `app/workflows/ingestion_workflow.py` | Simplified. The Temporal shim stays for later, but the active path goes through the dispatcher. |
| `app/repositories/ingestion.py` | Add: `create_ingestion_stages`, `update_stage_status`, `update_run_status`, `get_stages_for_run`, `recover_orphaned_runs`. |
| `app/services/document_service.py` | After `create_ingestion_run`, call `dispatcher.dispatch(run.id)`. Dispatcher fetched from app state. |
| `app/main.py` | Build dispatcher at startup, attach to `app.state.dispatcher`. Run recovery sweep in lifespan. |
| `app/core/config.py` | No changes needed — `parser_backend` already exists. |

### 5. What does not change

- Storage adapter, ACL service, auth, audit — untouched.
- Parser interfaces (`DocumentParser`, `DoclingDocumentParser`, `RemoteDocumentParser`) — unchanged, just actually called now.
- `store_parsed_artifact` and `build_quality_report` — unchanged, just wired into the stage flow.
- API routes — no contract changes. Upload response already returns `ingestion_run_id`. Ingestion jobs endpoints already return status.

### 6. Test strategy

- Unit tests for each stage function with mock parser and in-memory DB.
- Integration test: upload a document -> verify run progresses to `completed` with 3 stages all `completed` -> verify parsed artifact and quality report exist.
- Integration test: stage failure -> verify run marked `failed`, artifact not persisted.
- Integration test: re-dispatch a `failed` run -> verify completed stages are skipped, failed stage re-runs.

### 7. Migration to Temporal later

When Temporal is wired:
- Each stage function becomes a Temporal activity (same signature, same idempotency).
- `InProcessDispatcher.dispatch()` is replaced by a `TemporalDispatcher.dispatch()` that starts a workflow.
- The `IngestionStage` records become an audit shadow of Temporal's own history.
- No changes to stage function internals, parser interfaces, or API routes.

## Open questions

None. All design decisions resolved through the brainstorming session.

## References

- ADR-0002: Ingestion Orchestration — Celery Now, Temporal-Ready Design
- ADR-0010: Ingestion Orchestration Direction for Phase 2 — Temporal as Lead Candidate
- ADR-0011: Structured Document-Understanding Architecture for Phase 2
