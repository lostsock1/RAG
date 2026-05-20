# Search Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject whitespace-only search queries and make source-viewer focus marking stable for equivalent UUID strings.

**Architecture:** Keep the fix narrow. Query validation belongs in the `SearchRequest` schema so invalid blank input fails before routing or retrieval. Source-viewer focus marking stays in the repository response shaping path, but the incoming `chunk_id` must be normalized to the same canonical identifier format as stored chunk rows before `is_focus` is computed.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, pytest

---

## File structure

- Modify: `apps/api/app/schemas/search.py` — add trim-aware query validation to `SearchRequest`.
- Modify: `apps/api/app/repositories/search_sources.py` — normalize requested `chunk_id` before `is_focus` comparison.
- Modify: `apps/api/app/tests/integration/test_search_route.py` — add the blank-query regression at the public API layer.
- Modify: `apps/api/app/tests/unit/test_search_sources_repository.py` — add the focus-normalization regression at the repository layer.
- Modify: `docs/uber-rag/PROJECT_STATE.md` — record the shipped polish slice after implementation and verification.

### Task 1: Reject whitespace-only `/search` queries

**Files:**
- Modify: `apps/api/app/schemas/search.py`
- Modify: `apps/api/app/tests/integration/test_search_route.py`

- [ ] **Step 1: Write the failing integration test**

```python
def test_search_rejects_whitespace_only_query(seeded_search_documents: dict[str, str]) -> None:
    client = make_client(
        RequestContext(
            tenant_id=seeded_search_documents['tenant_id'],
            user_id=seeded_search_documents['user_b_id'],
            group_ids=[seeded_search_documents['group_b_id']],
            roles=['editor'],
            scopes=['documents:read'],
        ),
        RetrieverStub(hits=[]),
    )

    response = client.post('/api/v1/search', json={'query': '   ', 'top_k': 5})

    assert response.status_code == 422
    assert 'query' in response.text.lower()
```

- [ ] **Step 2: Run the test to verify RED**

Run: `pytest apps/api/app/tests/integration/test_search_route.py -k whitespace_only_query -v`
Expected: FAIL because the route currently accepts whitespace-only input.

- [ ] **Step 3: Implement minimal trim-aware schema validation**

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)

    @field_validator('query')
    @classmethod
    def validate_query_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('query must contain non-whitespace characters')
        return value
