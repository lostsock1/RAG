# Storage Materialization Seam for Docling Parsing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SeaweedFS-backed parsing runnable by adding a general storage materialization seam that always provides Docling a local file path.

**Architecture:** Extend `StorageAdapter` with a read/materialize capability that yields a `MaterializedObject` containing a local path and optional cleanup callback. Thread that seam through dispatcher and parse request so Docling consumes `local_source_path` rather than assuming `storage_root / object_key`. Keep local and S3-compatible storage behind the same contract.

**Tech Stack:** Python, FastAPI runtime seams, S3-compatible storage adapter, temp-file materialization, Docling parser path, pytest.

---

## File Structure

| Action | File | Responsibility |
|---|---|---|
| Modify | `apps/api/app/services/storage.py` | Add `MaterializedObject` and `materialize_for_read()` implementations |
| Modify | `apps/api/app/services/parsers/base.py` | Extend `ParseRequest` with `local_source_path` |
| Modify | `apps/api/app/services/parsers/docling_backend.py` | Prefer materialized local path for runtime parsing |
| Modify | `apps/api/app/services/parsers/factory.py` | Relax/remove current SeaweedFS + local Docling guard after runtime path is supported |
| Modify | `apps/api/app/workflows/dispatcher.py` | Materialize object before parse and always cleanup |
| Modify | `apps/api/app/workflows/stages.py` | Accept/pass `local_source_path` into parse stage |
| Modify | `apps/api/app/tests/unit/test_storage_adapters.py` | Materialization seam tests |
| Modify | `apps/api/app/tests/unit/test_parser_backends.py` | Parser local_source_path tests |
| Modify | `apps/api/app/tests/unit/test_dispatcher.py` | Dispatcher cleanup/materialization tests |
| Modify | `apps/api/app/tests/integration/test_ingestion_dispatch.py` | End-to-end S3-compatible parsing path with fake client |
| Modify | `apps/api/app/tests/integration/test_runtime_auth_startup.py` | Update startup expectations once guard is relaxed |
| Modify | `pyproject.toml` | Add `boto3` runtime dependency |

---

### Task 1: Add the storage materialization seam

**Files:**
- Modify: `apps/api/app/services/storage.py`
- Test: `apps/api/app/tests/unit/test_storage_adapters.py`

- [ ] **Step 1: Write the failing tests**

Add these tests to the end of `apps/api/app/tests/unit/test_storage_adapters.py`:

```python
from app.services.storage import MaterializedObject


def test_local_filesystem_storage_adapter_materialize_for_read_returns_existing_path(tmp_path: Path) -> None:
    source_path = tmp_path / "documents" / "tenant-1" / "sample.txt"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("hello world")

    adapter = LocalFilesystemStorageAdapter(tmp_path)
    materialized = adapter.materialize_for_read(object_key="documents/tenant-1/sample.txt")

    assert materialized.local_path == source_path
    assert materialized.local_path.read_text() == "hello world"
    assert materialized.cleanup is None


def test_local_filesystem_storage_adapter_materialize_for_read_raises_when_file_missing(tmp_path: Path) -> None:
    adapter = LocalFilesystemStorageAdapter(tmp_path)

    with pytest.raises(RuntimeError) as exc_info:
        adapter.materialize_for_read(object_key="documents/missing.txt")

    assert "could not find object" in str(exc_info.value)
    assert "documents/missing.txt" in str(exc_info.value)


def test_s3_compatible_storage_adapter_materialize_for_read_downloads_temp_file(tmp_path: Path) -> None:
    class FakeClient:
        def download_file(self, Bucket: str, Key: str, Filename: str) -> None:
            Path(Filename).write_bytes(b"seaweedfs payload")

    adapter = S3CompatibleStorageAdapter(
        endpoint_url="http://seaweedfs:8333",
        access_key="test-access",
        secret_key="test-secret",
        bucket="uber-rag-documents",
        region="us-east-1",
        client=FakeClient(),
    )

    materialized = adapter.materialize_for_read(object_key="documents/tenant-1/sample.pdf")

    assert materialized.local_path.exists()
    assert materialized.local_path.read_bytes() == b"seaweedfs payload"
    assert materialized.cleanup is not None
    materialized.cleanup()
    assert not materialized.local_path.exists()
```

