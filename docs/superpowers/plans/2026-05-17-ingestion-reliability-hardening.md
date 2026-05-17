# Ingestion Reliability Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Phase 2 ingestion operationally safe by hardening same-hash dedup, retry/re-dispatch, and startup recovery.

**Architecture:** Keep the current three-stage ingestion pipeline, but make document identity deterministic, run execution claim-based, and stage rows canonical per run/stage name. Add a retry endpoint that re-dispatches the existing run instead of requiring a new upload.

**Tech Stack:** Python, FastAPI, SQLAlchemy, Alembic, pytest.

---

## File Structure

| Action | File | Responsibility |
|---|---|---|
| Modify | `apps/api/app/services/document_service.py` | Deterministic object-key generation and upload flow reuse |
| Modify | `apps/api/app/repositories/documents.py` | DB-backed dedup conflict handling |
| Modify | `apps/api/app/db/models/ingestion.py` | Canonical stage uniqueness |
| Modify | `apps/api/app/repositories/ingestion.py` | Run claim/retry/recovery helpers |
| Modify | `apps/api/app/workflows/dispatcher.py` | Claim-based execution and resume behavior |
| Modify | `apps/api/app/api/routes/ingestion.py` | Retry endpoint |
| Modify | `apps/api/app/services/ingestion_service.py` | Retry service seam |
| Modify | `apps/api/app/schemas/ingestion.py` | Reuse response model for retry route |
| Create | `infra/migrations/versions/20260517_0005_ingestion_reliability_hardening.py` | Unique constraints for live dedup + canonical stages |
| Modify | `apps/api/app/tests/unit/test_ingestion_repository.py` | Red/green tests for recovery, canonical stages, claim/retry helpers |
| Modify | `apps/api/app/tests/unit/test_dispatcher.py` | Dispatcher resume/claim tests |
| Modify | `apps/api/app/tests/integration/test_documents_upload.py` | Deterministic dedup/object-key behavior |
| Modify | `apps/api/app/tests/integration/test_ingestion_jobs.py` | Retry route coverage |
| Modify | `docs/uber-rag/TASKS.md` | Mark completed backlog items |
| Modify | `docs/uber-rag/PROJECT_STATE.md` | Record implementation outcome |

---

### Task 1: Lock in failing tests for reliability semantics

**Files:**
- Modify: `apps/api/app/tests/unit/test_ingestion_repository.py`
- Modify: `apps/api/app/tests/unit/test_dispatcher.py`
- Modify: `apps/api/app/tests/integration/test_documents_upload.py`
- Modify: `apps/api/app/tests/integration/test_ingestion_jobs.py`

- [ ] **Step 1: Add repository tests for canonical stages and recovery**

Add tests covering:

```python
def test_ensure_ingestion_stages_reuses_existing_rows(seeded_run: IngestionRun) -> None:
    first = ensure_ingestion_stages(run_id=seeded_run.id, tenant_id=seeded_run.tenant_id, stage_names=["parse", "persist_artifact", "quality_report"])
    second = ensure_ingestion_stages(run_id=seeded_run.id, tenant_id=seeded_run.tenant_id, stage_names=["parse", "persist_artifact", "quality_report"])
    assert [stage.id for stage in second] == [stage.id for stage in first]


def test_prepare_ingestion_run_for_retry_resets_failed_and_running_stages(seeded_run: IngestionRun) -> None:
    stages = ensure_ingestion_stages(...)
    update_run_status(run_id=seeded_run.id, status="failed")
    update_stage_status(stage_id=stages[0].id, status="completed")
    update_stage_status(stage_id=stages[1].id, status="failed")
    update_stage_status(stage_id=stages[2].id, status="running")

    run = prepare_ingestion_run_for_retry(run_id=seeded_run.id)

    assert run.status == "queued"
    refreshed = get_stages_for_run(run_id=seeded_run.id)
    assert [stage.status for stage in refreshed] == ["completed", "queued", "queued"]
```