```

- [ ] **Step 4: Run the test to verify GREEN**

Run: `pytest apps/api/app/tests/integration/test_search_route.py -k whitespace_only_query -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/schemas/search.py apps/api/app/tests/integration/test_search_route.py
git commit -m "fix: reject blank search queries"
```

### Task 2: Normalize focus-chunk comparison in source viewer

**Files:**
- Modify: `apps/api/app/repositories/search_sources.py`
- Modify: `apps/api/app/tests/unit/test_search_sources_repository.py`

- [ ] **Step 1: Write the failing repository test**

```python
def test_get_source_slice_by_chunk_id_marks_focus_after_identifier_normalization() -> None:
    with TemporaryDirectory() as tmp_dir:
        database_url = f"sqlite:///{Path(tmp_dir) / 'search-sources-focus.db'}"
        engine = create_engine(database_url)

        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE documents (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_size_bytes INTEGER NOT NULL,
                    object_key TEXT NOT NULL,
                    ingestion_status TEXT NOT NULL,
                    is_tombstoned BOOLEAN NOT NULL DEFAULT 0,
                    created_at TEXT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE acl_grants (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    expires_at TEXT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE acl_allowed_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    acl_grant_id TEXT NOT NULL,
                    group_id TEXT NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    unit_type TEXT NOT NULL,
                    heading_path TEXT NOT NULL,
                    page_start INTEGER NULL,
                    page_end INTEGER NULL,
                    text TEXT NOT NULL,
                    parent_id TEXT NULL,
                    chunk_index INTEGER NOT NULL,
                    is_tombstoned BOOLEAN NOT NULL DEFAULT 0,
                    created_at TEXT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO documents (id, tenant_id, owner_user_id, title, source_type, source_hash, file_name, file_size_bytes, object_key, ingestion_status, is_tombstoned)
                VALUES ('11111111111111111111111111111111', '33333333333333333333333333333333', '44444444444444444444444444444444', 'Visible', 'loose_document', 'hash-visible', 'visible.txt', 1, 'documents/visible.txt', 'completed', 0)
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO acl_grants (id, document_id, tenant_id, owner_user_id, visibility, sensitivity, expires_at)
                VALUES ('acl-visible', '11111111111111111111111111111111', '33333333333333333333333333333333', '44444444444444444444444444444444', 'group', 'internal', NULL)
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO acl_allowed_groups (acl_grant_id, group_id)
                VALUES ('acl-visible', '77777777777777777777777777777777')
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO chunks (id, document_id, unit_type, heading_path, page_start, page_end, text, parent_id, chunk_index, is_tombstoned)
                VALUES ('11111111111111111111111111111111', '11111111111111111111111111111111', 'paragraph', '["Root"]', 1, 1, 'visible text', NULL, 0, 0)
                """
            )

        session_factory.configure(bind=engine)
        try:
            result = get_source_slice_by_chunk_id(
                chunk_id='11111111-1111-1111-1111-111111111111',
                tenant_id='33333333333333333333333333333333',
                user_id='66666666666666666666666666666666',
                group_ids=['77777777777777777777777777777777'],
                context_window=1,
            )
        finally:
            session_factory.configure(bind=None)
            engine.dispose()

    assert result is not None
    assert [item['is_focus'] for item in result['items']] == [True]
```

- [ ] **Step 2: Run the test to verify RED**

Run: `pytest apps/api/app/tests/unit/test_search_sources_repository.py -k identifier_normalization -v`
Expected: FAIL because `is_focus` still compares normalized stored IDs against the raw requested `chunk_id`.

- [ ] **Step 3: Implement minimal identifier normalization**

```python
def get_source_slice_by_chunk_id(...):
    normalized_chunk_id = _normalize_identifier(chunk_id)
    ...
    return {
        ...
        'items': [
            {
                'chunk_id': _normalize_identifier(row['id']),
                ...
                'is_focus': _normalize_identifier(row['id']) == normalized_chunk_id,
            }
            for row in rows
        ],
    }
```

- [ ] **Step 4: Run the test to verify GREEN**

Run: `pytest apps/api/app/tests/unit/test_search_sources_repository.py -k identifier_normalization -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/repositories/search_sources.py apps/api/app/tests/unit/test_search_sources_repository.py
git commit -m "fix: normalize source viewer focus ids"
```

### Task 3: Verify, document, and review the polish slice

**Files:**
- Modify: `docs/uber-rag/PROJECT_STATE.md`

- [ ] **Step 1: Run the focused regression suite**

Run: `pytest apps/api/app/tests/integration/test_search_route.py apps/api/app/tests/unit/test_search_sources_repository.py apps/api/app/tests/integration/test_search_source_viewer.py -v`
Expected: PASS

- [ ] **Step 2: Run the broader Phase 3 search suite**

Run: `pytest apps/api/app/tests/unit/test_query_router.py apps/api/app/tests/unit/test_fusion.py apps/api/app/tests/unit/test_opensearch_retriever.py apps/api/app/tests/unit/test_qdrant_retriever.py apps/api/app/tests/unit/test_hybrid_retriever.py apps/api/app/tests/unit/test_search_service.py apps/api/app/tests/unit/test_search_sources_repository.py apps/api/app/tests/unit/test_qdrant_indexer.py apps/api/app/tests/unit/test_opensearch_indexer.py apps/api/app/tests/unit/test_search_runtime.py apps/api/app/tests/integration/test_search_route.py apps/api/app/tests/integration/test_search_source_viewer.py apps/api/app/tests/unit/test_phase1_docs.py -q`
Expected: PASS

- [ ] **Step 3: Update project memory**

```markdown
- Search polish slice landed: blank-query rejection and source-viewer focus normalization
- Verification command/result recorded
```

- [ ] **Step 4: Request mandatory reviewer audit**

Run: dispatch `RAG/uber-rag-reviewer` on the final diff.
Expected: PASS or PASS WITH NITS before claiming completion.

- [ ] **Step 5: Commit**

```bash
git add docs/uber-rag/PROJECT_STATE.md
git commit -m "docs: record search polish slice"
```

## Self-review

- Spec coverage: both approved fixes are represented with direct tests and minimal code changes.
- Placeholder scan: no TODO/TBD markers or undefined helper references remain.
- Type consistency: the plan uses the existing `_normalize_identifier(...)` path and keeps `SearchRequest.query` as `str` throughout.
