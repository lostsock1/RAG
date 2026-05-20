# SeaweedFS Runtime Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exercise the SeaweedFS/S3-compatible runtime path through the upload API and adapter seam.

**Architecture:** Keep production changes minimal or zero. Add targeted unit and integration tests that run the existing `S3CompatibleStorageAdapter` through a fake S3 client so the suite proves runtime behavior without depending on a live SeaweedFS daemon.

**Tech Stack:** Python, pytest, FastAPI TestClient, existing S3-compatible storage adapter.

---

## File Structure

| Action | File | Responsibility |
|---|---|---|
| Modify | `apps/api/app/tests/unit/test_storage_adapters.py` | Add direct S3 put-object contract test |
| Modify | `apps/api/app/tests/integration/test_documents_upload.py` | Add upload tests using S3-compatible adapter with fake client |

### Task 1: Unit coverage for S3-compatible put_object

**Files:**
- Modify: `apps/api/app/tests/unit/test_storage_adapters.py`

- [ ] **Step 1: Write the failing test**

Add:

```python
def test_s3_compatible_storage_adapter_put_object_forwards_expected_payload() -> None:
    calls: list[dict] = []

    class FakeClient:
        def put_object(self, **kwargs):
            calls.append(kwargs)

    adapter = S3CompatibleStorageAdapter(
        endpoint_url="http://seaweedfs:8333",
        access_key="test-access",
        secret_key="test-secret",
        bucket="uber-rag-documents",
        region="us-east-1",
        client=FakeClient(),
    )

    adapter.put_object(
        object_key="documents/tenant-1/sample.txt",
        content=b"hello world",
        content_type="text/plain",
    )

    assert calls == [
        {
            "Bucket": "uber-rag-documents",
            "Key": "documents/tenant-1/sample.txt",
            "Body": b"hello world",
            "ContentType": "text/plain",
        }
    ]
```

- [ ] **Step 2: Run test to verify it fails or is absent**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/unit/test_storage_adapters.py -v`
Expected: FAIL or missing-test state before implementation.

- [ ] **Step 3: Add minimal production changes only if required**

If the test fails, adjust production code only as needed. Otherwise leave `apps/api/app/services/storage.py` unchanged.

- [ ] **Step 4: Run unit storage tests**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/unit/test_storage_adapters.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/tests/unit/test_storage_adapters.py
git commit -m "test: add S3-compatible storage payload coverage"
```

### Task 2: Upload API coverage through S3-compatible adapter

**Files:**
- Modify: `apps/api/app/tests/integration/test_documents_upload.py`

- [ ] **Step 1: Write the failing integration tests**

Add a fake S3 client and adapter-backed client fixture, then add:

```python
def test_upload_uses_s3_compatible_storage_adapter_when_configured(
    seaweedfs_client: TestClient,
    auth_headers: dict[str, str],
    s3_calls: list[dict],
) -> None:
    response = seaweedfs_client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert len(s3_calls) == 1
    assert s3_calls[0]["Bucket"] == "uber-rag-documents"
    assert s3_calls[0]["Key"] == payload["object_key"]
    assert s3_calls[0]["Body"] == b"hello world"
    assert s3_calls[0]["ContentType"] == "text/plain"

    with session_factory() as session:
        document = session.scalar(select(Document).where(Document.id == UUID(payload["id"])))
        assert document is not None
        assert document.object_key == payload["object_key"]


def test_upload_reuses_same_object_key_with_s3_compatible_storage(
    seaweedfs_client: TestClient,
    auth_headers: dict[str, str],
    s3_calls: list[dict],
) -> None:
    first = seaweedfs_client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )
    second = seaweedfs_client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample-copy.txt", b"hello world", "text/plain")},
        data={"title": "Sample copy", "source_type": "loose_document"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    first_payload = first.json()
    second_payload = second.json()
    assert second_payload["object_key"] == first_payload["object_key"]
    assert len(s3_calls) == 1
```

- [ ] **Step 2: Run the integration file to verify red**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/integration/test_documents_upload.py -v`
Expected: FAIL until SeaweedFS-style test fixture/setup is added.

- [ ] **Step 3: Implement fake-client-backed fixture**

In `test_documents_upload.py`, add:

```python
class FakeS3Client:
    def __init__(self, calls: list[dict]) -> None:
        self._calls = calls

    def put_object(self, **kwargs) -> None:
        self._calls.append(kwargs)
```

and a fixture:

```python
@pytest.fixture()
def s3_calls() -> list[dict]:
    return []


@pytest.fixture()
def seaweedfs_client(auth_context: RequestContext, s3_calls: list[dict]):
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'upload-s3.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add(Tenant(id=UUID(auth_context.tenant_id), name="Tenant", slug="tenant"))
            session.add(
                User(
                    id=UUID(auth_context.user_id),
                    tenant_id=UUID(auth_context.tenant_id),
                    email="user@example.com",
                    display_name="User",
                    roles=auth_context.roles,
                )
            )
            session.commit()

        app.dependency_overrides[get_request_context] = lambda: auth_context
        app.state.document_storage = S3CompatibleStorageAdapter(
            endpoint_url="http://seaweedfs:8333",
            access_key="test-access",
            secret_key="test-secret",
            bucket="uber-rag-documents",
            region="us-east-1",
            client=FakeS3Client(s3_calls),
        )

        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.clear()
            if hasattr(app.state, "document_storage"):
                delattr(app.state, "document_storage")
            session_factory.configure(bind=None)
            engine.dispose()
```

- [ ] **Step 4: Run integration test file again**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/integration/test_documents_upload.py -v`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `cd /djesys/code/RAG && python -m pytest --tb=short -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/tests/integration/test_documents_upload.py
git commit -m "test: exercise upload runtime through S3-compatible storage adapter"
```
