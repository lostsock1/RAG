# Storage/Parser Compatibility Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fail fast at startup when object storage and parser runtime are configured in a combination that cannot work end-to-end.

**Architecture:** Keep the guard inside `apps/api/app/services/parsers/factory.py`, where backend resolution already lives. Add factory and startup tests first, then implement the minimal runtime error for the SeaweedFS + local Docling combination.

**Tech Stack:** Python, parser factory, FastAPI startup wiring, pytest.

---

## File Structure

| Action | File | Responsibility |
|---|---|---|
| Modify | `apps/api/app/services/parsers/factory.py` | Add compatibility guard |
| Modify | `apps/api/app/tests/unit/test_parser_backends.py` | Add factory guard tests |
| Modify | `apps/api/app/tests/integration/test_runtime_auth_startup.py` | Add startup failure coverage |

### Task 1: Factory-level compatibility guard

**Files:**
- Modify: `apps/api/app/tests/unit/test_parser_backends.py`
- Modify: `apps/api/app/services/parsers/factory.py`

- [ ] **Step 1: Write the failing tests**

Add:

```python
def test_build_document_parser_rejects_seaweedfs_with_local_docling(tmp_path: Path):
    settings = Settings(
        parser_backend="docling",
        storage_backend="seaweedfs",
        local_storage_dir=str(tmp_path),
        s3_endpoint_url="http://seaweedfs:8333",
        s3_access_key="test-access",
        s3_secret_key="test-secret",
    )

    with pytest.raises(RuntimeError, match="SeaweedFS"):
        build_document_parser(settings)
```

- [ ] **Step 2: Run targeted parser backend tests to verify red**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/unit/test_parser_backends.py -v`
Expected: FAIL because factory currently resolves `docling` regardless of storage backend.

- [ ] **Step 3: Implement minimal guard**

In `apps/api/app/services/parsers/factory.py`, before returning local Docling for `docling` / `docling-local`, add:

```python
    if backend in {"docling", "docling-local"}:
        if settings.storage_backend == "seaweedfs":
            raise RuntimeError(
                "SeaweedFS object storage is not yet compatible with the local Docling parser runtime. "
                "The current parser expects uploaded files to be readable from local disk. "
                "Use local storage for now, or implement a remote object-read parsing path first."
            )
        return DoclingDocumentParser(storage_root=storage_root), "docling-local", "local-cpu"
```

- [ ] **Step 4: Re-run targeted parser backend tests**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/unit/test_parser_backends.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/parsers/factory.py apps/api/app/tests/unit/test_parser_backends.py
git commit -m "feat: reject incompatible seaweedfs local-docling configuration"
```

### Task 2: Startup failure coverage

**Files:**
- Modify: `apps/api/app/tests/integration/test_runtime_auth_startup.py`

- [ ] **Step 1: Write the failing startup test**

Add:

```python
def test_app_startup_rejects_seaweedfs_with_local_docling_parser(monkeypatch) -> None:
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'runtime-seaweedfs-guard.db'}"
        monkeypatch.setenv("AUTH_MODE", "dev")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LOCAL_STORAGE_DIR", str(Path(tmp_dir) / "storage"))
        monkeypatch.setenv("STORAGE_BACKEND", "seaweedfs")
        monkeypatch.setenv("S3_ENDPOINT_URL", "http://seaweedfs:8333")
        monkeypatch.setenv("S3_ACCESS_KEY", "test-access")
        monkeypatch.setenv("S3_SECRET_KEY", "test-secret")
        monkeypatch.setenv("PARSER_BACKEND", "docling")

        reloaded_main = _reload_app_module()

        with pytest.raises(RuntimeError, match="SeaweedFS object storage is not yet compatible"):
            with TestClient(reloaded_main.app, client=("127.0.0.1", 50003)):
                pass
```

- [ ] **Step 2: Run targeted startup tests to verify red**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/integration/test_runtime_auth_startup.py -v`
Expected: FAIL until the factory guard is active in startup.

- [ ] **Step 3: Re-run startup tests after Task 1 code**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/integration/test_runtime_auth_startup.py -v`
Expected: PASS if startup surfaces the same error cleanly.

- [ ] **Step 4: Run full suite**

Run: `cd /djesys/code/RAG && python -m pytest --tb=short -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/tests/integration/test_runtime_auth_startup.py
git commit -m "test: cover startup rejection for seaweedfs local-docling mismatch"
```
