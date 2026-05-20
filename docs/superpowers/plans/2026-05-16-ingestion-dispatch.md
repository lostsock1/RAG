# Ingestion Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire active ingestion dispatch so that uploading a document triggers a three-stage pipeline (parse → persist artifact → quality report) that runs in-process via `asyncio.create_task`.

**Architecture:** A `WorkflowDispatcher` protocol with one concrete `InProcessDispatcher` implementation. Upload calls `dispatcher.dispatch(run_id)` which spawns an `asyncio.Task`. The task creates `IngestionStage` records, runs each stage sequentially with checkpointing, and updates the run status. Stages are idempotent — re-dispatching a run skips completed stages.

**Tech Stack:** Python 3, asyncio, FastAPI, SQLAlchemy, existing parser/quality-report services.

**Spec:** `docs/superpowers/specs/2026-05-16-ingestion-dispatch-design.md`

---

## File Structure

| Action | File | Responsibility |
|---|---|---|
| Create | `apps/api/app/workflows/dispatcher.py` | `WorkflowDispatcher` protocol + `InProcessDispatcher` |
| Create | `apps/api/app/workflows/stages.py` | Three stage functions with checkpointing |
| Modify | `apps/api/app/repositories/ingestion.py` | Add stage/run CRUD helpers |
| Modify | `apps/api/app/services/document_service.py` | Call dispatcher after run creation |
| Modify | `apps/api/app/main.py` | Build dispatcher at startup, recovery sweep |
| Create | `apps/api/app/tests/unit/test_dispatcher.py` | Unit tests for dispatcher and stages |
| Create | `apps/api/app/tests/integration/test_ingestion_dispatch.py` | End-to-end dispatch integration tests |

---

### Task 1: Repository helpers for stage and run status management

**Files:**
- Modify: `apps/api/app/repositories/ingestion.py`
- Test: `apps/api/app/tests/unit/test_ingestion_repository.py`

- [ ] **Step 1: Write failing tests for the new repository functions**

Add to `apps/api/app/tests/unit/test_ingestion_repository.py`:

```python
def test_create_ingestion_stages_creates_three_records(setup_db):
    from app.repositories.ingestion import create_ingestion_stages, get_stages_for_run
    from app.db.models.ingestion import IngestionRun

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).limit(1))
        assert run is not None

    stages = create_ingestion_stages(
        run_id=run.id,
        tenant_id=run.tenant_id,
        stage_names=["parse", "persist_artifact", "quality_report"],
    )
    assert len(stages) == 3
    assert all(s.status == "queued" for s in stages)
    assert [s.stage_name for s in stages] == ["parse", "persist_artifact", "quality_report"]

    loaded = get_stages_for_run(run_id=run.id)
    assert len(loaded) == 3


def test_update_stage_status_sets_status_and_details(setup_db):
    from app.repositories.ingestion import create_ingestion_stages, update_stage_status, get_stages_for_run
    from app.db.models.ingestion import IngestionRun

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).limit(1))
        assert run is not None

    stages = create_ingestion_stages(
        run_id=run.id,
        tenant_id=run.tenant_id,
        stage_names=["parse"],
    )
    stage = stages[0]

    update_stage_status(stage_id=stage.id, status="running")
    update_stage_status(stage_id=stage.id, status="completed", details={"page_count": 5})

    loaded = get_stages_for_run(run_id=run.id)
    assert loaded[0].status == "completed"
    assert loaded[0].details["page_count"] == 5


def test_update_run_status(setup_db):
    from app.repositories.ingestion import update_run_status
    from app.db.models.ingestion import IngestionRun

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).limit(1))
        assert run is not None

    update_run_status(run_id=run.id, status="running")

    with session_factory() as session:
        refreshed = session.scalar(select(IngestionRun).where(IngestionRun.id == run.id))
        assert refreshed.status == "running"


def test_recover_orphaned_runs_resets_running_to_queued(setup_db):
    from app.repositories.ingestion import update_run_status, recover_orphaned_runs
    from app.db.models.ingestion import IngestionRun

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).limit(1))
        assert run is not None

    update_run_status(run_id=run.id, status="running")
    recover_orphaned_runs()

    with session_factory() as session:
        refreshed = session.scalar(select(IngestionRun).where(IngestionRun.id == run.id))
        assert refreshed.status == "queued"
```