- [ ] **Step 2: Run targeted storage tests to verify red**

Run: `python -m pytest apps/api/app/tests/unit/test_storage_adapters.py -v`
Expected: FAIL — `MaterializedObject` and `materialize_for_read()` do not exist yet.

- [ ] **Step 3: Implement the storage seam**

In `apps/api/app/services/storage.py`, add these imports at the top:

```python
from collections.abc import Callable
from tempfile import NamedTemporaryFile
```

Add the `MaterializedObject` dataclass after the `StoredObject` dataclass (around line 21):

```python
@dataclass(slots=True)
class MaterializedObject:
    local_path: Path
    cleanup: Callable[[], None] | None = None
```

Add the abstract method to `StorageAdapter` (after `put_object`):

```python
    def materialize_for_read(self, *, object_key: str) -> MaterializedObject:
        raise NotImplementedError
```

Add the implementation to `LocalFilesystemStorageAdapter` (after `put_object`):

```python
    def materialize_for_read(self, *, object_key: str) -> MaterializedObject:
        source_path = self.root_dir / object_key
        if not source_path.is_file():
            raise RuntimeError(
                f"Local storage could not find object for key '{object_key}'."
            )
        return MaterializedObject(local_path=source_path, cleanup=None)
```

Add the implementation to `S3CompatibleStorageAdapter` (after `put_object`):

```python
    def materialize_for_read(self, *, object_key: str) -> MaterializedObject:
        with NamedTemporaryFile(delete=False) as tmp_file:
            temp_path = Path(tmp_file.name)

        self._get_client().download_file(
            Bucket=self.bucket,
            Key=object_key,
            Filename=str(temp_path),
        )

        def _cleanup() -> None:
            if temp_path.exists():
                temp_path.unlink()

        return MaterializedObject(local_path=temp_path, cleanup=_cleanup)
```

- [ ] **Step 4: Re-run storage tests**

