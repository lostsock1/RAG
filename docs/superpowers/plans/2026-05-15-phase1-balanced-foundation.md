# Uber-RAG Phase 1 Balanced Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Uber-RAG Phase 1 as a gate-led foundation: close design gaps first, prove ACL/security and operational basics second, then deliver the first authenticated upload/list/UI slice.

**Architecture:** Implement Phase 1 in four gates. Gate A updates docs and freezes the Phase 1 contract. Gate B adds the minimum auth/schema/ACL/audit substrate. Gate C proves local operability and CI repeatability. Gate D adds the first product slice on top of the stabilized backend.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL, Keycloak OIDC/JWT, MinIO, Next.js, TypeScript, pytest, Docker Compose

---

## File Structure Map

### Create
- `docs/uber-rag/PHASE1_GATE_CHECKLIST.md` — gate checklist and exit criteria
- `apps/api/app/main.py` — FastAPI entrypoint
- `apps/api/app/api/router.py` — `/api/v1` router registration
- `apps/api/app/api/routes/health.py` — health endpoint
- `apps/api/app/api/routes/documents.py` — upload/list endpoints
- `apps/api/app/api/routes/document_acl.py` — ACL get/update endpoints
- `apps/api/app/core/config.py` — settings loader
- `apps/api/app/core/request_context.py` — typed auth context
- `apps/api/app/core/security.py` — Keycloak token seam
- `apps/api/app/db/base.py` — DB session/base
- `apps/api/app/db/models/__init__.py` — metadata import hub
- `apps/api/app/db/models/tenant.py`
- `apps/api/app/db/models/user.py`
- `apps/api/app/db/models/group.py`
- `apps/api/app/db/models/document.py`
- `apps/api/app/db/models/acl.py`
- `apps/api/app/db/models/audit.py`
- `apps/api/app/repositories/documents.py` — document queries and writes
- `apps/api/app/repositories/audit.py` — audit writes
- `apps/api/app/services/acl_service.py` — ACL filter builder and ACL update logic
- `apps/api/app/services/document_service.py` — upload/list orchestration
- `apps/api/app/services/storage.py` — MinIO adapter
- `apps/api/app/schemas/auth.py` — auth context schema types
- `apps/api/app/schemas/documents.py` — upload/list schemas
- `apps/api/app/schemas/acl.py` — ACL request/response schemas
- `apps/api/app/tests/unit/test_acl_service.py`
- `apps/api/app/tests/unit/test_request_context.py`
- `apps/api/app/tests/integration/test_health.py`
- `apps/api/app/tests/integration/test_migrations.py`
- `apps/api/app/tests/integration/test_documents_upload.py`
- `apps/api/app/tests/integration/test_documents_list_acl.py`
- `apps/api/app/tests/integration/test_document_acl.py`
- `tests/integration/test_acl_leakage_ci.py` — release-blocking wrapper
- `infra/docker/docker-compose.yml` — local dev stack
- `infra/migrations/alembic.ini`
- `infra/migrations/env.py`
- `infra/migrations/versions/20260515_0001_phase1_foundation.py`
- `packages/clients/typescript/src/api.ts` — public API client
- `apps/web/lib/api-client.ts`
- `apps/web/middleware.ts`
- `apps/web/app/login/page.tsx`
- `apps/web/app/upload/page.tsx`
- `apps/web/app/documents/page.tsx`
- `apps/web/components/upload-form.tsx`
- `apps/web/components/document-list.tsx`
- `.env.example`

### Modify
- `docs/uber-rag/PROJECT_STATE.md` — replace speed-first next-step wording with gate-led Phase 1
- `docs/uber-rag/TASKS.md` — align tasks with gate completion
- `docs/uber-rag/API_CONTRACT.md` — freeze Phase 1 endpoint subset
- `docs/uber-rag/DOMAIN_MODEL.md` — mark Phase 1 minimum schema subset
- `docs/uber-rag/SECURITY_ACL.md` — add explicit Gate A ACL test cases
- `README.md` — local setup instructions

---

### Task 1: Gate A memory reconciliation

**Files:**
- Create: `docs/uber-rag/PHASE1_GATE_CHECKLIST.md`
- Modify: `docs/uber-rag/PROJECT_STATE.md`
- Modify: `docs/uber-rag/TASKS.md`

- [ ] **Step 1: Write the failing doc coverage test**