Note: `setup_db` is an existing fixture pattern in this test file. Check the file for the exact fixture name and adjust if needed. The fixture creates an in-memory SQLite DB with a tenant, user, and document so that an `IngestionRun` can be created.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/unit/test_ingestion_repository.py -v -k "test_create_ingestion_stages or test_update_stage_status or test_update_run_status or test_recover_orphaned"`
Expected: FAIL — functions not defined yet.

- [ ] **Step 3: Implement the repository functions**

Add these functions to `apps/api/app/repositories/ingestion.py` (after the existing `create_ingestion_run` function, around line 39):

```python
def create_ingestion_stages(*, run_id: UUID, tenant_id: UUID, stage_names: list[str]) -> list[IngestionStage]:
    from app.db.models.ingestion import IngestionStage

    stages = [
        IngestionStage(run_id=run_id, tenant_id=tenant_id, stage_name=name, status="queued")
        for name in stage_names
    ]

    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError("Ingestion persistence is not configured: session_factory has no database bind.")

        session.add_all(stages)
        session.commit()
        for stage in stages:
            session.refresh(stage)
        return stages


def get_stages_for_run(*, run_id: UUID) -> list[IngestionStage]:
    from app.db.models.ingestion import IngestionStage

    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError("Ingestion persistence is not configured: session_factory has no database bind.")

        return list(
            session.scalars(
                select(IngestionStage).where(IngestionStage.run_id == run_id).order_by(IngestionStage.created_at.asc())
            ).all()
        )


def update_stage_status(*, stage_id: UUID, status: str, details: dict | None = None) -> None:
    from app.db.models.ingestion import IngestionStage

    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError("Ingestion persistence is not configured: session_factory has no database bind.")

        stage = session.scalar(select(IngestionStage).where(IngestionStage.id == stage_id))
        if stage is None:
            return

        stage.status = status
        if details is not None:
            stage.details = {**stage.details, **details}
        session.commit()


def update_run_status(*, run_id: UUID, status: str) -> None:
    with session_factory() as session:
        if session.bind is None:
            raise RuntimeError("Ingestion persistence is not configured: session_factory has no database bind.")

        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        if run is None:
            return

        run.status = status
        session.commit()


def recover_orphaned_runs() -> int:
    with session_factory() as session:
        if session.bind is None:
            return 0

        result = session.execute(
            IngestionRun.__table__.update()
            .where(IngestionRun.status == "running")
            .values(status="queued")
        )
        session.commit()
        return result.rowcount
```

Also add the missing import at the top of the file — `IngestionStage` is needed. Add to the existing imports:

```python
from app.db.models.ingestion import IngestionRun, IngestionStage, ParsedArtifact as ParsedArtifactRecord, QualityReport
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/unit/test_ingestion_repository.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `cd /djesys/code/RAG && python -m pytest --tb=short -q`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/repositories/ingestion.py apps/api/app/tests/unit/test_ingestion_repository.py
git commit -m "feat: add stage/run status repository helpers for ingestion dispatch"
```

---

### Task 2: Stage functions with checkpointing

**Files:**
- Create: `apps/api/app/workflows/stages.py`
- Test: `apps/api/app/tests/unit/test_dispatcher.py`

- [ ] **Step 1: Write failing tests for stage functions**

Create `apps/api/app/tests/unit/test_dispatcher.py`:

```python
from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.db.base import session_factory
from app.db.models.document import Document
from app.db.models.ingestion import IngestionRun, IngestionStage
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParsedBlock, ParserProvenance


@pytest.fixture()
def setup_db():
    """Create an in-memory DB with a tenant, user, document, and ingestion run."""
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'dispatch.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        tenant_id = uuid4()
        user_id = uuid4()
        doc_id = uuid4()

        with session_factory() as session:
            session.add(Tenant(id=tenant_id, name="Test", slug="test"))
            session.add(User(id=user_id, tenant_id=tenant_id, email="u@t.com", display_name="U", roles=["editor"]))
            session.add(
                Document(
                    id=doc_id,
                    tenant_id=tenant_id,
                    owner_user_id=user_id,
                    title="Test Doc",
                    source_type="loose_document",
                    source_hash="abc123",
                    file_name="test.txt",
                    file_size_bytes=10,
                    object_key="documents/test/test.txt",
                    ingestion_status="uploaded",
                )
            )
            session.commit()

        run_id = uuid4()
        with session_factory() as session:
            session.add(
                IngestionRun(
                    id=run_id,
                    document_id=doc_id,
                    tenant_id=tenant_id,
                    parser_backend="docling",
                    source_hash="abc123",
                    status="queued",
                    workflow_backend="in_process",
                )
            )
            session.commit()

        yield {
            "engine": engine,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "doc_id": doc_id,
            "run_id": run_id,
        }

        session_factory.configure(bind=None)
        engine.dispose()


