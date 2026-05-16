# Phase 2 Ingestion Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the local-filesystem upload baseline with SeaweedFS-backed durable storage, add Temporal-oriented ingestion run tracking, and land a structured document-understanding foundation that persists parsed artifacts, quality reports, and provenance.

**Architecture:** Keep upload as the public API entry point, but split Phase 2 into three durable seams: object storage, ingestion workflow state, and normalized parsed artifacts. All parsing backends feed one structured artifact contract; workflow orchestration owns resumability and stage status rather than application-only retry logic.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, SeaweedFS (S3-compatible), Temporal Python SDK, Docling, pytest, httpx

---

## Planned file structure

### Modify existing

- `apps/api/app/core/config.py` — add SeaweedFS and Temporal settings.
- `apps/api/app/main.py` — wire object storage and workflow clients at app startup.
- `apps/api/app/services/storage.py` — upgrade from local-only adapter to pluggable storage adapters.
- `apps/api/app/services/document_service.py` — add dedup/run creation and stop treating upload as the whole ingestion lifecycle.
- `apps/api/app/api/routes/documents.py` — return ingestion metadata from upload.
- `apps/api/app/api/router.py` — mount ingestion routes.
- `apps/api/app/db/models/document.py` — add Phase 2 metadata fields needed by ingestion orchestration.
- `apps/api/app/db/models/__init__.py` — export new models.
- `apps/api/app/repositories/documents.py` — add dedup-aware document create/update helpers.
- `infra/migrations/versions/20260515_0001_phase1_foundation.py` — reference only; do not edit.
- `apps/api/app/tests/integration/test_documents_upload.py` — evolve upload assertions for dedup/run creation.

### Create new

- `apps/api/app/db/models/ingestion.py` — `IngestionRun`, `IngestionStage`, `ParsedArtifact`, `QualityReport`.
- `apps/api/app/repositories/ingestion.py` — persistence helpers for runs/stages/artifacts.
- `apps/api/app/schemas/ingestion.py` — public API response models.
- `apps/api/app/schemas/parsed_artifacts.py` — normalized structured artifact contract.
- `apps/api/app/api/routes/ingestion.py` — run status and list endpoints.
- `apps/api/app/services/parsers/base.py` — parser/document-understanding interface.
- `apps/api/app/services/parsers/docling_backend.py` — Docling implementation.
- `apps/api/app/services/parsers/remote_backend.py` — remote document-understanding adapter stub.
- `apps/api/app/services/quality_report.py` — artifact-derived quality summary.
- `apps/api/app/services/ingestion_service.py` — upload-to-run orchestration entrypoint.
- `apps/api/app/services/temporal_runtime.py` — Temporal client/bootstrap helpers.
- `apps/api/app/workflows/ingestion_workflow.py` — workflow and activities.
- `infra/migrations/versions/20260516_0002_phase2_ingestion_foundation.py` — Phase 2 schema migration.
- `apps/api/app/tests/unit/test_storage_adapters.py`
- `apps/api/app/tests/unit/test_parsed_artifact_schema.py`
- `apps/api/app/tests/unit/test_quality_report.py`
- `apps/api/app/tests/unit/test_ingestion_repository.py`
- `apps/api/app/tests/integration/test_ingestion_jobs.py`
- `apps/api/app/tests/integration/test_docling_parser_adapter.py`

---

### Task 1: Replace local-only storage with SeaweedFS-ready object storage

**Files:**
- Modify: `apps/api/app/core/config.py`
- Modify: `apps/api/app/services/storage.py`
- Modify: `apps/api/app/main.py`
- Test: `apps/api/app/tests/unit/test_storage_adapters.py`

- [ ] **Step 1: Write failing unit tests for config-driven storage adapter selection**

