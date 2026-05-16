# Parser Factory and Truthful Dispatch Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a parser factory as the runtime composition point and make ingestion dispatch emit truthful backend/profile metadata.

**Architecture:** Introduce `build_document_parser(settings)` to centralize backend selection and resolved runtime metadata. Then thread the resolved backend/profile through `InProcessDispatcher` so parse-stage details and parser provenance reflect the actual configured runtime path instead of hardcoded placeholders.

**Tech Stack:** Python, FastAPI app startup wiring, existing `DocumentParser` implementations, pytest.

---

## File Structure

| Action | File | Responsibility |
|---|---|---|
| Create | `apps/api/app/services/parsers/factory.py` | Runtime parser selection and resolved metadata |
| Modify | `apps/api/app/main.py` | Use parser factory instead of direct Docling construction |
| Modify | `apps/api/app/workflows/dispatcher.py` | Carry truthful parser backend/profile metadata |
| Modify | `apps/api/app/tests/unit/test_parser_backends.py` | Factory tests |
| Modify | `apps/api/app/tests/unit/test_dispatcher.py` | Dispatcher truthfulness tests |
| Modify | `apps/api/app/tests/integration/test_runtime_auth_startup.py` | Startup wiring assertions |

### Task 1: Parser factory

**Files:**
- Create: `apps/api/app/services/parsers/factory.py`
- Test: `apps/api/app/tests/unit/test_parser_backends.py`

- [ ] **Step 1: Write failing tests**

Add tests for:

```python
def test_build_document_parser_resolves_docling_alias_to_local(tmp_path: Path):
    settings = Settings(parser_backend="docling", local_storage_dir=str(tmp_path))
    parser, backend, profile = build_document_parser(settings)
    assert isinstance(parser, DoclingDocumentParser)
    assert backend == "docling-local"
    assert profile == "local-cpu"


def test_build_document_parser_supports_docling_local(tmp_path: Path):
    settings = Settings(parser_backend="docling-local", local_storage_dir=str(tmp_path))
    parser, backend, profile = build_document_parser(settings)
    assert isinstance(parser, DoclingDocumentParser)
    assert backend == "docling-local"
    assert profile == "local-cpu"


def test_build_document_parser_rejects_remote_backend_until_implemented():
    settings = Settings(parser_backend="remote")
    with pytest.raises(RuntimeError, match="not yet supported"):
        build_document_parser(settings)


def test_build_document_parser_rejects_unknown_backend():
    settings = Settings(parser_backend="weird")
    with pytest.raises(RuntimeError, match="Unknown parser backend"):
        build_document_parser(settings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/djesys/RAG && python -m pytest apps/api/app/tests/unit/test_parser_backends.py -v`
Expected: FAIL because factory module does not exist yet.

- [ ] **Step 3: Implement the factory**

Create `apps/api/app/services/parsers/factory.py`:

```python
from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.services.parsers.base import DocumentParser
from app.services.parsers.docling_backend import DoclingDocumentParser


def build_document_parser(settings: Settings) -> tuple[DocumentParser, str, str]:
    backend = settings.parser_backend

    if backend in {"docling", "docling-local"}:
        parser = DoclingDocumentParser(
            storage_root=Path(settings.local_storage_dir) if settings.local_storage_dir else None
        )
        return parser, "docling-local", "local-cpu"

    if backend == "remote":
        raise RuntimeError("Parser backend 'remote' is not yet supported by the runtime parser factory.")

    raise RuntimeError(f"Unknown parser backend: {backend}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/djesys/RAG && python -m pytest apps/api/app/tests/unit/test_parser_backends.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/parsers/factory.py apps/api/app/tests/unit/test_parser_backends.py
git commit -m "feat: add runtime parser factory"
```

### Task 2: Runtime wiring through factory

**Files:**
- Modify: `apps/api/app/main.py`
- Test: `apps/api/app/tests/integration/test_runtime_auth_startup.py`