def _make_artifact(doc_id: UUID) -> ParsedArtifact:
    return ParsedArtifact(
        document_id=doc_id,
        pages=[
            ParsedPage(page_number=1, text="Hello world", blocks=[ParsedBlock(block_type="text", text="Hello world")]),
        ],
        tables=[],
        provenance=ParserProvenance(parser_backend="docling", parser_version="1.0.0", profile="loose"),
    )


def test_run_parse_stage_calls_parser_and_checkpoints(setup_db):
    from app.workflows.stages import run_parse_stage
    from app.repositories.ingestion import create_ingestion_stages, get_stages_for_run

    run_id = setup_db["run_id"]
    doc_id = setup_db["doc_id"]
    tenant_id = setup_db["tenant_id"]

    stages = create_ingestion_stages(run_id=run_id, tenant_id=tenant_id, stage_names=["parse", "persist_artifact", "quality_report"])
    parse_stage = stages[0]

    artifact = run_parse_stage(
        run_id=run_id,
        stage_id=parse_stage.id,
        document_id=doc_id,
        object_key="documents/test/test.txt",
        content_type="text/plain",
        profile="loose",
        parser_backend="docling",
    )

    assert artifact is not None
    assert artifact.document_id == doc_id
    assert len(artifact.pages) == 1

    loaded_stages = get_stages_for_run(run_id=run_id)
    parse_loaded = [s for s in loaded_stages if s.stage_name == "parse"][0]
    assert parse_loaded.status == "completed"
    assert parse_loaded.details["page_count"] == 1


def test_run_persist_artifact_stage_stores_artifact(setup_db):
    from app.workflows.stages import run_persist_artifact_stage
    from app.repositories.ingestion import create_ingestion_stages, get_stages_for_run

    run_id = setup_db["run_id"]
    doc_id = setup_db["doc_id"]
    tenant_id = setup_db["tenant_id"]

    stages = create_ingestion_stages(run_id=run_id, tenant_id=tenant_id, stage_names=["parse", "persist_artifact", "quality_report"])
    persist_stage = stages[1]
    artifact = _make_artifact(doc_id)

    run_persist_artifact_stage(run_id=run_id, stage_id=persist_stage.id, artifact=artifact)

    loaded_stages = get_stages_for_run(run_id=run_id)
    persist_loaded = [s for s in loaded_stages if s.stage_name == "persist_artifact"][0]
    assert persist_loaded.status == "completed"


def test_run_quality_report_stage_checkpoints_report(setup_db):
    from app.workflows.stages import run_quality_report_stage
    from app.repositories.ingestion import create_ingestion_stages, get_stages_for_run, store_parsed_artifact

    run_id = setup_db["run_id"]
    doc_id = setup_db["doc_id"]
    tenant_id = setup_db["tenant_id"]

    stages = create_ingestion_stages(run_id=run_id, tenant_id=tenant_id, stage_names=["parse", "persist_artifact", "quality_report"])
    report_stage = stages[2]
    artifact = _make_artifact(doc_id)

    store_parsed_artifact(run_id=run_id, artifact=artifact)

    run_quality_report_stage(run_id=run_id, stage_id=report_stage.id, artifact=artifact)

    loaded_stages = get_stages_for_run(run_id=run_id)
    report_loaded = [s for s in loaded_stages if s.stage_name == "quality_report"][0]
    assert report_loaded.status == "completed"
    assert "quality_score" in report_loaded.details