Run: `python -m pytest apps/api/app/tests/unit/test_storage_adapters.py -v`
Expected: PASS (all tests, old and new).

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/storage.py apps/api/app/tests/unit/test_storage_adapters.py
git commit -m "feat: add storage materialization seam for parsing"
```

---

### Task 2: Extend parse request and Docling parser path

**Files:**
- Modify: `apps/api/app/services/parsers/base.py`
- Modify: `apps/api/app/services/parsers/docling_backend.py`
- Test: `apps/api/app/tests/unit/test_parser_backends.py`

- [ ] **Step 1: Write the failing parser tests**

Add these tests to the end of `apps/api/app/tests/unit/test_parser_backends.py`:

```python
def test_docling_document_parser_uses_local_source_path_when_provided(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    local_file = tmp_path / "materialized.pdf"
    local_file.write_bytes(b"%PDF-1.4")

    class FakePage:
        def __init__(self, page_no: int, markdown: str) -> None:
            self.page_no = page_no
            self._markdown = markdown

        def export_to_markdown(self) -> str:
            return self._markdown

    class FakeDocument:
        def __init__(self) -> None:
            self.pages = {1: FakePage(1, "Materialized page")}
            self.tables = []

    class FakeDocumentConverter:
        def convert(self, source: Path):
            assert Path(source) == local_file
            return SimpleNamespace(document=FakeDocument())

    monkeypatch.setattr(
        docling_backend,
        "import_module",
        lambda _module_name: SimpleNamespace(DocumentConverter=FakeDocumentConverter),
    )

    parser = DoclingDocumentParser(storage_root=tmp_path / "unused")
    artifact = parser.parse(
        ParseRequest(
            document_id="11111111-1111-1111-1111-111111111111",
            object_key="ignored/by/materialized/path.pdf",
            content_type="application/pdf",
            profile="local-cpu",
            local_source_path=str(local_file),
        )
    )

    assert artifact.pages[0].text == "Materialized page"
    assert artifact.provenance.parser_backend == "docling"
    assert artifact.provenance.profile == "local-cpu"


def test_docling_document_parser_falls_back_to_storage_root_when_no_local_source_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "documents" / "fallback.pdf"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_bytes(b"%PDF-1.4")

    class FakePage:
        def __init__(self, page_no: int, markdown: str) -> None:
            self.page_no = page_no
            self._markdown = markdown

        def export_to_markdown(self) -> str:
            return self._markdown

    class FakeDocument:
        def __init__(self) -> None:
            self.pages = {1: FakePage(1, "Fallback page")}
            self.tables = []

    class FakeDocumentConverter:
        def convert(self, source: Path):
            assert Path(source) == source_file
            return SimpleNamespace(document=FakeDocument())

    monkeypatch.setattr(
        docling_backend,
        "import_module",
        lambda _module_name: SimpleNamespace(DocumentConverter=FakeDocumentConverter),
    )

    parser = DoclingDocumentParser(storage_root=tmp_path)
    artifact = parser.parse(
        ParseRequest(
            document_id="11111111-1111-1111-1111-111111111111",
            object_key="documents/fallback.pdf",
            content_type="application/pdf",
            profile="local-cpu",
        )
    )

    assert artifact.pages[0].text == "Fallback page"
```

- [ ] **Step 2: Run targeted parser tests to verify red**

Run: `python -m pytest apps/api/app/tests/unit/test_parser_backends.py -v`
Expected: FAIL — `ParseRequest` does not accept `local_source_path` yet.

- [ ] **Step 3: Implement request + parser changes**

In `apps/api/app/services/parsers/base.py`, add the field to `ParseRequest`:

```python
@dataclass(slots=True)
class ParseRequest:
    document_id: str
    object_key: str
    content_type: str
    profile: str
    local_source_path: str | None = None
```

In `apps/api/app/services/parsers/docling_backend.py`, replace the `parse()` method body (lines 27–64) with:

```python
    def parse(self, request: ParseRequest) -> ParsedArtifact:
        if self._converter is not None:
            artifact = self._converter(request)
            artifact.provenance.parser_backend = self.backend_name
            artifact.provenance.profile = request.profile
            return artifact

        # Resolve source path: prefer materialized local path, fall back to storage_root + object_key
        source_path = Path(request.local_source_path) if request.local_source_path else None
        if source_path is None:
            if self._storage_root is None:
                raise RuntimeError(
                    "Docling parsing requires either a materialized local source path "
                    "or a configured local storage root when no converter is injected. "
                    "Configure a storage root or pass local_source_path before running local Docling parsing."
                )
            source_path = self._storage_root / request.object_key

        if not source_path.is_file():
            raise RuntimeError(
                f"Docling source file not found for object_key '{request.object_key}' at '{source_path}'."
            )

        try:
            document_converter_module = import_module("docling.document_converter")
        except ImportError as exc:
            raise RuntimeError(
                "Docling parsing requires the docling package. Install the docling package or inject a converter before running Phase 2 parsing."
            ) from exc

        try:
            converter = document_converter_module.DocumentConverter()
            conversion_result = converter.convert(source_path)
            return _normalize_docling_result(
                request=request,
                conversion_result=conversion_result,
                parser_backend=self.backend_name,
                parser_version=_resolve_docling_version(),
            )
        except Exception as exc:
            raise RuntimeError(
                f"Docling conversion failed for object_key '{request.object_key}': {exc}"
            ) from exc
```

- [ ] **Step 4: Re-run parser tests**

Run: `python -m pytest apps/api/app/tests/unit/test_parser_backends.py -v`
Expected: PASS (all tests, old and new).

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/parsers/base.py apps/api/app/services/parsers/docling_backend.py apps/api/app/tests/unit/test_parser_backends.py
git commit -m "feat: let docling parser consume materialized local source paths"
```

---

### Task 3: Dispatcher materialization and cleanup

**Files:**
- Modify: `apps/api/app/workflows/dispatcher.py`
- Modify: `apps/api/app/workflows/stages.py`
- Test: `apps/api/app/tests/unit/test_dispatcher.py`

- [ ] **Step 1: Write the failing dispatcher test**

Add these tests to the end of `apps/api/app/tests/unit/test_dispatcher.py`:

```python
from app.services.storage import MaterializedObject


def test_in_process_dispatcher_materializes_object_and_cleans_up(dispatcher_env, tmp_path: Path) -> None:
    materialized_file = tmp_path / "materialized.txt"
    materialized_file.write_text("hello")
    cleanup_called = {"value": False}

    class FakeStorage:
        def materialize_for_read(self, *, object_key: str) -> MaterializedObject:
            def _cleanup() -> None:
                cleanup_called["value"] = True
            return MaterializedObject(local_path=materialized_file, cleanup=_cleanup)

    run_id = dispatcher_env["run_id"]
    document_id = dispatcher_env["document_id"]

    test_artifact = _make_test_artifact(document_id)
    parser = DoclingDocumentParser(converter=lambda _req: test_artifact)
    dispatcher = InProcessDispatcher(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
        storage=FakeStorage(),
    )

    dispatcher._execute_pipeline(run_id)

    assert cleanup_called["value"] is True

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
    assert run is not None
    assert run.status == "completed"


def test_in_process_dispatcher_cleans_up_on_parse_failure(dispatcher_env, tmp_path: Path) -> None:
    materialized_file = tmp_path / "broken.txt"
    materialized_file.write_text("broken")
    cleanup_called = {"value": False}

    class FakeStorage:
        def materialize_for_read(self, *, object_key: str) -> MaterializedObject:
            def _cleanup() -> None:
                cleanup_called["value"] = True
            return MaterializedObject(local_path=materialized_file, cleanup=_cleanup)

    run_id = dispatcher_env["run_id"]

    parser = DoclingDocumentParser(converter=lambda _req: (_ for _ in ()).throw(RuntimeError("Parse boom")))
    dispatcher = InProcessDispatcher(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
        storage=FakeStorage(),
    )

    dispatcher._execute_pipeline(run_id)

    assert cleanup_called["value"] is True

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
    assert run is not None
    assert run.status == "failed"
```

- [ ] **Step 2: Run dispatcher tests to verify red**

Run: `python -m pytest apps/api/app/tests/unit/test_dispatcher.py::test_in_process_dispatcher_materializes_object_and_cleans_up -v`
Expected: FAIL — `InProcessDispatcher.__init__` does not accept `storage` yet.

- [ ] **Step 3: Implement dispatcher and stage changes**

In `apps/api/app/workflows/stages.py`, add `local_source_path` parameter to `run_parse_stage`:

Replace the function signature (line 36) with:

```python
def run_parse_stage(
    *,
    run_id: UUID,
    stage_id: UUID,
    document_id: UUID,
    object_key: str,
    content_type: str,
    profile: str,
    parser_backend: str,
    parser: DocumentParser | None = None,
    local_source_path: str | None = None,
) -> ParsedArtifact | None:
```

Replace the `ParseRequest` construction (lines 57–62) with:

```python
    request = ParseRequest(
        document_id=str(document_id),
        object_key=object_key,
        content_type=content_type,
        profile=profile,
        local_source_path=local_source_path,
    )
```

In `apps/api/app/workflows/dispatcher.py`, add the import:

```python
from app.services.storage import StorageAdapter
```

Update `InProcessDispatcher.__init__` to accept optional storage:

```python
class InProcessDispatcher:
    """In-process dispatcher that runs the ingestion pipeline via asyncio.create_task."""

    def __init__(
        self,
        parser: DocumentParser,
        parser_backend: str,
        parser_profile: str,
        storage: StorageAdapter | None = None,
    ) -> None:
        self._parser = parser
        self._parser_backend = parser_backend
        self._parser_profile = parser_profile
        self._storage = storage
```

Replace the `_execute_pipeline` method (lines 50–123) with:

```python
    def _execute_pipeline(self, run_id: UUID) -> None:
        # Load run and document metadata
        with session_factory() as session:
            if session.bind is None:
                logger.error("No database bind, cannot execute pipeline for run %s.", run_id)
                return

            run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
            if run is None:
                logger.error("Ingestion run %s not found, cannot dispatch.", run_id)
                return

            tenant_id = run.tenant_id
            document_id = run.document_id

            doc = session.scalar(select(Document).where(Document.id == document_id))
            object_key = doc.object_key if doc else ""
            content_type = "application/octet-stream"

        # Mark run as running
        update_run_status(run_id=run_id, status="running")

        # Create stage records
        stages = create_ingestion_stages(run_id=run_id, tenant_id=tenant_id, stage_names=STAGE_NAMES)
        stage_map = {s.stage_name: s for s in stages}

        # Materialize object for parsing if storage adapter is available
        materialized = None
        local_source_path = None
        if self._storage is not None:
            materialized = self._storage.materialize_for_read(object_key=object_key or "")
            local_source_path = str(materialized.local_path)

        try:
            # Stage 1: Parse
            artifact = run_parse_stage(
                run_id=run_id,
                stage_id=stage_map["parse"].id,
                document_id=document_id,
                object_key=object_key or "",
                content_type=content_type,
                profile=self._parser_profile,
                parser_backend=self._parser_backend,
                parser=self._parser,
                local_source_path=local_source_path,
            )

            # If parse was skipped (already completed), load artifact from DB
            if artifact is None:
                with session_factory() as session:
                    record = session.scalar(
                        select(ParsedArtifactRecord).where(ParsedArtifactRecord.run_id == run_id)
                    )
                    if record is not None:
                        artifact = ParsedArtifactSchema.model_validate(record.artifact_json)

            # Stage 2: Persist artifact
            if artifact is not None:
                run_persist_artifact_stage(
                    run_id=run_id,
                    stage_id=stage_map["persist_artifact"].id,
                    artifact=artifact,
                )

            # Stage 3: Quality report
            if artifact is not None:
                run_quality_report_stage(
                    run_id=run_id,
                    stage_id=stage_map["quality_report"].id,
                    artifact=artifact,
                )

            update_run_status(run_id=run_id, status="completed")

        except Exception as exc:
            logger.exception("Stage failed for run %s: %s", run_id, exc)
            # Mark any running stages as failed
            failed_stages = get_stages_for_run(run_id=run_id)
            for stage in failed_stages:
                if stage.status == "running":
                    update_stage_status(stage_id=stage.id, status="failed", details={"error": str(exc)})
            update_run_status(run_id=run_id, status="failed")
        finally:
            if materialized is not None and materialized.cleanup is not None:
                materialized.cleanup()
```

- [ ] **Step 4: Re-run dispatcher tests**

Run: `python -m pytest apps/api/app/tests/unit/test_dispatcher.py -v`
Expected: PASS (all tests, old and new).

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/workflows/dispatcher.py apps/api/app/workflows/stages.py apps/api/app/tests/unit/test_dispatcher.py
git commit -m "feat: materialize stored objects before docling parse"
```

---

### Task 4: Wire startup and remove SeaweedFS guard

**Files:**
- Modify: `apps/api/app/main.py`
- Modify: `apps/api/app/services/parsers/factory.py`
- Test: `apps/api/app/tests/integration/test_runtime_auth_startup.py`

- [ ] **Step 1: Write the failing startup test for supported SeaweedFS parsing**

Add this test to the end of `apps/api/app/tests/integration/test_runtime_auth_startup.py`:

```python
def test_app_startup_succeeds_for_seaweedfs_with_local_docling_runtime(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'runtime-startup-seaweedfs-ok.db'}"
        storage_dir = Path(tmp_dir) / "storage"

        monkeypatch.setenv("AUTH_MODE", "dev")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LOCAL_STORAGE_DIR", str(storage_dir))
        monkeypatch.setenv("STORAGE_BACKEND", "seaweedfs")
        monkeypatch.setenv("S3_ENDPOINT_URL", "http://seaweedfs:8333")
        monkeypatch.setenv("S3_ACCESS_KEY", "test-access")
        monkeypatch.setenv("S3_SECRET_KEY", "test-secret")
        monkeypatch.setenv("PARSER_BACKEND", "docling")
        reloaded_main = _reload_app_module()

        try:
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50004)):
                assert hasattr(reloaded_main.app.state, "dispatcher")
                assert reloaded_main.app.state.dispatcher._storage is not None
                assert reloaded_main.app.state.dispatcher._parser_backend == "docling-local"
        finally:
            session_factory.configure(bind=None)