```python
from pathlib import Path


def test_phase1_gate_checklist_exists() -> None:
    path = Path("docs/uber-rag/PHASE1_GATE_CHECKLIST.md")
    assert path.exists()
    text = path.read_text()
    assert "Gate A" in text
    assert "Gate B" in text
    assert "Gate C" in text
    assert "Gate D" in text
```

- [ ] **Step 2: Run the doc coverage test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_phase1_docs.py::test_phase1_gate_checklist_exists -v`

Expected: FAIL because the checklist file does not exist yet.

- [ ] **Step 3: Write the Phase 1 gate checklist and reconcile project memory**

```markdown
# Phase 1 Gate Checklist

## Gate A — Design closure
- [ ] Phase 1 endpoint subset frozen
- [ ] Phase 1 minimum schema subset frozen
- [ ] ACL rules translated into explicit tests
- [ ] ADR/doc gaps identified

## Gate B — Security/data foundation
- [ ] Request context seam implemented
- [ ] Initial migration landed
- [ ] ACL filter builder implemented
- [ ] Audit persistence implemented
- [ ] Leakage tests passing

## Gate C — Operational foundation
- [ ] Docker stack runs locally
- [ ] Config/env discipline documented
- [ ] Health checks green
- [ ] MinIO adapter wired
- [ ] CI baseline green

## Gate D — First product slice
- [ ] Upload works
- [ ] ACL read/update works
- [ ] Document list is ACL-filtered
- [ ] Minimal login/upload/list UI works
```

Also update `PROJECT_STATE.md` next-step wording to reference the gate-led plan and update `TASKS.md` so Phase 1 work is tracked by gate, not just by a flat list.

- [ ] **Step 4: Run the doc coverage test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_phase1_docs.py::test_phase1_gate_checklist_exists -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/uber-rag/PHASE1_GATE_CHECKLIST.md docs/uber-rag/PROJECT_STATE.md docs/uber-rag/TASKS.md apps/api/app/tests/unit/test_phase1_docs.py
git commit -m "docs: align project memory to gate-led phase 1"
```

---

### Task 2: Gate A contract freeze

**Files:**
- Modify: `docs/uber-rag/API_CONTRACT.md`
- Modify: `docs/uber-rag/DOMAIN_MODEL.md`
- Modify: `docs/uber-rag/SECURITY_ACL.md`

- [ ] **Step 1: Write the failing contract freeze test**

```python
from pathlib import Path


def test_phase1_contract_subset_is_documented() -> None:
    text = Path("docs/uber-rag/API_CONTRACT.md").read_text()
    assert "/api/v1/system/health" in text
    assert "/api/v1/documents/upload" in text
    assert "/api/v1/documents" in text
    assert "/api/v1/documents/{document_id}/acl" in text
```

- [ ] **Step 2: Run the contract freeze test to verify it fails if the subset is not explicit**

Run: `pytest apps/api/app/tests/unit/test_phase1_docs.py::test_phase1_contract_subset_is_documented -v`

Expected: FAIL if the contract subset is not clearly marked.

- [ ] **Step 3: Freeze the Gate A contract in docs**

```markdown
## Phase 1 frozen subset

- `GET /api/v1/system/health`
- `POST /api/v1/documents/upload`
- `GET /api/v1/documents`
- `GET /api/v1/documents/{document_id}/acl`
- `PUT /api/v1/documents/{document_id}/acl`
```

In `DOMAIN_MODEL.md`, explicitly mark the Phase 1 minimum subset:

```text
tenants
users
groups
user_groups
documents
acl_grants
acl_allowed_users
acl_allowed_groups
audit_events
```

In `SECURITY_ACL.md`, add explicit Gate A test cases for:
- disjoint-group isolation
- owner visibility
- explicit user grant visibility
- tenant visibility inside tenant only
- hidden docs omitted from counts/titles

- [ ] **Step 4: Run the contract freeze test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_phase1_docs.py::test_phase1_contract_subset_is_documented -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/uber-rag/API_CONTRACT.md docs/uber-rag/DOMAIN_MODEL.md docs/uber-rag/SECURITY_ACL.md apps/api/app/tests/unit/test_phase1_docs.py
git commit -m "docs: freeze phase 1 contract and schema subset"
```

---

### Task 3: Gate B auth seam

**Files:**
- Create: `apps/api/app/core/request_context.py`
- Create: `apps/api/app/core/security.py`
- Create: `apps/api/app/schemas/auth.py`
- Test: `apps/api/app/tests/unit/test_request_context.py`

- [ ] **Step 1: Write the failing request-context test**

```python
from app.core.request_context import RequestContext


