# Phase 2 Temporal Dispatch Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a concrete Temporal dispatch adapter and runnable worker skeleton while keeping the current in-process ingestion dispatcher as the default runtime path.

**Architecture:** Extract the existing ingestion stage execution into a shared backend-neutral pipeline runner, then hang both the current in-process dispatcher and a new Temporal dispatcher off that runner. Keep DB-backed run/stage truth, ACL behavior, retry/recovery semantics, and parser/storage seams unchanged.

**Tech Stack:** FastAPI, Python 3.12, SQLAlchemy, Pydantic v2, Temporal Python SDK, pytest

---

## File structure

- Create: `apps/api/app/workflows/pipeline_runner.py` — shared ingestion pipeline executor reused by in-process and Temporal paths.
- Create: `apps/api/app/workflows/temporal_dispatcher.py` — `WorkflowDispatcher` implementation that submits ingestion runs to Temporal.
- Create: `apps/api/app/workflows/temporal_workflow.py` — Temporal workflow and activity bridge definitions.
- Create: `apps/api/app/workflows/temporal_worker.py` — runnable worker bootstrap that registers workflow/activity entrypoints.
- Modify: `apps/api/app/workflows/dispatcher.py` — slim `InProcessDispatcher` to call the shared runner.
- Modify: `apps/api/app/main.py` — select workflow backend from config at startup.
- Modify: `apps/api/app/core/config.py` — formalize `workflow_backend` and Temporal config validation inputs.
- Modify: `apps/api/app/tests/unit/test_dispatcher.py` — keep in-process behavior green and cover extracted runner semantics.
- Modify: `apps/api/app/tests/integration/test_runtime_auth_startup.py` — verify backend selection / startup failure behavior.
- Modify: `apps/api/app/tests/integration/test_ingestion_dispatch.py` — prove in-process default remains stable.
- Create: `apps/api/app/tests/unit/test_temporal_dispatcher.py` — Temporal enqueue contract tests.
- Create: `apps/api/app/tests/unit/test_temporal_worker.py` — workflow/worker registration contract tests.
- Modify: `docs/uber-rag/API_CONTRACT.md` — document backend-neutral dispatch truthfully.
- Modify: `docs/uber-rag/PROJECT_STATE.md` — record the completed slice and remaining limitations.
- Modify: `docs/uber-rag/TASKS.md` — mark the orchestration hardening slice done if completed.

### Task 1: Backend config and startup selection

**Files:**
- Modify: `apps/api/app/core/config.py`
- Modify: `apps/api/app/main.py`
- Test: `apps/api/app/tests/integration/test_runtime_auth_startup.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_startup_uses_in_process_dispatcher_by_default(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'default.db'}",
        local_storage_dir=str(tmp_path / "storage"),
    )

    test_app = create_app(settings)
    with TestClient(test_app):
        assert test_app.state.dispatcher.__class__.__name__ == "InProcessDispatcher"


def test_startup_fails_when_temporal_backend_selected_without_host_port(tmp_path: Path) -> None:
    settings = Settings(
        workflow_backend="temporal",
        database_url=f"sqlite:///{tmp_path / 'temporal.db'}",
        local_storage_dir=str(tmp_path / "storage"),
        temporal_host_port=None,
    )

    test_app = create_app(settings)
    with pytest.raises(RuntimeError, match="temporal_host_port"):
        with TestClient(test_app):
            pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/api/app/tests/integration/test_runtime_auth_startup.py -q`
Expected: FAIL because `workflow_backend` does not exist yet or startup still always builds `InProcessDispatcher`.

- [ ] **Step 3: Write minimal implementation**

```python
class Settings(BaseSettings):
    workflow_backend: Literal["in_process", "temporal"] = "in_process"
```

```python
def _build_dispatcher(*, settings: Settings, parser: DocumentParser, parser_backend: str, parser_profile: str, ocr_service: OcrService, storage: StorageAdapter | None) -> WorkflowDispatcher:
    if settings.workflow_backend == "in_process":
        return InProcessDispatcher(
            parser=parser,
            parser_backend=parser_backend,
            parser_profile=parser_profile,
            ocr_service=ocr_service,
            storage=storage,
        )

    if not settings.temporal_host_port:
        raise RuntimeError("workflow_backend=temporal requires temporal_host_port")

    return TemporalDispatcher(
        host_port=settings.temporal_host_port,
        namespace=settings.temporal_namespace,
        task_queue=settings.temporal_task_queue,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest apps/api/app/tests/integration/test_runtime_auth_startup.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
# Only if the user explicitly asked for commits
git add apps/api/app/core/config.py apps/api/app/main.py apps/api/app/tests/integration/test_runtime_auth_startup.py
git commit -m "feat: add workflow backend startup selection"
```

### Task 2: Shared pipeline runner extraction