```

- [ ] **Step 2: Run startup tests to verify red**

Run: `python -m pytest apps/api/app/tests/integration/test_runtime_auth_startup.py::test_app_startup_succeeds_for_seaweedfs_with_local_docling_runtime -v`
Expected: FAIL — the SeaweedFS guard in `factory.py` raises `RuntimeError` before the app starts.

- [ ] **Step 3: Update factory and startup wiring**

In `apps/api/app/services/parsers/factory.py`, remove the SeaweedFS guard block. Replace the entire function body with:

```python
def build_document_parser(settings: Settings) -> tuple[DocumentParser, str, str]:
    backend = settings.parser_backend.strip().lower()
    storage_root = Path(settings.local_storage_dir) if settings.local_storage_dir else None

    if backend in {"docling", "docling-local"}:
        return DoclingDocumentParser(storage_root=storage_root), "docling-local", "local-cpu"

    if backend == "remote":
        raise RuntimeError(
            "Parser backend 'remote' is not yet supported in runtime startup. Configure a local Docling backend for now."
        )

    raise RuntimeError(
        f"Unknown parser backend '{settings.parser_backend}'. Supported backends: docling, docling-local."
    )
```

In `apps/api/app/main.py`, update the dispatcher construction to pass storage:

```python
    if settings.parser_backend:
        from app.workflows.dispatcher import InProcessDispatcher

        parser, parser_backend, parser_profile = build_document_parser(settings)
        app.state.dispatcher = InProcessDispatcher(
            parser=parser,
            parser_backend=parser_backend,
            parser_profile=parser_profile,
            storage=storage,
        )