def test_stage_skips_if_already_completed(setup_db):
    from app.workflows.stages import run_parse_stage
    from app.repositories.ingestion import create_ingestion_stages, update_stage_status, get_stages_for_run

    run_id = setup_db["run_id"]
    doc_id = setup_db["doc_id"]
    tenant_id = setup_db["tenant_id"]

    stages = create_ingestion_stages(run_id=run_id, tenant_id=tenant_id, stage_names=["parse"])
    parse_stage = stages[0]
    update_stage_status(stage_id=parse_stage.id, status="completed", details={"page_count": 0})

    result = run_parse_stage(
        run_id=run_id,
        stage_id=parse_stage.id,
        document_id=doc_id,
        object_key="documents/test/test.txt",
        content_type="text/plain",
        profile="loose",
        parser_backend="docling",
    )

    assert result is None

    loaded_stages = get_stages_for_run(run_id=run_id)
    assert loaded_stages[0].details["page_count"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/unit/test_dispatcher.py -v`
Expected: FAIL — `app.workflows.stages` module not found.

- [ ] **Step 3: Implement the stage functions**

Create `apps/api/app/workflows/stages.py`:

```python
from __future__ import annotations

import logging
from uuid import UUID

from app.repositories.ingestion import (
    get_stages_for_run,
    store_parsed_artifact,
    update_stage_status,
)
from app.schemas.parsed_artifacts import ParsedArtifact
from app.services.parsers.base import DocumentParser, ParseRequest
from app.services.parsers.docling_backend import DoclingDocumentParser
from app.services.parsers.remote_backend import RemoteDocumentParser
from app.services.quality_report import build_quality_report

logger = logging.getLogger(__name__)


def _resolve_parser(parser_backend: str) -> DocumentParser:
    if parser_backend == "docling":
        return DoclingDocumentParser()
    if parser_backend == "remote":
        raise RuntimeError("Remote parser backend requires an invoke_remote_parser callable. Use the factory pattern instead.")
    raise ValueError(f"Unknown parser backend: {parser_backend}")


def _is_stage_completed(*, run_id: UUID, stage_name: str) -> bool:
    stages = get_stages_for_run(run_id=run_id)
    for stage in stages:
        if stage.stage_name == stage_name and stage.status == "completed":
            return True
    return False


def run_parse_stage(
    *,
    run_id: UUID,
    stage_id: UUID,
    document_id: UUID,
    object_key: str,
    content_type: str,
    profile: str,
    parser_backend: str,
) -> ParsedArtifact | None:
    if _is_stage_completed(run_id=run_id, stage_name="parse"):
        logger.info("Stage parse already completed for run %s, skipping.", run_id)
        return None

    update_stage_status(stage_id=stage_id, status="running")

    parser = _resolve_parser(parser_backend)
    request = ParseRequest(
        document_id=str(document_id),
        object_key=object_key,
        content_type=content_type,
        profile=profile,
    )
    artifact = parser.parse(request)

    update_stage_status(
        stage_id=stage_id,
        status="completed",
        details={
            "page_count": len(artifact.pages),
            "table_count": len(artifact.tables),
            "parser_backend": parser_backend,
        },
    )

    return artifact


def run_persist_artifact_stage(
    *,
    run_id: UUID,
    stage_id: UUID,
    artifact: ParsedArtifact,
) -> None:
    if _is_stage_completed(run_id=run_id, stage_name="persist_artifact"):
        logger.info("Stage persist_artifact already completed for run %s, skipping.", run_id)
        return

    update_stage_status(stage_id=stage_id, status="running")
    store_parsed_artifact(run_id=run_id, artifact=artifact)
    update_stage_status(stage_id=stage_id, status="completed")


def run_quality_report_stage(
    *,
    run_id: UUID,
    stage_id: UUID,
    artifact: ParsedArtifact,
) -> None:
    if _is_stage_completed(run_id=run_id, stage_name="quality_report"):
        logger.info("Stage quality_report already completed for run %s, skipping.", run_id)
        return

    update_stage_status(stage_id=stage_id, status="running")
    report = build_quality_report(artifact)
    update_stage_status(
        stage_id=stage_id,
        status="completed",
        details={
            "quality_score": report.quality_score,
            "warnings": report.warnings,
            "summary": report.summary,
        },
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/unit/test_dispatcher.py -v`
Expected: `test_run_parse_stage_calls_parser_and_checkpoints` will fail because `DoclingDocumentParser()` without a converter raises `RuntimeError`. We need to inject a test converter.

Update the `run_parse_stage` test to inject a converter into the parser. Modify the `_resolve_parser` function to accept an optional parser instance, or modify the test to use a different approach.

**Revised approach:** Make `_resolve_parser` accept an optional `parser_override` parameter for testability, and have the stage function accept it too.

Update `apps/api/app/workflows/stages.py` — change `run_parse_stage` signature to accept an optional `parser` parameter:

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
) -> ParsedArtifact | None:
    if _is_stage_completed(run_id=run_id, stage_name="parse"):
        logger.info("Stage parse already completed for run %s, skipping.", run_id)
        return None

    update_stage_status(stage_id=stage_id, status="running")

    if parser is None:
        parser = _resolve_parser(parser_backend)

    request = ParseRequest(
        document_id=str(document_id),
        object_key=object_key,
        content_type=content_type,
        profile=profile,
    )
    artifact = parser.parse(request)

    update_stage_status(
        stage_id=stage_id,
        status="completed",
        details={
            "page_count": len(artifact.pages),
            "table_count": len(artifact.tables),
            "parser_backend": parser_backend,
        },
    )

    return artifact
```

Update the test to inject a parser with a converter:

```python
def test_run_parse_stage_calls_parser_and_checkpoints(setup_db):
    from app.workflows.stages import run_parse_stage
    from app.repositories.ingestion import create_ingestion_stages, get_stages_for_run
    from app.services.parsers.docling_backend import DoclingDocumentParser

    run_id = setup_db["run_id"]
    doc_id = setup_db["doc_id"]
    tenant_id = setup_db["tenant_id"]

    stages = create_ingestion_stages(run_id=run_id, tenant_id=tenant_id, stage_names=["parse", "persist_artifact", "quality_report"])
    parse_stage = stages[0]

    expected_artifact = _make_artifact(doc_id)
    parser = DoclingDocumentParser(converter=lambda req: expected_artifact)

    artifact = run_parse_stage(
        run_id=run_id,
        stage_id=parse_stage.id,
        document_id=doc_id,
        object_key="documents/test/test.txt",
        content_type="text/plain",
        profile="loose",
        parser_backend="docling",
        parser=parser,
    )

    assert artifact is not None
    assert artifact.document_id == doc_id
    assert len(artifact.pages) == 1

    loaded_stages = get_stages_for_run(run_id=run_id)
    parse_loaded = [s for s in loaded_stages if s.stage_name == "parse"][0]
    assert parse_loaded.status == "completed"
    assert parse_loaded.details["page_count"] == 1
```

- [ ] **Step 5: Run tests again**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/unit/test_dispatcher.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Run full test suite**

Run: `cd /djesys/code/RAG && python -m pytest --tb=short -q`
Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/workflows/stages.py apps/api/app/tests/unit/test_dispatcher.py
git commit -m "feat: add three-stage ingestion pipeline with checkpointing"
```

---

### Task 3: Dispatcher protocol and InProcessDispatcher

**Files:**
- Create: `apps/api/app/workflows/dispatcher.py`
- Test: `apps/api/app/tests/unit/test_dispatcher.py` (extend)

- [ ] **Step 1: Write failing tests for the dispatcher**

Add to `apps/api/app/tests/unit/test_dispatcher.py`:

```python
def test_in_process_dispatcher_runs_all_stages(setup_db):
    import asyncio
    from app.workflows.dispatcher import InProcessDispatcher
    from app.repositories.ingestion import get_stages_for_run, update_run_status
    from app.db.models.ingestion import IngestionRun
    from app.services.parsers.docling_backend import DoclingDocumentParser

    run_id = setup_db["run_id"]
    doc_id = setup_db["doc_id"]
    tenant_id = setup_db["tenant_id"]

    expected_artifact = _make_artifact(doc_id)
    parser = DoclingDocumentParser(converter=lambda req: expected_artifact)

    dispatcher = InProcessDispatcher(parser=parser)

    asyncio.get_event_loop().run_until_complete(dispatcher.dispatch(run_id))

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        assert run.status == "completed"

    stages = get_stages_for_run(run_id=run_id)
    assert len(stages) == 3
    assert all(s.status == "completed" for s in stages)


def test_in_process_dispatcher_marks_run_failed_on_stage_error(setup_db):
    import asyncio
    from app.workflows.dispatcher import InProcessDispatcher
    from app.repositories.ingestion import get_stages_for_run
    from app.db.models.ingestion import IngestionRun
    from app.services.parsers.docling_backend import DoclingDocumentParser

    run_id = setup_db["run_id"]
    doc_id = setup_db["doc_id"]

    def failing_converter(req):
        raise RuntimeError("Parser exploded")

    parser = DoclingDocumentParser(converter=failing_converter)
    dispatcher = InProcessDispatcher(parser=parser)

    asyncio.get_event_loop().run_until_complete(dispatcher.dispatch(run_id))

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        assert run.status == "failed"

    stages = get_stages_for_run(run_id=run_id)
    parse_stage = [s for s in stages if s.stage_name == "parse"][0]
    assert parse_stage.status == "failed"
    assert "error" in parse_stage.details
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/unit/test_dispatcher.py -v -k "test_in_process"`
Expected: FAIL — `app.workflows.dispatcher` module not found.

- [ ] **Step 3: Implement the dispatcher**

Create `apps/api/app/workflows/dispatcher.py`:

```python
from __future__ import annotations

import asyncio
import logging
from typing import Protocol
from uuid import UUID

from app.db.models.ingestion import IngestionRun
from app.repositories.ingestion import (
    create_ingestion_stages,
    get_stages_for_run,
    update_run_status,
    update_stage_status,
)
from app.services.parsers.base import DocumentParser
from app.workflows.stages import run_parse_stage, run_persist_artifact_stage, run_quality_report_stage

logger = logging.getLogger(__name__)

STAGE_NAMES = ["parse", "persist_artifact", "quality_report"]


class WorkflowDispatcher(Protocol):
    async def dispatch(self, run_id: UUID) -> None: ...


class InProcessDispatcher:
    def __init__(self, parser: DocumentParser) -> None:
        self._parser = parser

    async def dispatch(self, run_id: UUID) -> None:
        loop = asyncio.get_event_loop()
        loop.create_task(self._run_pipeline(run_id))

    async def _run_pipeline(self, run_id: UUID) -> None:
        try:
            await asyncio.to_thread(self._execute_pipeline, run_id)
        except Exception:
            logger.exception("Ingestion pipeline failed unexpectedly for run %s", run_id)

    def _execute_pipeline(self, run_id: UUID) -> None:
        from app.db.base import session_factory
        from sqlalchemy import select

        with session_factory() as session:
            run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
            if run is None:
                logger.error("Ingestion run %s not found, cannot dispatch.", run_id)
                return

            tenant_id = run.tenant_id
            document_id = run.document_id
            object_key = None
            content_type = "application/octet-stream"

            from app.db.models.document import Document
            doc = session.scalar(select(Document).where(Document.id == document_id))
            if doc is not None:
                object_key = doc.object_key
                content_type = "application/octet-stream"

        update_run_status(run_id=run_id, status="running")

        stages = create_ingestion_stages(run_id=run_id, tenant_id=tenant_id, stage_names=STAGE_NAMES)
        stage_map = {s.stage_name: s for s in stages}

        try:
            artifact = run_parse_stage(
                run_id=run_id,
                stage_id=stage_map["parse"].id,
                document_id=document_id,
                object_key=object_key or "",
                content_type=content_type,
                profile="loose",
                parser_backend="docling",
                parser=self._parser,
            )

            if artifact is None:
                logger.info("Parse stage was skipped (already completed) for run %s. Loading artifact from DB.", run_id)
                from app.repositories.ingestion import store_parsed_artifact
                from app.db.models.ingestion import ParsedArtifact as ParsedArtifactRecord
                with session_factory() as session:
                    record = session.scalar(
                        select(ParsedArtifactRecord).where(ParsedArtifactRecord.run_id == run_id)
                    )
                    if record is not None:
                        from app.schemas.parsed_artifacts import ParsedArtifact as ParsedArtifactSchema
                        artifact = ParsedArtifactSchema.model_validate(record.artifact_json)

            if artifact is not None:
                run_persist_artifact_stage(run_id=run_id, stage_id=stage_map["persist_artifact"].id, artifact=artifact)
                run_quality_report_stage(run_id=run_id, stage_id=stage_map["quality_report"].id, artifact=artifact)

            update_run_status(run_id=run_id, status="completed")

        except Exception as exc:
            logger.exception("Stage failed for run %s: %s", run_id, exc)
            failed_stages = get_stages_for_run(run_id=run_id)
            for stage in failed_stages:
                if stage.status == "running":
                    update_stage_status(stage_id=stage.id, status="failed", details={"error": str(exc)})
            update_run_status(run_id=run_id, status="failed")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/unit/test_dispatcher.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Run full test suite**

Run: `cd /djesys/code/RAG && python -m pytest --tb=short -q`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/workflows/dispatcher.py apps/api/app/tests/unit/test_dispatcher.py
git commit -m "feat: add WorkflowDispatcher protocol and InProcessDispatcher"
```

---

### Task 4: Wire dispatcher into upload flow and app startup

**Files:**
- Modify: `apps/api/app/services/document_service.py`
- Modify: `apps/api/app/main.py`

- [ ] **Step 1: Write failing integration test for end-to-end dispatch**

Create `apps/api/app/tests/integration/test_ingestion_dispatch.py`:

```python
from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.request_context import RequestContext
from app.core.security import get_request_context
from app.db.base import session_factory
from app.db.models.ingestion import IngestionRun, IngestionStage
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.main import app
from app.schemas.parsed_artifacts import ParsedArtifact, ParsedPage, ParsedBlock, ParserProvenance
from app.services.parsers.docling_backend import DoclingDocumentParser
from app.workflows.dispatcher import InProcessDispatcher


class StorageStub:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, *, object_key: str, content: bytes, content_type: str) -> None:
        self.objects[object_key] = content


@pytest.fixture()
def auth_context() -> RequestContext:
    return RequestContext(
        tenant_id=str(uuid4()),
        user_id=str(uuid4()),
        group_ids=[],
        roles=["editor"],
        scopes=["documents:write", "documents:read"],
    )


@pytest.fixture()
def client(auth_context: RequestContext):
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'dispatch_e2e.db'}"
        engine = create_engine(database_url)
        alembic_ini_path = Path("infra/migrations/alembic.ini")
        config = Config(str(alembic_ini_path))
        config.set_main_option("sqlalchemy.url", database_url)

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        session_factory.configure(bind=engine)

        with session_factory() as session:
            session.add(Tenant(id=UUID(auth_context.tenant_id), name="T", slug="t"))
            session.add(
                User(
                    id=UUID(auth_context.user_id),
                    tenant_id=UUID(auth_context.tenant_id),
                    email="u@t.com",
                    display_name="U",
                    roles=auth_context.roles,
                )
            )
            session.commit()

        doc_id = UUID(auth_context.tenant_id)  # unique enough for test
        expected_artifact = ParsedArtifact(
            document_id=doc_id,
            pages=[ParsedPage(page_number=1, text="test content", blocks=[])],
            tables=[],
            provenance=ParserProvenance(parser_backend="docling", parser_version="1.0.0", profile="loose"),
        )
        parser = DoclingDocumentParser(converter=lambda req: expected_artifact)
        dispatcher = InProcessDispatcher(parser=parser)

        app.dependency_overrides[get_request_context] = lambda: auth_context
        app.state.document_storage = StorageStub()
        app.state.dispatcher = dispatcher

        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.clear()
            for attr in ("document_storage", "dispatcher"):
                if hasattr(app.state, attr):
                    delattr(app.state, attr)
            session_factory.configure(bind=None)
            engine.dispose()


