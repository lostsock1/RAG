# Phase 2 Temporal Dispatch Hardening Design

**Date:** 2026-05-17
**Status:** Proposed for implementation
**Scope:** Complete the remaining orchestration-hardening slice of Phase 2 by adding a concrete Temporal dispatch path and runnable worker skeleton while preserving the current in-process dispatcher as the default runtime path.

## Goal

Add a real Temporal-backed ingestion dispatch adapter and runnable worker skeleton without changing the current default behavior of the application. The system must keep the existing ingestion stage logic, preserve Phase 2 ACL and persistence behavior, and remain backend-neutral through the `WorkflowDispatcher` seam.

## Non-goals

- No retrieval, indexing, reranking, or chat work.
- No live Temporal integration test requirement in this slice.
- No replacement of the current in-process dispatcher as the default runtime backend.
- No broad migration of existing ingestion persistence schema unless strictly required.

## Context

The current Phase 2 ingestion path is functionally complete, but orchestration is still primarily in-process. The repo already has:

- DB-backed ingestion runs and stages
- claim-based dispatch
- retry/recovery behavior
- storage materialization for parsing
- parser/profile truthfulness and OCR provenance truthfulness improvements

What remains is to make orchestration more production-shaped by adding a concrete Temporal dispatch path. This must align with existing accepted decisions:

- `ADR-0010`: Temporal is the approved Phase 2 orchestration direction
- `ADR-0011`: deployment-configured backends, backend-neutral downstream pipeline
- architecture invariant: modular adapters and backend replaceability

## Requirements

### Functional

1. The runtime must support two workflow backends:
   - `in_process` (default)
   - `temporal` (explicit opt-in)
2. Upload and retry endpoints must continue to dispatch through a backend-neutral dispatcher seam.
3. A concrete `TemporalDispatcher` must submit ingestion work to Temporal using the ingestion `run_id`.
4. A runnable Temporal worker skeleton must exist in the repo.
5. Temporal orchestration must reuse the same ingestion pipeline contract as the in-process path.

### Safety / architecture

1. Existing in-process behavior remains the default and must not regress.
2. The Temporal path must not duplicate parse/persist/report business logic.
3. ACL behavior must remain unchanged.
4. Retry and recovery semantics must remain tied to existing DB-backed run/stage truth, not Temporal-only state.
5. The implementation must keep the orchestration backend swappable.

### Testing

1. Backend selection must be covered by tests.
2. Temporal dispatch submission must be covered by unit tests.
3. Shared pipeline execution must be covered by unit tests.
4. Startup/runtime config behavior must be covered.
5. No live Temporal service requirement for green tests in this slice.

## Approaches considered

### Approach 1 — Keep in-process default, add Temporal as explicit opt-in

Add a backend selector at startup. Keep current in-process dispatch as default. Add Temporal dispatch and worker files behind explicit configuration.

**Why recommended**
- Safest incremental rollout
- Preserves today’s working ingestion path
- Adds real production-shaped orchestration without forcing infra everywhere
- Best fit for remaining Phase 2 scope

**Tradeoff**
- Two dispatch paths coexist temporarily

### Approach 2 — Config switch with equal first-class support immediately

Support both backends equally from day one and treat both as standard runtime modes.

**Why rejected**
- More surface area than this slice needs
- Higher stabilization cost now

### Approach 3 — Temporal-first replacement

Replace in-process dispatch as the preferred runtime path and keep in-process only as fallback.

**Why rejected**
- Too risky for a Phase 2 hardening slice
- Destabilizes the known-good current path

## Chosen design

Use **Approach 1**.

### Runtime model

- Add or formalize a `workflow_backend` setting with allowed values:
  - `in_process`
  - `temporal`
- Default remains `in_process`.
- `main.py` chooses which dispatcher to build at startup.
- API routes keep using the same dispatcher seam and do not branch on backend-specific behavior.

### Shared execution model

Extract the current stage-running logic from `InProcessDispatcher` into a shared backend-neutral runner.

That runner is responsible for:
- claiming the run
- loading document/object metadata
- materializing storage if needed
- running parse → persist_artifact → quality_report
- preserving retry/recovery behavior
- marking run/stage state based on existing repository helpers

This runner remains synchronous/thread-friendly so both:
- in-process dispatch
- Temporal activity execution

can call the same code.

### Temporal model

#### Dispatcher

`TemporalDispatcher.dispatch(run_id)` submits a workflow execution to Temporal.