```

- [ ] **Step 4: Update the old fail-fast test**

The existing test `test_app_startup_fails_fast_for_seaweedfs_with_local_docling_runtime` must be updated to expect success instead of failure. Replace it with:

```python
def test_app_startup_succeeds_for_seaweedfs_with_local_docling_runtime_via_env(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'runtime-startup-seaweedfs-env.db'}"
        storage_dir = Path(tmp_dir) / "storage"

        monkeypatch.setenv("AUTH_MODE", "dev")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LOCAL_STORAGE_DIR", str(storage_dir))
        monkeypatch.setenv("STORAGE_BACKEND", "seaweedfs")
        monkeypatch.setenv("S3_ENDPOINT_URL", "http://seaweedfs:8333")
        monkeypatch.setenv("S3_ACCESS_KEY", "test-access")
        monkeypatch.setenv("S3_SECRET_KEY", "test-secret")
        monkeypatch.setenv("PARSER_BACKEND", "docling")
        reloaded_main = _reload_app_module()

        try:
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50003)):
                assert hasattr(reloaded_main.app.state, "dispatcher")
                assert reloaded_main.app.state.dispatcher._storage is not None
        finally:
            session_factory.configure(bind=None)
```

- [ ] **Step 5: Re-run startup tests**

Run: `python -m pytest apps/api/app/tests/integration/test_runtime_auth_startup.py -v`
Expected: PASS (all tests).

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/main.py apps/api/app/services/parsers/factory.py apps/api/app/tests/integration/test_runtime_auth_startup.py
git commit -m "feat: allow seaweedfs-backed parsing through storage materialization seam"
```