def test_upload_triggers_ingestion_dispatch_to_completed(client):
    response = client.post(
        "/api/v1/documents/upload",
        headers={"Authorization": "Bearer test-token"},
        files={"file": ("doc.txt", b"test content", "text/plain")},
        data={"title": "Test Doc", "source_type": "loose_document"},
    )

    assert response.status_code == 201
    payload = response.json()
    run_id = UUID(payload["ingestion_run_id"])

    with session_factory() as session:
        run = session.scalar(select(IngestionRun).where(IngestionRun.id == run_id))
        assert run is not None
        assert run.status == "completed"

        stages = list(session.scalars(
            select(IngestionStage).where(IngestionStage.run_id == run_id).order_by(IngestionStage.created_at.asc())
        ).all())
        assert len(stages) == 3
        assert all(s.status == "completed" for s in stages)
        assert stages[0].stage_name == "parse"
        assert stages[1].stage_name == "persist_artifact"
        assert stages[2].stage_name == "quality_report"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/integration/test_ingestion_dispatch.py -v`
Expected: FAIL — the upload route doesn't call the dispatcher yet.

- [ ] **Step 3: Wire dispatcher into the upload route**

Modify `apps/api/app/services/document_service.py`. No changes needed — `upload_document` stays sync and returns the `UploadResult` as before. The dispatcher call happens in the route.

Modify `apps/api/app/api/routes/documents.py`. Update the `upload_document_route` function to get the dispatcher from app state and call it after `upload_document`:

```python
@router.post("/upload", status_code=status.HTTP_201_CREATED, response_model=DocumentUploadResponse)
async def upload_document_route(
    request: Request,
    title: str = Form(...),
    source_type: str = Form(...),
    document_type: str | None = Form(default=None),
    language: str | None = Form(default=None),
    file: UploadFile = File(...),
    context: RequestContext = Depends(require_scopes(["documents:write"])),
) -> DocumentUploadResponse:
    content = await file.read()
    parser_backend = request.app.state.settings.parser_backend
    result = upload_document(
        context=context,
        payload=UploadPayload(
            file_name=file.filename or "upload.bin",
            content=content,
            content_type=file.content_type or "application/octet-stream",
            form=DocumentUploadForm(
                title=title,
                source_type=source_type,
                document_type=document_type,
                language=language,
            ),
        ),
        storage=get_storage_adapter(request),
        parser_backend=parser_backend,
    )

    dispatcher = getattr(request.app.state, "dispatcher", None)
    if dispatcher is not None:
        await dispatcher.dispatch(result.ingestion_run_id)

    return DocumentUploadResponse.model_validate(
        {**DocumentResponse.model_validate(result.document).model_dump(), "ingestion_run_id": result.ingestion_run_id}
    )