**Files:**
- Create: `apps/api/app/workflows/pipeline_runner.py`
- Modify: `apps/api/app/workflows/dispatcher.py`
- Test: `apps/api/app/tests/unit/test_dispatcher.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_pipeline_runner_executes_parse_persist_and_quality(seeded_env) -> None:
    runner = PipelineRunner(
        parser=DoclingDocumentParser(converter=lambda _req: _make_test_artifact(seeded_env["document_id"])),
        parser_backend="docling-local",
        parser_profile="local-cpu",
        ocr_service=StubOcrService(
            OcrResult(status="unverified", applied=None, engine="tesseract", provider="docling-local")
        ),
        storage=None,
    )

    runner.run(seeded_env["run_id"])

    stages = get_stages_for_run(run_id=seeded_env["run_id"])
    assert [stage.status for stage in stages] == ["completed", "completed", "completed"]


def test_in_process_dispatcher_delegates_to_pipeline_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[UUID] = []

    class RunnerStub:
        def run(self, run_id: UUID) -> None:
            calls.append(run_id)

    dispatcher = InProcessDispatcher(runner=RunnerStub())
    dispatcher._execute_pipeline(uuid4())
    assert len(calls) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/api/app/tests/unit/test_dispatcher.py -q`
Expected: FAIL because `PipelineRunner` does not exist and `InProcessDispatcher` does not delegate.

- [ ] **Step 3: Write minimal implementation**

```python
class PipelineRunner:
    def __init__(self, *, parser: DocumentParser, parser_backend: str, parser_profile: str, ocr_service: OcrService | None, storage: StorageAdapter | None) -> None:
        self._parser = parser
        self._parser_backend = parser_backend
        self._parser_profile = parser_profile
        self._ocr_service = ocr_service
        self._storage = storage

    def run(self, run_id: UUID) -> None:
        # move current _execute_pipeline body here
        ...
```

```python
class InProcessDispatcher:
    def __init__(self, ..., runner: PipelineRunner | None = None) -> None:
        self._runner = runner or PipelineRunner(...)

    def _execute_pipeline(self, run_id: UUID) -> None:
        self._runner.run(run_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest apps/api/app/tests/unit/test_dispatcher.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
# Only if the user explicitly asked for commits
git add apps/api/app/workflows/pipeline_runner.py apps/api/app/workflows/dispatcher.py apps/api/app/tests/unit/test_dispatcher.py
git commit -m "refactor: extract shared ingestion pipeline runner"
```

### Task 3: Temporal dispatcher submission contract