Expected responsibilities:
- create Temporal client from settings
- submit workflow with `run_id`
- use stable workflow identity derived from ingestion run for deduplication clarity
- not execute ingestion logic inline

#### Workflow

The Temporal workflow should stay thin.

Expected responsibilities:
- accept `run_id`
- call one activity or one worker-side runner entrypoint
- avoid embedding ingestion business logic directly in workflow code

#### Worker skeleton

The worker skeleton should be runnable from the repo and register:
- the ingestion workflow
- the workflow activity/runner bridge

It does not need broad production CLI polish in this slice. It does need enough structure to prove the architecture is real and runnable.

## File boundaries

### New files

- `apps/api/app/workflows/pipeline_runner.py`
  - shared backend-neutral ingestion pipeline executor
- `apps/api/app/workflows/temporal_dispatcher.py`
  - Temporal submission adapter implementing the dispatcher seam
- `apps/api/app/workflows/temporal_workflow.py`
  - Temporal workflow definition
- `apps/api/app/workflows/temporal_worker.py`
  - worker bootstrap / registration entrypoint

### Existing files to modify

- `apps/api/app/workflows/dispatcher.py`
  - keep `InProcessDispatcher`, but shrink it to use `pipeline_runner`
- `apps/api/app/main.py`
  - build either in-process or Temporal dispatcher from config
- `apps/api/app/core/config.py`
  - formalize `workflow_backend` and Temporal settings if needed
- tests around startup, dispatcher, ingestion routes
- project memory / contract docs reflecting the new runtime truth

## Data flow

### In-process path

1. API creates/updates ingestion run
2. route calls dispatcher seam
3. `InProcessDispatcher.dispatch(run_id)` schedules local execution
4. shared pipeline runner executes stages
5. DB remains source of truth for run/stage state

### Temporal path

1. API creates/updates ingestion run
2. route calls dispatcher seam
3. `TemporalDispatcher.dispatch(run_id)` submits workflow
4. Temporal worker receives workflow
5. workflow invokes shared pipeline runner through activity/bridge
6. DB remains source of truth for run/stage state

## Error handling

### Startup/config

- If `workflow_backend=temporal` but required Temporal config is missing, startup fails clearly.
- If `workflow_backend=in_process`, no Temporal config is required.

### Dispatch

- Temporal submission failures should surface as dispatch failures, not silently fall back to in-process.
- In-process remains default only by explicit configuration, not by hidden fallback when Temporal is selected.

### Pipeline execution

- Shared runner continues existing behavior for stage/run failure marking.
- Temporal does not become the source of truth for business completion state; DB-backed run/stage rows remain authoritative.

## Testing strategy

### Unit tests

- backend selection in startup/config wiring
- Temporal dispatcher submission contract
- pipeline runner execution contract
- Temporal worker/workflow registration shape
- explicit failure when Temporal backend selected without valid config

### Integration tests

- ingestion route behavior remains stable under in-process default
- startup/runtime tests for Temporal config opt-in behavior
- no requirement for live Temporal service in CI for this slice

## Risks

1. **Backend drift**
   - If in-process and Temporal paths diverge, orchestration becomes inconsistent.
   - Mitigation: shared `pipeline_runner.py`

2. **Config ambiguity**
   - Hidden fallback could make Temporal misconfiguration hard to detect.
   - Mitigation: no implicit fallback when Temporal is explicitly selected.

3. **Scope creep into full Temporal integration**
   - This slice could expand into infrastructure-heavy live integration.
   - Mitigation: keep live Temporal integration out of scope.

## Acceptance criteria

1. App defaults to in-process backend unchanged.
2. App can be configured to use Temporal dispatcher explicitly.
3. Temporal dispatcher submits a workflow using ingestion `run_id`.
4. Runnable Temporal worker skeleton exists and registers workflow/activity entrypoints.
5. Shared pipeline logic is not duplicated between in-process and Temporal paths.
6. Targeted tests pass without requiring a live Temporal server.
7. Docs/project memory reflect the new runtime truth.

## Open choices intentionally resolved here

- **Coexistence model:** keep in-process default, add Temporal as explicit opt-in.
- **Success shape:** real Temporal adapter + runnable worker skeleton, but no required live worker integration tests.
- **Fallback behavior:** explicit backend choice only; no silent Temporal-to-local fallback once Temporal is selected.

## Implementation handoff note

The implementation plan should focus on a small, test-driven slice order:
1. config/runtime selection
2. shared pipeline runner extraction
3. Temporal dispatcher
4. worker/workflow skeleton
5. docs and verification