```python
from pathlib import Path

from app.core.config import Settings
from app.services.storage import LocalFilesystemStorageAdapter, S3CompatibleStorageAdapter, build_storage_adapter


def test_build_storage_adapter_uses_local_filesystem_when_local_dir_present(tmp_path: Path) -> None:
    settings = Settings(local_storage_dir=str(tmp_path), storage_backend="local")

    adapter = build_storage_adapter(settings)

    assert isinstance(adapter, LocalFilesystemStorageAdapter)


def test_build_storage_adapter_uses_s3_compatible_backend_when_seaweedfs_selected() -> None:
    settings = Settings(
        storage_backend="seaweedfs",
        s3_endpoint_url="http://seaweedfs:8333",
        s3_access_key="test-access",
        s3_secret_key="test-secret",
        s3_bucket="uber-rag-documents",
    )

    adapter = build_storage_adapter(settings)

    assert isinstance(adapter, S3CompatibleStorageAdapter)
```

- [ ] **Step 2: Run the new unit test file to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_storage_adapters.py -v`
Expected: FAIL with missing `build_storage_adapter`, missing S3 settings, and missing `S3CompatibleStorageAdapter`.

- [ ] **Step 3: Add storage settings and pluggable storage adapter implementation**

```python
# apps/api/app/core/config.py
from typing import Literal


class Settings(BaseSettings):
    storage_backend: Literal["local", "seaweedfs"] = "local"
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str = "uber-rag-documents"
    s3_region: str = "us-east-1"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "uber-rag-ingestion"
    temporal_host_port: str | None = None
```

```python
# apps/api/app/services/storage.py
from dataclasses import dataclass
from pathlib import Path

import boto3

from app.core.config import Settings


class StorageAdapter:
    def put_object(self, *, object_key: str, content: bytes, content_type: str) -> None:
        raise NotImplementedError


class S3CompatibleStorageAdapter(StorageAdapter):
    def __init__(self, *, endpoint_url: str, access_key: str, secret_key: str, bucket: str, region: str) -> None:
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

    def put_object(self, *, object_key: str, content: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=object_key, Body=content, ContentType=content_type)


def build_storage_adapter(settings: Settings) -> StorageAdapter | None:
    if settings.storage_backend == "local" and settings.local_storage_dir:
        return LocalFilesystemStorageAdapter(Path(settings.local_storage_dir))
    if settings.storage_backend == "seaweedfs" and settings.s3_endpoint_url and settings.s3_access_key and settings.s3_secret_key:
        return S3CompatibleStorageAdapter(
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket,
            region=settings.s3_region,
        )
    return None
```

```python
# apps/api/app/main.py
from app.services.storage import build_storage_adapter


storage = build_storage_adapter(settings)
if storage is not None:
    app.state.document_storage = storage
```

- [ ] **Step 4: Run the unit tests again**

Run: `pytest apps/api/app/tests/unit/test_storage_adapters.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/core/config.py apps/api/app/services/storage.py apps/api/app/main.py apps/api/app/tests/unit/test_storage_adapters.py
git commit -m "feat: add SeaweedFS-ready storage adapter seam"
```

### Task 2: Add ingestion run/stage and artifact schema foundation

**Files:**
- Create: `apps/api/app/db/models/ingestion.py`
- Modify: `apps/api/app/db/models/__init__.py`
- Modify: `apps/api/app/db/models/document.py`
- Create: `infra/migrations/versions/20260516_0002_phase2_ingestion_foundation.py`
- Test: `apps/api/app/tests/integration/test_migrations.py`

- [ ] **Step 1: Write a failing migration/integration test for the new Phase 2 tables**

```python
from sqlalchemy import inspect


def test_phase2_ingestion_tables_exist(engine) -> None:
    tables = set(inspect(engine).get_table_names())

    assert "ingestion_runs" in tables
    assert "ingestion_stages" in tables
    assert "parsed_artifacts" in tables
    assert "quality_reports" in tables