**Files:**
- Create: `apps/api/app/workflows/temporal_dispatcher.py`
- Create: `apps/api/app/tests/unit/test_temporal_dispatcher.py`
- Modify: `apps/api/app/main.py`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_temporal_dispatcher_submits_ingestion_workflow() -> None:
    submitted: dict[str, object] = {}

    class ClientStub:
        async def execute_workflow(self, workflow: object, *, id: str, task_queue: str, args: list[object]) -> None:
            submitted["workflow"] = workflow
            submitted["id"] = id
            submitted["task_queue"] = task_queue
            submitted["args"] = args

    dispatcher = TemporalDispatcher(
        host_port="temporal:7233",
        namespace="default",
        task_queue="uber-rag-ingestion",
        client=ClientStub(),
    )

    run_id = uuid4()
    await dispatcher.dispatch(run_id)

    assert submitted["id"] == f"ingestion-run:{run_id}"
    assert submitted["task_queue"] == "uber-rag-ingestion"
    assert submitted["args"] == [str(run_id)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/api/app/tests/unit/test_temporal_dispatcher.py -q`
Expected: FAIL because `TemporalDispatcher` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
class TemporalDispatcher:
    def __init__(self, *, host_port: str, namespace: str, task_queue: str, client: object | None = None) -> None:
        self._host_port = host_port
        self._namespace = namespace
        self._task_queue = task_queue
        self._client = client

    async def dispatch(self, run_id: UUID) -> None:
        client = self._client or await Client.connect(self._host_port, namespace=self._namespace)
        await client.execute_workflow(
            IngestionWorkflow.run,
            id=f"ingestion-run:{run_id}",
            task_queue=self._task_queue,
            args=[str(run_id)],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest apps/api/app/tests/unit/test_temporal_dispatcher.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
# Only if the user explicitly asked for commits
git add apps/api/app/workflows/temporal_dispatcher.py apps/api/app/tests/unit/test_temporal_dispatcher.py apps/api/app/main.py
git commit -m "feat: add temporal ingestion dispatcher"
```

### Task 4: Temporal workflow and worker skeleton

**Files:**
- Create: `apps/api/app/workflows/temporal_workflow.py`
- Create: `apps/api/app/workflows/temporal_worker.py`
- Create: `apps/api/app/tests/unit/test_temporal_worker.py`
- Modify: `docs/uber-rag/API_CONTRACT.md`
- Modify: `docs/uber-rag/PROJECT_STATE.md`
- Modify: `docs/uber-rag/TASKS.md`

- [ ] **Step 1: Write the failing tests**

```python
def test_ingestion_workflow_activity_bridge_calls_pipeline_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[UUID] = []

    class RunnerStub:
        def run(self, run_id: UUID) -> None:
            seen.append(run_id)

    activity = build_ingestion_activity(RunnerStub())
    run_id = uuid4()
    activity(str(run_id))
    assert seen == [run_id]


def test_temporal_worker_builds_with_registered_workflow_and_activity() -> None:
    worker = build_temporal_worker(
        client=object(),
        task_queue="uber-rag-ingestion",
        runner=object(),
    )

    assert worker is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/api/app/tests/unit/test_temporal_worker.py -q`
Expected: FAIL because workflow/worker files do not exist.

- [ ] **Step 3: Write minimal implementation**

```python
@workflow.defn
class IngestionWorkflow:
    @workflow.run
    async def run(self, run_id: str) -> None:
        await workflow.execute_activity(run_ingestion_activity, run_id, start_to_close_timeout=timedelta(minutes=30))
```

```python
def build_ingestion_activity(runner: PipelineRunner):
    @activity.defn(name="run_ingestion_activity")
    def run_ingestion_activity(run_id: str) -> None:
        runner.run(UUID(run_id))

    return run_ingestion_activity
```

```python
def build_temporal_worker(*, client: Client, task_queue: str, runner: PipelineRunner) -> Worker:
    return Worker(
        client,
        task_queue=task_queue,
        workflows=[IngestionWorkflow],
        activities=[build_ingestion_activity(runner)],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest apps/api/app/tests/unit/test_temporal_worker.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
# Only if the user explicitly asked for commits
git add apps/api/app/workflows/temporal_workflow.py apps/api/app/workflows/temporal_worker.py apps/api/app/tests/unit/test_temporal_worker.py docs/uber-rag/API_CONTRACT.md docs/uber-rag/PROJECT_STATE.md docs/uber-rag/TASKS.md
git commit -m "feat: add temporal worker skeleton for ingestion"
```

### Task 5: Final regression and documentation truthfulness

**Files:**
- Modify: `apps/api/app/tests/integration/test_ingestion_dispatch.py`
- Modify: `apps/api/app/tests/integration/test_runtime_auth_startup.py`
- Modify: `docs/uber-rag/API_CONTRACT.md`
- Modify: `docs/uber-rag/PROJECT_STATE.md`
- Modify: `docs/uber-rag/TASKS.md`

- [ ] **Step 1: Write the failing regression checks**

```python
def test_in_process_dispatch_remains_default_under_existing_settings() -> None:
    ...


def test_temporal_backend_startup_documents_worker_backed_dispatch_truthfully() -> None:
    text = Path("docs/uber-rag/API_CONTRACT.md").read_text()
    assert "in_process default" in text
    assert "temporal explicit opt-in" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/api/app/tests/integration/test_ingestion_dispatch.py apps/api/app/tests/integration/test_runtime_auth_startup.py apps/api/app/tests/unit/test_phase1_docs.py -q`
Expected: FAIL until docs/runtime truth is updated.

- [ ] **Step 3: Write minimal implementation**

```markdown
- In-process remains the default workflow backend.
- Temporal dispatch is explicit opt-in via runtime configuration.
- The Temporal worker skeleton reuses the shared pipeline runner and does not redefine stage business logic.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest apps/api/app/tests/unit/test_temporal_dispatcher.py apps/api/app/tests/unit/test_temporal_worker.py apps/api/app/tests/unit/test_dispatcher.py apps/api/app/tests/integration/test_ingestion_dispatch.py apps/api/app/tests/integration/test_runtime_auth_startup.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
# Only if the user explicitly asked for commits
git add apps/api/app/tests/integration/test_ingestion_dispatch.py apps/api/app/tests/integration/test_runtime_auth_startup.py docs/uber-rag/API_CONTRACT.md docs/uber-rag/PROJECT_STATE.md docs/uber-rag/TASKS.md
git commit -m "docs: record temporal opt-in dispatch hardening"
```

## Self-review

- Spec coverage: config selection, shared runner extraction, Temporal dispatcher, worker skeleton, docs, and tests are each covered by a dedicated task.
- Placeholder scan: no `TODO` / `TBD` markers remain; every task includes concrete files, commands, and expected failures.
- Type consistency: plan consistently uses `workflow_backend` values `in_process` / `temporal`, parser/profile canonical labels, and `run_id: UUID` through dispatch and worker boundaries.
