# Temporal Live Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the Temporal ingestion path against a real local Temporal service, document the exact runbook, and remove the final practical Phase 2 validation gap.

**Architecture:** Reuse the existing Temporal dispatcher, workflow, and worker bridge without changing ingestion business logic. Add only the smallest local Temporal runtime support, a truthful guarded live integration test, and the documentation/state updates needed to record the result.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, Temporal Python SDK (`temporalio`), Docker Compose

---

### Task 1: Local Temporal dev service

**Files:**
- Modify: `infra/docker/docker-compose.yml`
- Modify: `README.md`

- [ ] **Step 1: Write the failing test**

```python
def test_temporal_live_ingestion_completes_when_server_available() -> None:
    assert False, "Temporal local proof path is not wired yet"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/api/app/tests/integration/test_temporal_live_ingestion.py -q`
Expected: FAIL because the live Temporal validation file/path does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```yaml
temporal:
  image: temporalio/temporal:latest
  command: server start-dev --headless --ip 0.0.0.0 --port 7233 --ui-port 8233
  ports:
    - "7233:7233"
    - "8233:8233"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/api/app/tests/integration/test_temporal_live_ingestion.py -q`
Expected: the test now exists and truthfully `skips` when no Temporal server is running.

- [ ] **Step 5: Commit**

```bash
git add infra/docker/docker-compose.yml README.md apps/api/app/tests/integration/test_temporal_live_ingestion.py
git commit -m "feat: add local temporal validation path"
```

### Task 2: Runnable worker entrypoint

**Files:**
- Modify: `apps/api/app/workflows/temporal_worker.py`
- Modify: `apps/api/app/workflows/temporal_workflow.py`
- Test: `apps/api/app/tests/unit/test_temporal_worker.py`

- [ ] **Step 1: Write the failing test**

```python
async def test_run_temporal_worker_connects_builds_and_runs() -> None:
    events = []

    async def fake_connect(_settings):
        events.append("connect")
        return object()

    def fake_build_runner(_settings):
        events.append("runner")
        return object()

    class FakeWorker:
        async def run(self):
            events.append("worker.run")

    def fake_build_worker(_settings, *, client, runner):
        events.append("worker")
        return FakeWorker()

    await run_temporal_worker(settings, connect_client=fake_connect, build_runner=fake_build_runner, build_worker=fake_build_worker)

    assert events == ["connect", "runner", "worker", "worker.run"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_temporal_worker.py -q`
Expected: FAIL because `run_temporal_worker` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
async def run_temporal_worker(settings: Settings, *, connect_client=connect_temporal_client, build_runner=build_pipeline_runner_from_settings, build_worker=build_temporal_worker_from_settings) -> None:
    client = await connect_client(settings)
    runner = build_runner(settings)
    worker = build_worker(settings, client=client, runner=runner)
    await worker.run()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_temporal_worker.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/workflows/temporal_worker.py apps/api/app/workflows/temporal_workflow.py apps/api/app/tests/unit/test_temporal_worker.py
git commit -m "feat: add runnable temporal worker entrypoint"
```

### Task 3: Guarded live Temporal ingestion proof

**Files:**
- Create: `apps/api/app/tests/integration/test_temporal_live_ingestion.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.anyio
async def test_temporal_live_ingestion_completes_when_server_available() -> None:
    assert False, "real temporal ingestion proof not implemented"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/api/app/tests/integration/test_temporal_live_ingestion.py -q`
Expected: FAIL with the explicit assertion above.

- [ ] **Step 3: Write minimal implementation**

```python
if not await temporal_server_is_available(host_port="127.0.0.1:7233", namespace="default"):
    pytest.skip("Temporal server is not reachable at 127.0.0.1:7233.")

client = await Client.connect("127.0.0.1:7233", namespace="default")
async with Worker(client, task_queue=task_queue, workflows=[IngestionWorkflow], activities=[build_ingestion_activity(runner)]):
    await dispatcher.dispatch(run.id)
    result = await asyncio.wait_for(handle.result(), timeout=60)
    assert result == str(run.id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/api/app/tests/integration/test_temporal_live_ingestion.py -q`
Expected: `1 skipped` when no Temporal server is running, then `1 passed` after the local Temporal server is started.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/tests/integration/test_temporal_live_ingestion.py
git commit -m "test: prove temporal ingestion against local server"
```

### Task 4: Documentation and Phase 2 state closeout

**Files:**
- Modify: `README.md`
- Modify: `docs/uber-rag/PROJECT_STATE.md`
- Modify: `docs/uber-rag/TASKS.md`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write the failing test**

```python
def test_project_state_mentions_local_temporal_proof() -> None:
    text = Path("docs/uber-rag/PROJECT_STATE.md").read_text()
    assert "local Temporal" in text
    assert "remains deferred" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_phase1_docs.py -q`
Expected: FAIL until the docs are updated.

- [ ] **Step 3: Write minimal implementation**

```markdown
- [x] Prove the Temporal worker/dispatcher path against a real local Temporal service.

Local proof completed with:
- `temporal operator cluster health --address 127.0.0.1:7233`
- `.venv/bin/pytest apps/api/app/tests/integration/test_temporal_live_ingestion.py -q`
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_phase1_docs.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add README.md docs/uber-rag/PROJECT_STATE.md docs/uber-rag/TASKS.md pyproject.toml
git commit -m "docs: record local temporal proof"
```
