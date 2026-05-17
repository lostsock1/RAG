# Ingestion Retry Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit audit coverage for ingestion retry success, denial, and conflict outcomes.

**Architecture:** Keep HTTP outcome mapping in `api/routes/ingestion.py`, retry mechanics in `services/ingestion_service.py`, and audit persistence in `repositories/ingestion.py`. Extend the existing ingestion audit pattern with retry-specific helpers so retry becomes contract-compliant without refactoring the whole ingestion audit surface.

**Tech Stack:** Python, FastAPI, SQLAlchemy, pytest.

---

## File Structure

| Action | File | Responsibility |
|---|---|---|
| Modify | `apps/api/app/repositories/ingestion.py` | Add retry-specific audit write helpers |
| Modify | `apps/api/app/api/routes/ingestion.py` | Write denied/conflict/success retry audit events in the correct HTTP branches |
| Modify | `apps/api/app/tests/integration/test_ingestion_jobs.py` | Add red/green integration coverage for retry audit outcomes |
| Modify | `docs/uber-rag/API_CONTRACT.md` | Record that retry is now audited |
| Modify | `docs/uber-rag/PROJECT_STATE.md` | Record slice completion and verification |

---

### Task 1: Add failing retry-audit integration tests

**Files:**
- Modify: `apps/api/app/tests/integration/test_ingestion_jobs.py`

- [ ] **Step 1: Write the failing success-audit test**

Add this test after `test_retry_ingestion_job_redispatches_failed_run`:

```python
def test_retry_ingestion_job_writes_success_audit_event(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    upload = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )

    assert upload.status_code == 201

    run_id = UUID(upload.json()["ingestion_run_id"])

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        assert run is not None
        run.status = "failed"
        session.commit()

    response = client.post(f"/api/v1/ingestion/jobs/{run_id}/retry", headers=auth_headers)

    assert response.status_code == 200

    with session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "ingestion.job.retry")
            .order_by(AuditEvent.timestamp.desc())
        )

    assert audit_event is not None
    assert audit_event.resource_id == run_id
    assert audit_event.details["job_id"] == str(run_id)
    assert audit_event.details["document_id"] == upload.json()["id"]
    assert audit_event.details["previous_status"] == "failed"
    assert audit_event.details["resulting_status"] in {"queued", "running", "completed"}
```

- [ ] **Step 2: Write the failing denied/conflict audit tests**

Add these tests after `test_retry_ingestion_job_rejects_completed_run`:

```python
def test_retry_ingestion_job_writes_denied_audit_event_for_missing_run(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    missing_run_id = uuid4()

    response = client.post(f"/api/v1/ingestion/jobs/{missing_run_id}/retry", headers=auth_headers)

    assert response.status_code == 404

    with session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "ingestion.job.retry.denied")
            .order_by(AuditEvent.timestamp.desc())
        )

    assert audit_event is not None
    assert audit_event.resource_id is None
    assert audit_event.details == {
        "job_id": str(missing_run_id),
        "reason": "not_found_or_denied",
    }


def test_retry_ingestion_job_writes_conflict_audit_event_for_completed_run(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    upload = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )

    assert upload.status_code == 201

    run_id = UUID(upload.json()["ingestion_run_id"])

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        assert run is not None
        run.status = "completed"
        session.commit()

    response = client.post(f"/api/v1/ingestion/jobs/{run_id}/retry", headers=auth_headers)

    assert response.status_code == 409

    with session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "ingestion.job.retry.conflict")
            .order_by(AuditEvent.timestamp.desc())
        )

    assert audit_event is not None
    assert audit_event.resource_id == run_id
    assert audit_event.details == {
        "job_id": str(run_id),
        "document_id": upload.json()["id"],
        "current_status": "completed",
        "reason": "non_retryable_status",
    }
```

- [ ] **Step 3: Run the retry integration tests to verify red**

Run:

```bash
python -m pytest apps/api/app/tests/integration/test_ingestion_jobs.py -k "retry_ingestion_job" -v
```

Expected: FAIL because the retry audit events are not written yet.

---

### Task 2: Implement retry audit helpers and route wiring