```

- [ ] **Step 2: Run the migration test to verify it fails**

Run: `pytest apps/api/app/tests/integration/test_migrations.py -v`
Expected: FAIL because the new tables do not exist.

- [ ] **Step 3: Add SQLAlchemy models and Alembic migration**

```python
# apps/api/app/db/models/ingestion.py
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, json_type


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(length=32), nullable=False, default="queued", server_default="queued")
    workflow_backend: Mapped[str] = mapped_column(String(length=32), nullable=False, default="temporal", server_default="temporal")
    parser_backend: Mapped[str] = mapped_column(String(length=64), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(length=128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
```

```python
# infra/migrations/versions/20260516_0002_phase2_ingestion_foundation.py
def upgrade() -> None:
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("workflow_backend", sa.String(length=32), nullable=False, server_default="temporal"),
        sa.Column("parser_backend", sa.String(length=64), nullable=False),
        sa.Column("source_hash", sa.String(length=128), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
```

- [ ] **Step 4: Re-run the migration test**

Run: `pytest apps/api/app/tests/integration/test_migrations.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/db/models/ingestion.py apps/api/app/db/models/__init__.py apps/api/app/db/models/document.py infra/migrations/versions/20260516_0002_phase2_ingestion_foundation.py apps/api/app/tests/integration/test_migrations.py
git commit -m "feat: add ingestion run and artifact schema foundation"
```

### Task 3: Make upload dedup-aware and create ingestion runs

**Files:**
- Modify: `apps/api/app/services/document_service.py`
- Modify: `apps/api/app/repositories/documents.py`
- Create: `apps/api/app/repositories/ingestion.py`
- Modify: `apps/api/app/api/routes/documents.py`
- Create: `apps/api/app/schemas/ingestion.py`
- Test: `apps/api/app/tests/integration/test_documents_upload.py`

- [ ] **Step 1: Add a failing upload test for duplicate file hash reuse and run creation**

```python
def test_upload_reuses_existing_document_hash_and_creates_new_ingestion_run(client, auth_headers) -> None:
    first = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )
    second = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample-copy.txt", b"hello world", "text/plain")},
        data={"title": "Sample copy", "source_type": "loose_document"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["source_hash"] == first.json()["source_hash"]
    assert second.json()["ingestion_run_id"]
```

- [ ] **Step 2: Run the upload integration test to verify it fails**

Run: `pytest apps/api/app/tests/integration/test_documents_upload.py -v`
Expected: FAIL because `ingestion_run_id` is missing and dedup logic does not exist.

- [ ] **Step 3: Add dedup-aware persistence and run creation**

```python
# apps/api/app/repositories/ingestion.py
def create_ingestion_run(*, document_id: UUID, tenant_id: UUID, parser_backend: str, source_hash: str) -> IngestionRun:
    run = IngestionRun(
        document_id=document_id,
        tenant_id=tenant_id,
        parser_backend=parser_backend,
        source_hash=source_hash,
        status="queued",
        workflow_backend="temporal",
    )
    with session_factory() as session:
        session.add(run)
        session.commit()
        session.refresh(run)
        return run
```

```python
# apps/api/app/services/document_service.py
@dataclass(slots=True)
class UploadResult:
    document: Document
    ingestion_run_id: UUID


def upload_document(
    *,
    context: RequestContext,
    payload: UploadPayload,
    storage: StorageAdapter,
    parser_backend: str,
) -> UploadResult:
    source_hash = sha256(payload.content).hexdigest()
    object_key = build_object_key(tenant_id=context.tenant_id, file_name=payload.file_name)
    storage.put_object(object_key=object_key, content=payload.content, content_type=payload.content_type)
    document = get_or_create_document_by_source_hash(
        tenant_id=UUID(context.tenant_id),
        owner_user_id=UUID(context.user_id),
        title=payload.form.title,
        source_type=payload.form.source_type,
        document_type=payload.form.document_type,
        language=payload.form.language,
        source_hash=source_hash,
        file_name=payload.file_name,
        file_size_bytes=len(payload.content),
        object_key=object_key,
    )
    run = create_ingestion_run(
        document_id=document.id,
        tenant_id=UUID(context.tenant_id),
        parser_backend=parser_backend,
        source_hash=source_hash,
    )
    return UploadResult(document=document, ingestion_run_id=run.id)
```

- [ ] **Step 4: Update route/schema output and rerun upload tests**

Run: `pytest apps/api/app/tests/integration/test_documents_upload.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/document_service.py apps/api/app/repositories/documents.py apps/api/app/repositories/ingestion.py apps/api/app/api/routes/documents.py apps/api/app/schemas/ingestion.py apps/api/app/tests/integration/test_documents_upload.py
git commit -m "feat: create ingestion runs on document upload"
```

### Task 4: Land the normalized parsed-artifact contract and parser interface

**Files:**
- Create: `apps/api/app/schemas/parsed_artifacts.py`
- Create: `apps/api/app/services/parsers/base.py`
- Test: `apps/api/app/tests/unit/test_parsed_artifact_schema.py`

- [ ] **Step 1: Write a failing schema test for structured artifacts with table/layout provenance**

```python
from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParsedTable, ParserProvenance


def test_parsed_artifact_requires_pages_tables_and_provenance() -> None:
    artifact = ParsedArtifact(
        document_id="11111111-1111-1111-1111-111111111111",
        pages=[ParsedPage(page_number=1, text="Example", blocks=[])],
        tables=[ParsedTable(page_number=1, bbox=[0, 0, 100, 100], markdown="|a|b|")],
        provenance=ParserProvenance(parser_backend="docling", parser_version="2.x", profile="gpu-local"),
    )

    assert artifact.tables[0].markdown.startswith("|a|")
```

- [ ] **Step 2: Run the schema unit test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_parsed_artifact_schema.py -v`
Expected: FAIL because the schema module does not exist.

- [ ] **Step 3: Add the parsed-artifact schema and parser interface**

```python
# apps/api/app/schemas/parsed_artifacts.py
from pydantic import BaseModel, Field


class ParserProvenance(BaseModel):
    parser_backend: str
    parser_version: str
    profile: str


class ParsedTable(BaseModel):
    page_number: int
    bbox: list[float] = Field(min_length=4, max_length=4)
    markdown: str


class ParsedPage(BaseModel):
    page_number: int
    text: str
    blocks: list[dict]


class ParsedArtifact(BaseModel):
    document_id: str
    pages: list[ParsedPage]
    tables: list[ParsedTable]
    provenance: ParserProvenance
```

```python
# apps/api/app/services/parsers/base.py
from dataclasses import dataclass

from app.schemas.parsed_artifacts import ParsedArtifact


@dataclass(slots=True)
class ParseRequest:
    document_id: str
    object_key: str
    content_type: str
    profile: str


class DocumentParser:
    backend_name: str

    def parse(self, request: ParseRequest) -> ParsedArtifact:
        raise NotImplementedError
```

- [ ] **Step 4: Run the schema tests again**

Run: `pytest apps/api/app/tests/unit/test_parsed_artifact_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/schemas/parsed_artifacts.py apps/api/app/services/parsers/base.py apps/api/app/tests/unit/test_parsed_artifact_schema.py
git commit -m "feat: define normalized parsed artifact contract"
```

### Task 5: Implement Docling backend, remote backend stub, and quality report generation

**Files:**
- Create: `apps/api/app/services/parsers/docling_backend.py`
- Create: `apps/api/app/services/parsers/remote_backend.py`
- Create: `apps/api/app/services/quality_report.py`
- Test: `apps/api/app/tests/unit/test_quality_report.py`
- Test: `apps/api/app/tests/integration/test_docling_parser_adapter.py`

- [ ] **Step 1: Write failing tests for Docling-backed parsing and quality summary extraction**

```python
from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParsedTable, ParserProvenance
from app.services.quality_report import build_quality_report


def test_build_quality_report_counts_tables_and_pages() -> None:
    artifact = ParsedArtifact(
        document_id="doc-1",
        pages=[ParsedPage(page_number=1, text="hello", blocks=[]), ParsedPage(page_number=2, text="world", blocks=[])],
        tables=[ParsedTable(page_number=2, bbox=[0, 0, 1, 1], markdown="|a|b|")],
        provenance=ParserProvenance(parser_backend="docling", parser_version="2.x", profile="gpu-local"),
    )

    report = build_quality_report(artifact)

    assert report.table_count == 1
    assert report.page_count == 2
```

- [ ] **Step 2: Run the new unit/integration tests to verify they fail**

Run: `pytest apps/api/app/tests/unit/test_quality_report.py apps/api/app/tests/integration/test_docling_parser_adapter.py -v`
Expected: FAIL because the backend and report modules do not exist.

- [ ] **Step 3: Add minimal Docling backend, remote backend stub, and report builder**

```python
# apps/api/app/services/quality_report.py
from dataclasses import dataclass

from app.schemas.parsed_artifacts import ParsedArtifact


@dataclass(slots=True)
class QualityReportSummary:
    page_count: int
    table_count: int
    parser_backend: str


def build_quality_report(artifact: ParsedArtifact) -> QualityReportSummary:
    return QualityReportSummary(
        page_count=len(artifact.pages),
        table_count=len(artifact.tables),
        parser_backend=artifact.provenance.parser_backend,
    )
```

```python
# apps/api/app/services/parsers/remote_backend.py
from collections.abc import Callable


class RemoteDocumentParser(DocumentParser):
    backend_name = "remote"

    def __init__(self, invoke_remote_parser: Callable[[ParseRequest], ParsedArtifact]) -> None:
        self._invoke_remote_parser = invoke_remote_parser

    def parse(self, request: ParseRequest) -> ParsedArtifact:
        artifact = self._invoke_remote_parser(request)
        artifact.provenance.profile = request.profile
        return artifact
```

- [ ] **Step 4: Re-run parser/report tests**

Run: `pytest apps/api/app/tests/unit/test_quality_report.py apps/api/app/tests/integration/test_docling_parser_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/parsers/docling_backend.py apps/api/app/services/parsers/remote_backend.py apps/api/app/services/quality_report.py apps/api/app/tests/unit/test_quality_report.py apps/api/app/tests/integration/test_docling_parser_adapter.py
git commit -m "feat: add structured parsing backends and quality report"
```

### Task 6: Add Temporal workflow runtime and ingestion job status API

**Files:**
- Create: `apps/api/app/services/temporal_runtime.py`
- Create: `apps/api/app/workflows/ingestion_workflow.py`
- Create: `apps/api/app/services/ingestion_service.py`
- Create: `apps/api/app/api/routes/ingestion.py`
- Modify: `apps/api/app/api/router.py`
- Test: `apps/api/app/tests/integration/test_ingestion_jobs.py`

- [ ] **Step 1: Write a failing ingestion jobs API test**

```python
def test_get_ingestion_job_returns_status_payload(client, auth_headers) -> None:
    response = client.get("/api/v1/ingestion/jobs/11111111-1111-1111-1111-111111111111", headers=auth_headers)

    assert response.status_code in {200, 404}
```

- [ ] **Step 2: Run the integration test to verify it fails**

Run: `pytest apps/api/app/tests/integration/test_ingestion_jobs.py -v`
Expected: FAIL because the route does not exist.

- [ ] **Step 3: Add Temporal bootstrap, workflow skeleton, and job status route**

```python
# apps/api/app/services/temporal_runtime.py
from temporalio.client import Client


async def build_temporal_client(host_port: str, namespace: str) -> Client:
    return await Client.connect(host_port, namespace=namespace)
```

```python
# apps/api/app/workflows/ingestion_workflow.py
from temporalio import workflow


@workflow.defn
class IngestionWorkflow:
    @workflow.run
    async def run(self, ingestion_run_id: str) -> str:
        return ingestion_run_id
```

```python
# apps/api/app/api/routes/ingestion.py
@router.get("/jobs/{job_id}", response_model=IngestionJobResponse)
def get_ingestion_job(job_id: UUID, context: RequestContext = Depends(require_scopes(["documents:read"]))) -> IngestionJobResponse:
    run = get_ingestion_run_for_context(job_id=job_id, tenant_id=context.tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    return IngestionJobResponse.model_validate(run)
```

- [ ] **Step 4: Re-run the ingestion jobs test**

Run: `pytest apps/api/app/tests/integration/test_ingestion_jobs.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/temporal_runtime.py apps/api/app/workflows/ingestion_workflow.py apps/api/app/services/ingestion_service.py apps/api/app/api/routes/ingestion.py apps/api/app/api/router.py apps/api/app/tests/integration/test_ingestion_jobs.py
git commit -m "feat: add Temporal ingestion workflow scaffold"
```

### Task 7: Persist parsed artifacts and quality reports, then verify end-to-end foundation flow

**Files:**
- Modify: `apps/api/app/repositories/ingestion.py`
- Modify: `apps/api/app/services/ingestion_service.py`
- Modify: `apps/api/app/api/routes/documents.py`
- Test: `apps/api/app/tests/unit/test_ingestion_repository.py`
- Test: `apps/api/app/tests/integration/test_documents_upload.py`

- [ ] **Step 1: Write a failing repository test for artifact/report persistence**

```python
def test_store_parsed_artifact_and_quality_report(session) -> None:
    run = create_test_ingestion_run(session)
    artifact = build_test_artifact(run.document_id)

    stored = store_parsed_artifact(run_id=run.id, artifact=artifact)

    assert stored.run_id == run.id
    assert stored.table_count == 1
```

- [ ] **Step 2: Run the repository and upload integration tests to verify they fail**

Run: `pytest apps/api/app/tests/unit/test_ingestion_repository.py apps/api/app/tests/integration/test_documents_upload.py -v`
Expected: FAIL because artifact/report persistence does not exist.

- [ ] **Step 3: Add persistence helpers and route-visible status fields**

```python
# apps/api/app/repositories/ingestion.py
def store_parsed_artifact(*, run_id: UUID, artifact: ParsedArtifact, object_key: str) -> ParsedArtifactRecord:
    report = build_quality_report(artifact)
    record = ParsedArtifactRecord(
        ingestion_run_id=run_id,
        artifact_json=artifact.model_dump(mode="json"),
        page_count=report.page_count,
        table_count=report.table_count,
        artifact_object_key=object_key,
    )
    with session_factory() as session:
        session.add(record)
        session.flush()
        session.add(
            QualityReport(
                ingestion_run_id=run_id,
                parser_backend=report.parser_backend,
                summary_json={
                    "page_count": report.page_count,
                    "table_count": report.table_count,
                },
            )
        )
        session.commit()
        session.refresh(record)
        return record
```

```python
# apps/api/app/services/ingestion_service.py
def finalize_parse_stage(
    *,
    run_id: UUID,
    stage_id: UUID,
    artifact: ParsedArtifact,
    artifact_object_key: str,
) -> None:
    artifact_record = store_parsed_artifact(
        run_id=run_id,
        artifact=artifact,
        object_key=artifact_object_key,
    )
    update_ingestion_stage_status(stage_id=stage_id, status="completed", output_ref=str(artifact_record.id))
    update_document_ingestion_status(run_id=run_id, status="parsed")
```

- [ ] **Step 4: Re-run repository + upload tests and then the full Phase 2 foundation subset**

Run: `pytest apps/api/app/tests/unit/test_ingestion_repository.py apps/api/app/tests/unit/test_storage_adapters.py apps/api/app/tests/unit/test_parsed_artifact_schema.py apps/api/app/tests/unit/test_quality_report.py apps/api/app/tests/integration/test_documents_upload.py apps/api/app/tests/integration/test_ingestion_jobs.py apps/api/app/tests/integration/test_docling_parser_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/repositories/ingestion.py apps/api/app/services/ingestion_service.py apps/api/app/api/routes/documents.py apps/api/app/tests/unit/test_ingestion_repository.py apps/api/app/tests/integration/test_documents_upload.py
git commit -m "feat: persist parsed artifacts and quality reports"
```

---

## Self-review checklist

- ADR-0009 covered: SeaweedFS-backed object storage seam replaces local-only default.
- ADR-0010 covered: Temporal runtime/workflow scaffold and ingestion run tracking land in Phase 2.
- ADR-0011 covered: one parsed-artifact contract and deployment-profile-aware parser backends.
- Phase 2 tasks covered: storage, dedup, ingestion job table, Docling adapter, OCR/document-understanding interface, quality report, parsed artifacts/provenance.
- Deliberately deferred to later phases: chunking, embeddings, OpenSearch/Qdrant indexing, reranking, chat.