```

This keeps `document_service.py` unchanged — the dispatch is a route-level concern.

- [ ] **Step 4: Update the upload route to pass the dispatcher**

Modify `apps/api/app/api/routes/documents.py`. Update the `upload_document_route` function to get the dispatcher from app state and pass it:

```python
@router.post("/upload", status_code=status.HTTP_201_CREATED, response_model=DocumentUploadResponse)
async def upload_document_route(
    request: Request,
    title: str = Form(...),
    source_type: str = Form(...),
    document_type: str | None = Form(default=None),
    language: str | None = Form(default=None),
    file: UploadFile = File(...),
    context: RequestContext = Depends(require_scopes(["documents:write"])),
) -> DocumentUploadResponse:
    content = await file.read()
    parser_backend = request.app.state.settings.parser_backend
    dispatcher = getattr(request.app.state, "dispatcher", None)
    result = upload_document(
        context=context,
        payload=UploadPayload(
            file_name=file.filename or "upload.bin",
            content=content,
            content_type=file.content_type or "application/octet-stream",
            form=DocumentUploadForm(
                title=title,
                source_type=source_type,
                document_type=document_type,
                language=language,
            ),
        ),
        storage=get_storage_adapter(request),
        parser_backend=parser_backend,
        dispatcher=dispatcher,
    )
    return DocumentUploadResponse.model_validate(
        {**DocumentResponse.model_validate(result.document).model_dump(), "ingestion_run_id": result.ingestion_run_id}
    )