- [ ] **Step 1: Write failing startup wiring assertions**

Extend the startup test to verify dispatcher metadata:

```python
assert app.state.dispatcher._parser_backend == "docling-local"
assert app.state.dispatcher._parser_profile == "local-cpu"
```

- [ ] **Step 2: Run the targeted startup test**

Run: `cd /Users/djesys/RAG && python -m pytest apps/api/app/tests/integration/test_runtime_auth_startup.py -v`
Expected: FAIL because dispatcher does not yet expose truthful metadata.

- [ ] **Step 3: Update main.py**

Replace direct parser construction with factory usage:

```python
    if settings.parser_backend:
        from app.services.parsers.factory import build_document_parser
        from app.workflows.dispatcher import InProcessDispatcher

        parser, parser_backend, parser_profile = build_document_parser(settings)
        app.state.dispatcher = InProcessDispatcher(
            parser=parser,
            parser_backend=parser_backend,
            parser_profile=parser_profile,
        )
```

- [ ] **Step 4: Run startup test again**

Run: `cd /Users/djesys/RAG && python -m pytest apps/api/app/tests/integration/test_runtime_auth_startup.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/main.py apps/api/app/tests/integration/test_runtime_auth_startup.py
git commit -m "feat: wire parser factory into app startup"
```

### Task 3: Truthful dispatcher metadata

**Files:**
- Modify: `apps/api/app/workflows/dispatcher.py`
- Test: `apps/api/app/tests/unit/test_dispatcher.py`

- [ ] **Step 1: Write failing dispatcher tests**

Add assertions that the parse stage records the resolved backend, not `docling`:

```python
def test_in_process_dispatcher_records_truthful_parser_metadata(dispatcher_env):
    from app.workflows.dispatcher import InProcessDispatcher
    from app.repositories.ingestion import get_stages_for_run
    from app.services.parsers.docling_backend import DoclingDocumentParser

    run_id = dispatcher_env["run_id"]
    doc_id = dispatcher_env["doc_id"]
    expected_artifact = _make_artifact(doc_id)
    parser = DoclingDocumentParser(converter=lambda req: expected_artifact)

    dispatcher = InProcessDispatcher(
        parser=parser,
        parser_backend="docling-local",
        parser_profile="local-cpu",
    )
    dispatcher._execute_pipeline(run_id)

    stages = get_stages_for_run(run_id=run_id)
    parse_stage = [s for s in stages if s.stage_name == "parse"][0]
    assert parse_stage.details["parser_backend"] == "docling-local"
```

- [ ] **Step 2: Run the targeted dispatcher test**

Run: `cd /Users/djesys/RAG && python -m pytest apps/api/app/tests/unit/test_dispatcher.py -v`
Expected: FAIL because dispatcher constructor/signature still only accepts parser.

- [ ] **Step 3: Implement truthful metadata threading**

Change dispatcher constructor and parse call:

```python
class InProcessDispatcher:
    def __init__(self, parser: DocumentParser, parser_backend: str, parser_profile: str) -> None:
        self._parser = parser
        self._parser_backend = parser_backend
        self._parser_profile = parser_profile
```

and in `_execute_pipeline()`:

```python
            artifact = run_parse_stage(
                run_id=run_id,
                stage_id=stage_map["parse"].id,
                document_id=document_id,
                object_key=object_key or "",
                content_type=content_type,
                profile=self._parser_profile,
                parser_backend=self._parser_backend,
                parser=self._parser,
            )
```

- [ ] **Step 4: Run dispatcher tests again**

Run: `cd /Users/djesys/RAG && python -m pytest apps/api/app/tests/unit/test_dispatcher.py -v`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `cd /Users/djesys/RAG && python -m pytest --tb=short -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/workflows/dispatcher.py apps/api/app/tests/unit/test_dispatcher.py
git commit -m "feat: make dispatcher emit truthful parser metadata"
```