**Files:**
- Modify: `apps/api/app/repositories/ingestion.py`
- Modify: `apps/api/app/api/routes/ingestion.py`

- [ ] **Step 1: Add retry audit repository helpers**

Add these functions near the existing ingestion audit helpers in `apps/api/app/repositories/ingestion.py`:

```python
def write_ingestion_job_retry_denied_audit_event(*, tenant_id: str, user_id: str, job_id: UUID) -> None:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Audit persistence is not configured: session_factory has no database bind."
            )

        session.add(
            AuditEvent(
                tenant_id=UUID(tenant_id),
                user_id=UUID(user_id),
                action="ingestion.job.retry.denied",
                resource_type="ingestion_run",
                resource_id=None,
                details={
                    "job_id": str(job_id),
                    "reason": "not_found_or_denied",
                },
            )
        )
        session.commit()


def write_ingestion_job_retry_conflict_audit_event(
    *, tenant_id: str, user_id: str, run: IngestionRun, current_status: str
) -> None:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Audit persistence is not configured: session_factory has no database bind."
            )

        session.add(
            AuditEvent(
                tenant_id=UUID(tenant_id),
                user_id=UUID(user_id),
                action="ingestion.job.retry.conflict",
                resource_type="ingestion_run",
                resource_id=run.id,
                details={
                    "job_id": str(run.id),
                    "document_id": str(run.document_id),
                    "current_status": current_status,
                    "reason": "non_retryable_status",
                },
            )
        )
        session.commit()


def write_ingestion_job_retry_audit_event(
    *, tenant_id: str, user_id: str, run: IngestionRun, previous_status: str
) -> None:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError(
                "Audit persistence is not configured: session_factory has no database bind."
            )

        session.add(
            AuditEvent(
                tenant_id=UUID(tenant_id),
                user_id=UUID(user_id),
                action="ingestion.job.retry",
                resource_type="ingestion_run",
                resource_id=run.id,
                details={
                    "job_id": str(run.id),
                    "document_id": str(run.document_id),
                    "previous_status": previous_status,
                    "resulting_status": run.status,
                },
            )
        )
        session.commit()
```

- [ ] **Step 2: Wire retry audit branches in the route**

In `apps/api/app/api/routes/ingestion.py`, import the three new helpers and update `retry_ingestion_job_route(...)` so it:

```python
    run = await retry_ingestion_job(...)
    if run is None:
        write_ingestion_job_retry_denied_audit_event(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            job_id=job_id,
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion job not found")
```

Wrap the service call so `HTTPException(status_code=409, ...)` produces a conflict audit event using an ACL-visible run lookup before re-raising. On success, write `ingestion.job.retry` using the pre-retry status captured from a lookup before the service call.

- [ ] **Step 3: Re-run the retry tests**

Run:

```bash
python -m pytest apps/api/app/tests/integration/test_ingestion_jobs.py -k "retry_ingestion_job" -v
```

Expected: PASS.

---

### Task 3: Update contract docs and verify the slice

**Files:**
- Modify: `docs/uber-rag/API_CONTRACT.md`
- Modify: `docs/uber-rag/PROJECT_STATE.md`

- [ ] **Step 1: Update the API contract note**

In the Phase 2 ingestion note under `POST /api/v1/ingestion/jobs/{job_id}/retry`, extend the bullet so it explicitly says retry attempts now emit audit events for success, denied/not-found, and conflict outcomes.

- [ ] **Step 2: Update project state**

Add a recent-changes entry noting the retry-audit closure and update the active backend status summary to mention that retry audit coverage is now implemented.

- [ ] **Step 3: Run the targeted verification suite**

Run:

```bash
python -m pytest apps/api/app/tests/integration/test_ingestion_jobs.py -v
```

Expected: PASS.

- [ ] **Step 4: Run the broader ingestion verification suite**

Run:

```bash
python -m pytest apps/api/app/tests/unit/test_ingestion_repository.py apps/api/app/tests/unit/test_dispatcher.py apps/api/app/tests/integration/test_documents_upload.py apps/api/app/tests/integration/test_ingestion_jobs.py apps/api/app/tests/integration/test_ingestion_dispatch.py apps/api/app/tests/integration/test_migrations.py -v
```

Expected: PASS.