def test_request_context_contains_acl_inputs() -> None:
    context = RequestContext(
        tenant_id="tenant-1",
        user_id="user-1",
        group_ids=["group-a"],
        roles=["editor"],
        scopes=["documents:read"],
    )
    assert context.tenant_id == "tenant-1"
    assert context.group_ids == ["group-a"]
```

- [ ] **Step 2: Run the request-context test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_request_context.py -v`

Expected: FAIL because `RequestContext` does not exist.

- [ ] **Step 3: Implement the typed auth seam**

```python
# apps/api/app/core/request_context.py
from pydantic import BaseModel


class RequestContext(BaseModel):
    tenant_id: str
    user_id: str
    group_ids: list[str]
    roles: list[str]
    scopes: list[str]
```

```python
# apps/api/app/core/security.py
from fastapi import HTTPException, status
from app.core.request_context import RequestContext


def get_request_context() -> RequestContext:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication not configured",
    )
```

- [ ] **Step 4: Run the request-context test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_request_context.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/core/request_context.py apps/api/app/core/security.py apps/api/app/schemas/auth.py apps/api/app/tests/unit/test_request_context.py
git commit -m "feat: add phase 1 auth request context seam"
```

---

### Task 4: Gate B initial schema and migration

**Files:**
- Create: `apps/api/app/db/base.py`
- Create: `apps/api/app/db/models/*.py`
- Create: `apps/api/app/db/models/__init__.py`
- Create: `infra/migrations/alembic.ini`
- Create: `infra/migrations/env.py`
- Create: `infra/migrations/versions/20260515_0001_phase1_foundation.py`
- Test: `apps/api/app/tests/integration/test_migrations.py`

- [ ] **Step 1: Write the failing migration test**

```python
def test_phase1_tables_exist(inspector) -> None:
    table_names = set(inspector.get_table_names())
    expected = {
        "tenants",
        "users",
        "groups",
        "user_groups",
        "documents",
        "acl_grants",
        "acl_allowed_users",
        "acl_allowed_groups",
        "audit_events",
    }
    assert expected.issubset(table_names)
```

- [ ] **Step 2: Run the migration test to verify it fails**

Run: `pytest apps/api/app/tests/integration/test_migrations.py -v`

Expected: FAIL because no migration exists yet.

- [ ] **Step 3: Implement the minimum schema exactly as frozen in Gate A**

```text
Create SQLAlchemy models and Alembic migration for:
- tenants
- users
- groups
- user_groups
- documents
- acl_grants
- acl_allowed_users
- acl_allowed_groups
- audit_events
```

Use the exact field names from `docs/uber-rag/DOMAIN_MODEL.md`; do not rename `tenant_id`, `owner_user_id`, `visibility`, `sensitivity`, or `source_hash`.

- [ ] **Step 4: Run the migration and verify test pass**

Run: `alembic -c infra/migrations/alembic.ini upgrade head && pytest apps/api/app/tests/integration/test_migrations.py -v`

Expected: migration succeeds and test PASSes.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/db infra/migrations apps/api/app/tests/integration/test_migrations.py
git commit -m "feat: add phase 1 schema and initial migration"
```

---

### Task 5: Gate B ACL filter builder and audit persistence

**Files:**
- Create: `apps/api/app/services/acl_service.py`
- Create: `apps/api/app/repositories/audit.py`
- Create: `apps/api/app/db/models/audit.py`
- Test: `apps/api/app/tests/unit/test_acl_service.py`

- [ ] **Step 1: Write the failing ACL filter test**

```python
from app.services.acl_service import build_document_acl_filter


def test_acl_filter_includes_owner_group_and_tenant_visibility() -> None:
    sql_filter = build_document_acl_filter(
        tenant_id="tenant-1",
        user_id="user-1",
        group_ids=["group-a"],
    )
    compiled = str(sql_filter)
    assert "tenant-1" in compiled
    assert "group-a" in compiled
    assert "tenant" in compiled
```

- [ ] **Step 2: Run the ACL filter test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_acl_service.py -v`

Expected: FAIL because the filter builder does not exist.

- [ ] **Step 3: Implement ACL filtering and audit write helpers**

```python
def build_document_acl_filter(tenant_id: str, user_id: str, group_ids: list[str]):
    """Return a SQLAlchemy boolean expression that enforces:
    - same tenant
    - owner access
    - explicit user grant access
    - matching allowed group access
    - tenant visibility within tenant only
    - no tombstoned documents
    """
```

```python
def write_audit_event(
    *,
    tenant_id: str,
    user_id: str | None,
    action: str,
    resource_type: str | None,
    resource_id: str | None,
    details: dict,
) -> None:
    ...
```

- [ ] **Step 4: Run the ACL filter test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_acl_service.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/acl_service.py apps/api/app/repositories/audit.py apps/api/app/tests/unit/test_acl_service.py
git commit -m "feat: add acl filter builder and audit persistence"
```

---

### Task 6: Gate C operational foundation

**Files:**
- Create: `infra/docker/docker-compose.yml`
- Create: `apps/api/app/core/config.py`
- Create: `apps/api/app/api/routes/health.py`
- Create: `apps/api/app/main.py`
- Create: `apps/api/app/api/router.py`
- Create: `.env.example`
- Modify: `README.md`
- Test: `apps/api/app/tests/integration/test_health.py`

- [ ] **Step 1: Write the failing health test**

```python
from fastapi.testclient import TestClient
from app.main import app


def test_healthcheck_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/system/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the health test to verify it fails**

Run: `pytest apps/api/app/tests/integration/test_health.py -v`

Expected: FAIL because the app shell is missing.

- [ ] **Step 3: Implement the operational shell**

```python
# apps/api/app/main.py
from fastapi import FastAPI
from app.api.router import api_router

app = FastAPI(title="Uber-RAG API", version="0.1.0")
app.include_router(api_router, prefix="/api/v1")
```

```python
# apps/api/app/api/routes/health.py
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
```

```yaml
# infra/docker/docker-compose.yml
services:
  postgres:
    image: postgres:17
  minio:
    image: minio/minio:latest
  keycloak:
    image: quay.io/keycloak/keycloak:26.2
```

- [ ] **Step 4: Run local stack and health test**

Run: `docker compose -f infra/docker/docker-compose.yml up -d && pytest apps/api/app/tests/integration/test_health.py -v`

Expected: containers start and test PASSes.

- [ ] **Step 5: Commit**

```bash
git add infra/docker/docker-compose.yml apps/api/app/main.py apps/api/app/api apps/api/app/core/config.py .env.example README.md apps/api/app/tests/integration/test_health.py
git commit -m "feat: add operational foundation for phase 1"
```

---

### Task 7: Gate D upload endpoint

**Files:**
- Create: `apps/api/app/services/storage.py`
- Create: `apps/api/app/services/document_service.py`
- Create: `apps/api/app/repositories/documents.py`
- Create: `apps/api/app/schemas/documents.py`
- Create: `apps/api/app/api/routes/documents.py`
- Test: `apps/api/app/tests/integration/test_documents_upload.py`

- [ ] **Step 1: Write the failing upload test**

```python
def test_upload_creates_document_and_default_acl(client, auth_headers, minio_stub) -> None:
    response = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "Sample"
    assert payload["source_hash"]
    assert payload["ingestion_status"] == "uploaded"
    assert minio_stub.last_put_object_key == payload["object_key"]
```

- [ ] **Step 2: Run the upload test to verify it fails**

Run: `pytest apps/api/app/tests/integration/test_documents_upload.py -v`

Expected: FAIL because the endpoint does not exist.

- [ ] **Step 3: Implement upload orchestration**

```python
@router.post("/upload", status_code=201, response_model=DocumentResponse)
async def upload_document(...):
    """Compute SHA-256, store original bytes in MinIO, insert document,
    create default owner ACL, and write a document.upload audit event."""
```

- [ ] **Step 4: Run the upload test to verify it passes**

Run: `pytest apps/api/app/tests/integration/test_documents_upload.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/storage.py apps/api/app/services/document_service.py apps/api/app/repositories/documents.py apps/api/app/schemas/documents.py apps/api/app/api/routes/documents.py apps/api/app/tests/integration/test_documents_upload.py
git commit -m "feat: add document upload flow"
```

---

### Task 8: Gate D ACL endpoints and ACL-filtered list

**Files:**
- Create: `apps/api/app/schemas/acl.py`
- Create: `apps/api/app/api/routes/document_acl.py`
- Modify: `apps/api/app/api/routes/documents.py`
- Modify: `apps/api/app/repositories/documents.py`
- Test: `apps/api/app/tests/integration/test_document_acl.py`
- Test: `apps/api/app/tests/integration/test_documents_list_acl.py`
- Test: `tests/integration/test_acl_leakage_ci.py`

- [ ] **Step 1: Write the failing list leakage test**

```python
def test_group_b_user_cannot_see_group_a_document(client, auth_headers_group_b, seeded_documents) -> None:
    response = client.get("/api/v1/documents", headers=auth_headers_group_b)
    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["items"]]
    assert "Group A Secret" not in titles
    assert "Group B Visible" in titles
```

- [ ] **Step 2: Run the ACL integration tests to verify they fail**

Run: `pytest apps/api/app/tests/integration/test_document_acl.py apps/api/app/tests/integration/test_documents_list_acl.py tests/integration/test_acl_leakage_ci.py -v`

Expected: FAIL because list filtering and ACL endpoints are missing.

- [ ] **Step 3: Implement ACL read/update and list filtering**

```python
GET /api/v1/documents/{document_id}/acl
PUT /api/v1/documents/{document_id}/acl
GET /api/v1/documents
```

Required behavior:
- owner or authorized admin can read/update ACL
- list endpoint applies `build_document_acl_filter(...)`
- hidden docs are omitted, not marked denied
- `acl.update` and `document.list` audit events are written

- [ ] **Step 4: Run the ACL integration tests to verify they pass**

Run: `pytest apps/api/app/tests/integration/test_document_acl.py apps/api/app/tests/integration/test_documents_list_acl.py tests/integration/test_acl_leakage_ci.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/schemas/acl.py apps/api/app/api/routes/document_acl.py apps/api/app/api/routes/documents.py apps/api/app/repositories/documents.py apps/api/app/tests/integration/test_document_acl.py apps/api/app/tests/integration/test_documents_list_acl.py tests/integration/test_acl_leakage_ci.py
git commit -m "feat: add document acl endpoints and filtered list"
```

---

### Task 9: Gate D minimal web client

**Files:**
- Create: `packages/clients/typescript/src/api.ts`
- Create: `apps/web/lib/api-client.ts`
- Create: `apps/web/middleware.ts`
- Create: `apps/web/app/login/page.tsx`
- Create: `apps/web/app/upload/page.tsx`
- Create: `apps/web/app/documents/page.tsx`
- Create: `apps/web/components/upload-form.tsx`
- Create: `apps/web/components/document-list.tsx`

- [ ] **Step 1: Write the failing API client test**

```ts
import { listDocuments } from "../src/api"

test("listDocuments calls the public API", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [] }) })
  await listDocuments(fetchMock, { baseUrl: "http://localhost:8000", token: "token" })
  expect(fetchMock).toHaveBeenCalledWith(
    "http://localhost:8000/api/v1/documents",
    expect.objectContaining({ method: "GET" }),
  )
})
```

- [ ] **Step 2: Run the client test to verify it fails**

Run: `pnpm test packages/clients/typescript/src/api.test.ts`

Expected: FAIL because the client does not exist.

- [ ] **Step 3: Implement the minimal UI flow**

```text
/login      -> auth entry point
/upload     -> multipart upload form using POST /api/v1/documents/upload
/documents  -> read-only list using GET /api/v1/documents
```

Rules:
- all data goes through the public API client
- no direct access to PostgreSQL, MinIO, or Keycloak internals
- show loading, empty, and error states

- [ ] **Step 4: Run web tests and manual smoke check**

Run: `pnpm test`

Manual check:
- log in
- upload one file
- confirm it appears on `/documents`

Expected: tests PASS and the three-page flow works locally.

- [ ] **Step 5: Commit**

```bash
git add packages/clients/typescript/src/api.ts apps/web/lib/api-client.ts apps/web/middleware.ts apps/web/app/login/page.tsx apps/web/app/upload/page.tsx apps/web/app/documents/page.tsx apps/web/components/upload-form.tsx apps/web/components/document-list.tsx
git commit -m "feat: add minimal phase 1 web client"
```

---

## Self-review

- Spec coverage: Gate A docs, Gate B auth/schema/ACL/audit, Gate C operability, Gate D first slice are all represented as tasks.
- Placeholder scan: no `TODO` or `TBD` placeholders remain.
- Type consistency: uses `tenant_id`, `user_id`, `group_ids`, `source_hash`, `visibility`, and `sensitivity` consistently with project memory.