- [ ] **Step 2: Add dispatcher tests for claim/resume behavior**

Add tests covering:

```python
def test_in_process_dispatcher_skips_when_run_cannot_be_claimed(dispatcher_env) -> None:
    update_run_status(run_id=dispatcher_env["run_id"], status="running")
    dispatcher = InProcessDispatcher(...)
    dispatcher._execute_pipeline(dispatcher_env["run_id"])
    assert get_stages_for_run(run_id=dispatcher_env["run_id"]) == []


def test_in_process_dispatcher_reruns_parse_when_checkpoint_missing(dispatcher_env) -> None:
    stages = ensure_ingestion_stages(...)
    update_stage_status(stage_id=stages[0].id, status="completed")
    update_stage_status(stage_id=stages[1].id, status="failed")
    update_run_status(run_id=dispatcher_env["run_id"], status="queued")
    dispatcher = InProcessDispatcher(...)
    dispatcher._execute_pipeline(dispatcher_env["run_id"])
    with session_factory() as session:
        assert session.scalar(select(ParsedArtifactRecord).where(ParsedArtifactRecord.run_id == dispatcher_env["run_id"])) is not None
```

- [ ] **Step 3: Add upload and retry-route integration tests**

Add tests covering:

```python
def test_upload_uses_deterministic_object_key_for_same_hash(...):
    first = client.post(... b"hello world" ...)
    second = client.post(... b"hello world" ...)
    assert first.json()["object_key"] == second.json()["object_key"]


def test_retry_ingestion_job_redispatches_failed_run(client: TestClient, auth_headers: dict[str, str]) -> None:
    upload = client.post(...)
    run_id = UUID(upload.json()["ingestion_run_id"])
    update_run_status(run_id=run_id, status="failed")
    response = client.post(f"/api/v1/ingestion/jobs/{run_id}/retry", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["id"] == str(run_id)
    assert response.json()["status"] in {"queued", "running", "completed"}
```

- [ ] **Step 4: Run the failing tests**

Run:

```bash
python -m pytest apps/api/app/tests/unit/test_ingestion_repository.py apps/api/app/tests/unit/test_dispatcher.py apps/api/app/tests/integration/test_documents_upload.py apps/api/app/tests/integration/test_ingestion_jobs.py -v
```

Expected: FAIL because the new helpers, route, and canonical stage behavior do not exist yet.

---

### Task 2: Implement DB-backed dedup and canonical stage helpers

**Files:**
- Modify: `apps/api/app/services/document_service.py`
- Modify: `apps/api/app/repositories/documents.py`
- Modify: `apps/api/app/db/models/ingestion.py`
- Create: `infra/migrations/versions/20260517_0005_ingestion_reliability_hardening.py`
- Modify: `apps/api/app/repositories/ingestion.py`

- [ ] **Step 1: Make upload object keys deterministic**

Update `build_object_key(...)` to accept `source_hash` and produce a stable key:

```python
def build_object_key(*, tenant_id: str, file_name: str, source_hash: str) -> str:
    suffix = Path(file_name).suffix
    return f"documents/{tenant_id}/{source_hash}{suffix}"
```

Update `upload_document(...)` to compute the key with `source_hash` and reuse it in both the existing-document path and the new-document path.

- [ ] **Step 2: Add DB uniqueness and race-safe reload**

Add an Alembic migration creating:

```python
op.create_unique_constraint(
    "uq_documents_live_owner_hash",
    "documents",
    ["tenant_id", "owner_user_id", "source_hash", "is_tombstoned"],
)
op.create_unique_constraint(
    "uq_ingestion_stages_run_stage_name",
    "ingestion_stages",
    ["run_id", "stage_name"],
)
```

Then update `get_or_create_document_by_source_hash(...)` to catch `IntegrityError`, roll back, and reload the canonical document.

- [ ] **Step 3: Replace stage creation with canonical-stage ensure helpers**

Add repository helpers with behavior like:

```python
def ensure_ingestion_stages(*, run_id: UUID, tenant_id: UUID, stage_names: list[str]) -> list[IngestionStage]: ...
def try_claim_ingestion_run(*, run_id: UUID) -> IngestionRun | None: ...
def prepare_ingestion_run_for_retry(*, run_id: UUID) -> IngestionRun: ...
```

Rules:
- `ensure_ingestion_stages(...)` returns one canonical stage row per name in input order.
- `try_claim_ingestion_run(...)` changes `queued -> running` atomically and returns `None` if claim fails.
- `prepare_ingestion_run_for_retry(...)` only allows `failed` or `queued`, resets `failed`/`running` stages to `queued`, and leaves completed stages untouched.

- [ ] **Step 4: Improve startup recovery**

Extend `recover_orphaned_runs()` so it also updates `running` stage rows back to `queued` and merges a recovery marker into `details`.

- [ ] **Step 5: Run repository-focused tests**

Run:

```bash
python -m pytest apps/api/app/tests/unit/test_ingestion_repository.py apps/api/app/tests/integration/test_documents_upload.py -v
```

Expected: PASS.

---

### Task 3: Implement retry route and dispatcher resume behavior

**Files:**
- Modify: `apps/api/app/workflows/dispatcher.py`
- Modify: `apps/api/app/api/routes/ingestion.py`
- Modify: `apps/api/app/services/ingestion_service.py`
- Modify: `apps/api/app/schemas/ingestion.py`

- [ ] **Step 1: Make the dispatcher claim runs and reuse canonical stages**

Update dispatcher flow to:

```python
run = try_claim_ingestion_run(run_id=run_id)
if run is None:
    logger.info("Run %s could not be claimed; skipping duplicate dispatch.", run_id)
    return

stages = ensure_ingestion_stages(...)
```

- [ ] **Step 2: Add parse-checkpoint fallback logic**

If parse is already completed but no persisted artifact exists, reset parse to queued and rerun parse once:

```python
if artifact is None:
    artifact = load_persisted_artifact(run_id)
    if artifact is None:
        reset_stage_to_queued(stage_map["parse"].id, reason="artifact_missing_for_completed_parse")
        artifact = run_parse_stage(...)
```

- [ ] **Step 3: Add retry service and route**

Add a service helper that:
- ACL-loads the run
- prepares it for retry
- re-dispatches it through `request.app.state.dispatcher`
- returns the refreshed run response

Expose it via:

```python
@router.post("/jobs/{job_id}/retry", response_model=IngestionJobResponse)
async def retry_ingestion_job_route(...):
    ...
```

Use `documents:write` scope. Return `404` for not found/denied and `409` for non-retryable states.

- [ ] **Step 4: Run dispatcher and route tests**

Run:

```bash
python -m pytest apps/api/app/tests/unit/test_dispatcher.py apps/api/app/tests/integration/test_ingestion_jobs.py -v
```

Expected: PASS.

---

### Task 4: Verify the slice and update memory

**Files:**
- Modify: `docs/uber-rag/TASKS.md`
- Modify: `docs/uber-rag/PROJECT_STATE.md`

- [ ] **Step 1: Run the complete targeted verification set**

Run:

```bash
python -m pytest apps/api/app/tests/unit/test_ingestion_repository.py apps/api/app/tests/unit/test_dispatcher.py apps/api/app/tests/integration/test_documents_upload.py apps/api/app/tests/integration/test_ingestion_jobs.py apps/api/app/tests/integration/test_ingestion_dispatch.py -v
```

Expected: PASS.

- [ ] **Step 2: Update project memory**

Mark the dedup hardening task done in `docs/uber-rag/TASKS.md` and add a `PROJECT_STATE.md` entry recording:
- deterministic object-key dedup
- canonical stage rows
- retry endpoint
- run/stage startup recovery improvements
- verification command/results

- [ ] **Step 3: Optional full-suite confidence run**

Run:

```bash
python -m pytest -v
```

Expected: PASS or, if omitted, document why targeted verification is sufficient for this slice.
