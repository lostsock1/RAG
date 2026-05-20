# Real Docling Local Parsing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the injected-converter-only Docling parser path with a real local filesystem-backed Docling conversion path that normalizes pages and tables into `ParsedArtifact`.

**Architecture:** Keep the Docling integration contained inside `apps/api/app/services/parsers/docling_backend.py`. Preserve the injected converter override for deterministic tests, and add a storage-root-backed runtime path that resolves local files, runs Docling conversion, and normalizes pages/tables into the existing parser contract.

**Tech Stack:** Python, FastAPI runtime config, Docling, Pydantic schemas, pytest.

---

## File Structure

| Action | File | Responsibility |
|---|---|---|
| Modify | `apps/api/app/services/parsers/docling_backend.py` | Add storage-root-backed Docling runtime path and normalization helpers |
| Modify | `apps/api/app/main.py` | Pass local storage root into runtime Docling parser construction |
| Modify | `apps/api/app/tests/integration/test_docling_parser_adapter.py` | Extend parser tests for real runtime and failure cases |
| Modify | `apps/api/app/tests/unit/test_parser_backends.py` | Add runtime error-path tests if best suited there |

### Task 1: Real local Docling parsing path

**Files:**
- Modify: `apps/api/app/services/parsers/docling_backend.py`
- Test: `apps/api/app/tests/integration/test_docling_parser_adapter.py`

- [ ] **Step 1: Write failing tests**

Add tests for:

```python
def test_docling_parser_requires_storage_root_for_runtime_path():
    parser = DoclingDocumentParser()
    with pytest.raises(RuntimeError, match="storage root"):
        parser.parse(ParseRequest(
            document_id="11111111-1111-1111-1111-111111111111",
            object_key="documents/sample.pdf",
            content_type="application/pdf",
            profile="cpu-local",
        ))


def test_docling_parser_raises_when_local_file_missing(tmp_path: Path):
    parser = DoclingDocumentParser(storage_root=tmp_path)
    with pytest.raises(RuntimeError, match="documents/sample.pdf"):
        parser.parse(ParseRequest(
            document_id="11111111-1111-1111-1111-111111111111",
            object_key="documents/sample.pdf",
            content_type="application/pdf",
            profile="cpu-local",
        ))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/integration/test_docling_parser_adapter.py -v`
Expected: FAIL because `DoclingDocumentParser` does not yet accept `storage_root` or implement runtime parsing rules.

- [ ] **Step 3: Implement runtime parser path**

Update `docling_backend.py` to:

```python
from pathlib import Path
```

and change the class shape to:

```python
class DoclingDocumentParser(DocumentParser):
    backend_name = "docling"

    def __init__(
        self,
        converter: Callable[[ParseRequest], ParsedArtifact] | None = None,
        storage_root: Path | None = None,
    ) -> None:
        self._converter = converter
        self._storage_root = storage_root
```

Add private helpers:

```python
def _resolve_local_path(self, object_key: str) -> Path:
    if self._storage_root is None:
        raise RuntimeError("Docling local parsing requires a configured storage root.")

    resolved = (self._storage_root / object_key).resolve()
    try:
        resolved.relative_to(self._storage_root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"Resolved object key escapes storage root: {object_key}") from exc

    if not resolved.exists():
        raise RuntimeError(f"Docling local parsing could not find stored file for object key: {object_key}")

    return resolved


def _parse_with_docling(self, request: ParseRequest) -> ParsedArtifact:
    if self._storage_root is None:
        raise RuntimeError("Docling local parsing requires a configured storage root.")

    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise RuntimeError(
            "Docling parsing requires the docling package for real local conversion."
        ) from exc

    source_path = self._resolve_local_path(request.object_key)
    converter = DocumentConverter()

    try:
        result = converter.convert(str(source_path))
    except Exception as exc:
        raise RuntimeError(f"Docling conversion failed for object key: {request.object_key}") from exc

    return self._normalize_docling_result(request, result)
```

Normalize minimally:

```python
def _extract_pages(self, doc) -> list[ParsedPage]:
    pages: list[ParsedPage] = []
    texts = []
    if hasattr(doc, "export_to_markdown"):
        texts.append(doc.export_to_markdown())
    text = "\n".join([t for t in texts if t]).strip()
    pages.append(ParsedPage(page_number=1, text=text, blocks=[]))
    return pages


def _extract_tables(self, doc) -> list[ParsedTable]:
    tables: list[ParsedTable] = []
    doc_tables = getattr(doc, "tables", None) or []
    for index, table in enumerate(doc_tables, start=1):
        markdown = ""
        if hasattr(table, "export_to_markdown"):
            markdown = table.export_to_markdown()
        if markdown:
            tables.append(ParsedTable(page_number=1, bbox=[0, 0, 0, 0], markdown=markdown))
    return tables
```

Then:

```python
def _normalize_docling_result(self, request: ParseRequest, result) -> ParsedArtifact:
    document = getattr(result, "document", result)
    version = "docling-runtime"
    return ParsedArtifact(
        document_id=UUID(request.document_id),
        pages=self._extract_pages(document),
        tables=self._extract_tables(document),
        provenance=ParserProvenance(
            parser_backend=self.backend_name,
            parser_version=version,
            profile=request.profile,
        ),
    )
```

Finally, change `parse()` to use `_parse_with_docling()` when no converter override is present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/integration/test_docling_parser_adapter.py -v`
Expected: PASS for injected-converter path and new failure-path tests.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/parsers/docling_backend.py apps/api/app/tests/integration/test_docling_parser_adapter.py
git commit -m "feat: add local runtime path for docling parser"
```

### Task 2: Runtime wiring for local storage-backed parser

**Files:**
- Modify: `apps/api/app/main.py`
- Test: `apps/api/app/tests/unit/test_parser_backends.py`

- [ ] **Step 1: Write failing test**

Add a test that proves the runtime parser can be constructed with a storage root:

```python
def test_docling_parser_accepts_storage_root(tmp_path: Path):
    parser = DoclingDocumentParser(storage_root=tmp_path)
    assert parser is not None
```

- [ ] **Step 2: Run the targeted test**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/unit/test_parser_backends.py -v`
Expected: FAIL before the constructor change, PASS after.

- [ ] **Step 3: Wire storage root into app startup**

Update `main.py` dispatcher construction block:

```python
    if settings.parser_backend:
        from pathlib import Path
        from app.services.parsers.docling_backend import DoclingDocumentParser
        from app.workflows.dispatcher import InProcessDispatcher

        storage_root = Path(settings.local_storage_dir) if settings.local_storage_dir else None
        parser = DoclingDocumentParser(storage_root=storage_root)
        app.state.dispatcher = InProcessDispatcher(parser=parser)
```

- [ ] **Step 4: Run targeted tests**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/unit/test_parser_backends.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/main.py apps/api/app/tests/unit/test_parser_backends.py
git commit -m "feat: wire local storage root into runtime docling parser"
```

### Task 3: Full verification

**Files:**
- No code changes unless verification reveals breakage

- [ ] **Step 1: Run parser-focused tests**

Run: `cd /djesys/code/RAG && python -m pytest apps/api/app/tests/integration/test_docling_parser_adapter.py apps/api/app/tests/unit/test_parser_backends.py -v`
Expected: PASS.

- [ ] **Step 2: Run full suite**

Run: `cd /djesys/code/RAG && python -m pytest --tb=short -q`
Expected: PASS.

- [ ] **Step 3: Update project memory if code landed cleanly**

Update:

- `docs/uber-rag/TASKS.md` — mark `Replace parser stubs with real Docling-backed conversion.` done
- `docs/uber-rag/PROJECT_STATE.md` — add a recent change row for real local Docling parsing

- [ ] **Step 4: Commit docs update**

```bash
git add docs/uber-rag/TASKS.md docs/uber-rag/PROJECT_STATE.md
git commit -m "docs: record real local docling parsing support"
```