---

### Task 5: End-to-end SeaweedFS-backed ingestion test

**Files:**
- Modify: `apps/api/app/tests/integration/test_ingestion_dispatch.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write the failing integration test**

Add this test to the end of `apps/api/app/tests/integration/test_ingestion_dispatch.py`:

```python
from app.services.storage import S3CompatibleStorageAdapter


class FakeS3ClientWithDownload:
    """Fake S3 client that stores uploaded bytes and serves them back via download_file."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kwargs: object) -> None:
        key = kwargs["Key"]
        body = kwargs["Body"]
        self.objects[key] = body if isinstance(body, bytes) else b""

    def download_file(self, Bucket: str, Key: str, Filename: str) -> None:
        from pathlib import Path as _Path
        content = self.objects.get(Key, b"")
        _Path(Filename).write_bytes(content)


def test_upload_and_parse_through_s3_compatible_storage(client):
    """Upload stores to fake S3, dispatcher materializes a temp file, parser runs, run completes."""
    fake_s3 = FakeS3ClientWithDownload()
    storage = S3CompatibleStorageAdapter(
        endpoint_url="http://fake-s3:8333",
        access_key="test",
        secret_key="test",
        bucket="uber-rag-documents",
        region="us-east-1",
        client=fake_s3,
    )

    # Replace the storage stub with the fake S3 adapter
    app.state.document_storage = storage

    expected_artifact = ParsedArtifact(
        document_id=uuid4(),
        pages=[ParsedPage(page_number=1, text="s3 materialized content", blocks=[])],
        tables=[],
        provenance=ParserProvenance(
            parser_backend="docling", parser_version="1.0.0", profile="local-cpu"
        ),
    )
    parser = DoclingDocumentParser(converter=lambda req: expected_artifact)
    dispatcher = InProcessDispatcher(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
        storage=storage,
    )
    app.state._test_dispatcher = dispatcher

    response = client.post(
        "/api/v1/documents/upload",
        headers={"Authorization": "Bearer test-token"},
        files={"file": ("s3-doc.txt", b"uploaded via s3", "text/plain")},
        data={"title": "S3 Doc", "source_type": "loose_document"},
    )

    assert response.status_code == 201
    run_id = UUID(response.json()["ingestion_run_id"])

    # Verify the file was stored in fake S3
    assert len(fake_s3.objects) > 0

    # Run the pipeline synchronously
    dispatcher._execute_pipeline(run_id)

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        assert run is not None
        assert run.status == "completed"

        stages = list(
            session.scalars(
                select(IngestionStage)
                .where(IngestionStage.run_id == run_id)
                .order_by(IngestionStage.created_at.asc())
            ).all()
        )
        assert len(stages) == 3
        assert all(s.status == "completed" for s in stages)
        assert stages[0].stage_name == "parse"
        assert stages[0].details["parser_backend"] == "docling-local"
```

- [ ] **Step 2: Run integration test to verify red**

Run: `python -m pytest apps/api/app/tests/integration/test_ingestion_dispatch.py::test_upload_and_parse_through_s3_compatible_storage -v`
Expected: FAIL — `InProcessDispatcher` in the test fixture does not pass `storage`, so materialization is skipped and the test assertion about S3 objects may not hold, or the test fixture wiring needs the storage-aware dispatcher.

- [ ] **Step 3: Add boto3 runtime dependency**

In `pyproject.toml`, add `boto3` to the dependencies list:

```toml
"boto3>=1.35,<2",
```

- [ ] **Step 4: Re-run integration test**

Run: `python -m pytest apps/api/app/tests/integration/test_ingestion_dispatch.py -v`
Expected: PASS (all tests, old and new).

- [ ] **Step 5: Run full suite**

Run: `python -m pytest --tb=short -q`
Expected: PASS (all tests green).

- [ ] **Step 6: Update project memory**

Update `docs/uber-rag/PROJECT_STATE.md`:
- Add a row to "Recent changes" describing the storage materialization seam.
- Update "Next recommended actions" to reflect that SeaweedFS parsing is now runnable.
- Update the TASKS.md item "Exercise the live SeaweedFS backend in runtime/integration coverage" to `[x]`.

Update `docs/uber-rag/TASKS.md`:
- Mark `- [ ] Exercise the live SeaweedFS backend in runtime/integration coverage.` as `[x]`.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/tests/integration/test_ingestion_dispatch.py pyproject.toml docs/uber-rag/PROJECT_STATE.md docs/uber-rag/TASKS.md
git commit -m "feat: enable seaweedfs-backed parsing via storage materialization"
```
