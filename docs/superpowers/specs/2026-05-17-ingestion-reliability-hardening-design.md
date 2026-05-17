# Ingestion Reliability Hardening Design

Date: 2026-05-17
Status: Approved
Scope: Harden Phase 2 ingestion reliability around concurrent dedup, retry/re-dispatch, and startup recovery without changing the broader parser/OCR roadmap.

## Context

The current ingestion foundation already supports upload-time run creation, in-process dispatch, idempotent parsed-artifact persistence, and startup recovery that resets orphaned `running` runs to `queued`.

The remaining operational gap is reliability:

- same-hash uploads are only serially safe today
- retries require new uploads instead of reusing the existing run
- stage records are recreated on every dispatch rather than treated as canonical per run
- startup recovery resets run state but does not fully reconcile stage state

This is the next highest-value slice because it reduces correctness risk for every later parser, OCR, and quality-report expansion.

## Decision

Implement a reliability-first hardening slice with four rules:

1. **Dedup identity is deterministic and DB-backed.**
   - Compute object keys from tenant + source hash rather than per-upload UUIDs.
   - Add a DB uniqueness guard for live documents so concurrent same-hash uploads converge to one canonical document.

2. **Run execution is claim-based.**
   - A dispatcher must atomically claim a queued run before executing it.
   - Duplicate dispatch attempts become harmless no-ops instead of double execution.

3. **Stage rows are canonical per run/stage name.**
   - Each run keeps one row per stage (`parse`, `persist_artifact`, `quality_report`).
   - Retry/reset operations update those rows instead of creating new stage histories each time.

4. **Retry is re-dispatch of the same run.**
   - A failed or queued run can be retried through an authenticated API route.
   - Retry resets `failed`/`running` stages to `queued`, preserves completed stages where possible, and reuses the original stored object.

## Design

### 1. Concurrent dedup

- Change object-key generation to a deterministic hash-based key.
- Add a unique constraint over the live-document identity (`tenant_id`, `owner_user_id`, `source_hash`, `is_tombstoned`).
- Keep the current fast-path lookup, but catch unique-constraint races on insert and reload the canonical row.

This means two concurrent uploads of the same bytes converge on the same document row and the same storage key.

### 2. Canonical stage management

- Add a uniqueness guard over `ingestion_stages(run_id, stage_name)`.
- Replace “always create stages” with “ensure canonical stage rows exist for this run”.
- Retry/recovery should mutate existing stage rows instead of appending duplicates.

### 3. Retry semantics

- Add `POST /api/v1/ingestion/jobs/{job_id}/retry`.
- Require `documents:write` scope.
- Reuse ACL-aware run lookup so the frontend remains no more privileged than the API.
- Eligible states: `failed`, `queued`.
- Ineligible states: `running`, `completed`.

### 4. Resume behavior inside the dispatcher

- Dispatcher first tries to claim the run (`queued -> running`).
- If parse is already complete, dispatcher attempts to load the persisted parsed artifact.
- If parse is marked complete but the persisted artifact does not exist, dispatcher resets parse to `queued` and reruns parse.
- Persist and quality stages stay idempotent.

This preserves the useful checkpoint case (`quality` retry after artifact persistence) while staying correct for partially completed earlier runs.

### 5. Startup recovery

- Reset orphaned `running` runs to `queued`.
- Reset any `running` stage rows to `queued` and annotate the reset reason.

This keeps recovery workflow-backend-neutral and compatible with both the current in-process dispatcher and a future Temporal-backed dispatcher.

## Tests

Add or extend tests for:

- concurrent/same-hash document creation behavior via repository-level unique-constraint race handling
- deterministic object-key reuse for same-hash uploads
- retry route eligibility and ACL enforcement
- canonical stage creation/reuse without duplicates
- dispatcher claim behavior for duplicate dispatch calls
- startup recovery of both run and stage rows
- retry of a failed later stage without requiring a new upload

## Non-goals

- OCR adapter execution path
- richer quality report schema
- Temporal runtime implementation
- parser backend matrix expansion beyond what retry/recovery needs

## Outcome

After this slice, ingestion runs can be retried safely, duplicate dispatch becomes harmless, and same-hash uploads converge on one canonical document/object identity.