```

- [ ] **Step 4: Update main.py to build dispatcher at startup and run recovery sweep**

Modify `apps/api/app/main.py`:

```python
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.db.base import make_engine, session_factory
from app.services.storage import build_storage_adapter


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = getattr(app.state, "settings", None) or get_settings()
    engine = None

    app.state.settings = settings

    if settings.database_url:
        engine = make_engine(settings.database_url)
        session_factory.configure(bind=engine)
        app.state.db_engine = engine

        from app.repositories.ingestion import recover_orphaned_runs
        recovered = recover_orphaned_runs()
        if recovered > 0:
            import logging
            logging.getLogger(__name__).info("Recovered %d orphaned ingestion run(s) on startup.", recovered)

    storage = build_storage_adapter(settings)
    if storage is not None:
        app.state.document_storage = storage

    if settings.parser_backend:
        from app.services.parsers.docling_backend import DoclingDocumentParser
        from app.workflows.dispatcher import InProcessDispatcher

        parser = DoclingDocumentParser()
        app.state.dispatcher = InProcessDispatcher(parser=parser)

    yield

    session_factory.configure(bind=None)

    if engine is not None:
        engine.dispose()

    for attr in ("db_engine", "document_storage", "settings", "dispatcher"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    app = FastAPI(
        title=active_settings.app_name,
        version=active_settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = active_settings
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
```

- [ ] **Step 5: Run the integration test**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/integration/test_ingestion_dispatch.py -v`
Expected: PASS.

- [ ] **Step 6: Run full test suite**

Run: `cd /djesys/code/RAG && python -m pytest --tb=short -q`
Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/api/routes/documents.py apps/api/app/main.py apps/api/app/tests/integration/test_ingestion_dispatch.py
git commit -m "feat: wire ingestion dispatch into upload flow with startup recovery"
```

---

### Task 5: Update project memory

**Files:**
- Modify: `docs/uber-rag/PROJECT_STATE.md`
- Modify: `docs/uber-rag/TASKS.md`

- [ ] **Step 1: Update TASKS.md**

Mark the first Phase 2 dispatch task as done:

```markdown
- [x] Wire active uploads to the real accepted workflow dispatcher.
```

- [ ] **Step 2: Update PROJECT_STATE.md**

Add a row to the "Recent changes" table:

```markdown
| 2026-05-16 | Ingestion dispatch wired: in-process async dispatcher with three-stage pipeline | `apps/api/app/workflows/dispatcher.py`, `apps/api/app/workflows/stages.py`, `apps/api/app/repositories/ingestion.py`, `apps/api/app/services/document_service.py`, `apps/api/app/main.py`, `apps/api/app/api/routes/documents.py` | Upload now triggers parse → persist artifact → quality report pipeline via `InProcessDispatcher`. Stages are idempotent and checkpointed. Startup recovery sweep resets orphaned `running` runs. |
```

Update the "Ingestion" section in "Current implementation state" to reflect that dispatch is now wired.

- [ ] **Step 3: Commit**

```bash
git add docs/uber-rag/PROJECT_STATE.md docs/uber-rag/TASKS.md
git commit -m "docs: update project state for ingestion dispatch wiring"
```
