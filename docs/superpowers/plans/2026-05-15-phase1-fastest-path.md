# Phase 1 Fastest Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working Uber-RAG product slice: authenticated upload, stored original file, ACL-aware document list, audit logging, and a minimal UI.

**Architecture:** Start with the public FastAPI API and the minimum persistence model needed for auth, documents, ACL, and audit. Keep the frontend thin and API-only. Defer parsing, indexing, and retrieval until the authenticated document-management backbone works end to end.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL, Keycloak OIDC/JWT, MinIO, Next.js, TypeScript, pytest

---

## File Structure Map

### Create

- `apps/api/app/main.py` — FastAPI entrypoint and router registration
- `apps/api/app/api/router.py` — top-level API router for `/api/v1`
- `apps/api/app/api/routes/health.py` — health endpoint
- `apps/api/app/api/routes/documents.py` — upload and list endpoints
- `apps/api/app/api/routes/document_acl.py` — get/update document ACL endpoints
- `apps/api/app/core/config.py` — environment-backed settings
- `apps/api/app/core/security.py` — JWT validation and auth dependency boundary
- `apps/api/app/core/request_context.py` — typed request identity context
- `apps/api/app/db/base.py` — SQLAlchemy base and session factory exports
- `apps/api/app/db/models/tenant.py`
- `apps/api/app/db/models/user.py`
- `apps/api/app/db/models/group.py`
- `apps/api/app/db/models/document.py`
- `apps/api/app/db/models/acl.py`
- `apps/api/app/db/models/audit.py`
- `apps/api/app/db/models/__init__.py` — model imports for Alembic metadata
- `apps/api/app/repositories/documents.py` — document persistence and ACL-filtered queries
- `apps/api/app/repositories/audit.py` — audit write helpers
- `apps/api/app/services/storage.py` — MinIO adapter interface + implementation
- `apps/api/app/services/document_service.py` — upload orchestration
- `apps/api/app/services/acl_service.py` — ACL reads/writes and filter construction
- `apps/api/app/schemas/auth.py` — request context schema
- `apps/api/app/schemas/documents.py` — request/response models for document endpoints
- `apps/api/app/schemas/acl.py` — request/response models for ACL endpoints
- `apps/api/app/tests/conftest.py` — shared test fixtures
- `apps/api/app/tests/unit/test_acl_service.py` — ACL unit tests
- `apps/api/app/tests/integration/test_documents_upload.py` — upload API integration test
- `apps/api/app/tests/integration/test_documents_list_acl.py` — cross-group leakage test
- `apps/api/app/tests/integration/test_document_acl.py` — ACL update + audit integration test
- `infra/docker/docker-compose.yml` — local Postgres, MinIO, Keycloak, API, Web
- `infra/migrations/alembic.ini`
- `infra/migrations/env.py`
- `infra/migrations/versions/20260515_0001_phase1_foundation.py`
- `packages/clients/typescript/src/api.ts` — minimal typed API client used by web app
- `apps/web/app/login/page.tsx` — login entry page
- `apps/web/app/documents/page.tsx` — document list page
- `apps/web/app/upload/page.tsx` — upload page
- `apps/web/components/document-list.tsx`
- `apps/web/components/upload-form.tsx`
- `apps/web/lib/api-client.ts`
- `apps/web/middleware.ts` — auth gate wrapper
- `tests/integration/test_acl_leakage_ci.py` — release-blocking top-level leakage test wrapper
- `.env.example`
- `README.md` updates for local startup

### Modify

- `docs/uber-rag/PROJECT_STATE.md` — record Phase 1 work start and completed slice
- `docs/uber-rag/TASKS.md` — mark completed scaffold/foundation items as work lands

---

### Task 1: Repository scaffold and local dev stack

**Files:**
- Create: `apps/api/`, `apps/web/`, `packages/clients/`, `infra/docker/`, `infra/migrations/`, `tests/integration/`
- Create: `infra/docker/docker-compose.yml`
- Create: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Create the directory scaffold**

```text
apps/
  api/
  web/
services/
packages/
  clients/
infra/
  docker/
  migrations/
tests/
  integration/
```

- [ ] **Step 2: Add a local docker compose stack**

```yaml
services:
  postgres:
    image: postgres:17
    environment:
      POSTGRES_DB: uber_rag
      POSTGRES_USER: uber_rag
      POSTGRES_PASSWORD: uber_rag
    ports: ["5432:5432"]

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minio
      MINIO_ROOT_PASSWORD: minio123
    ports: ["9000:9000", "9001:9001"]

  keycloak:
    image: quay.io/keycloak/keycloak:26.2
    command: start-dev
    environment:
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: admin
    ports: ["8080:8080"]
```

- [ ] **Step 3: Add environment variables to `.env.example`**

```env
DATABASE_URL=postgresql+psycopg://uber_rag:uber_rag@localhost:5432/uber_rag
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minio
MINIO_SECRET_KEY=minio123
MINIO_BUCKET=documents
OIDC_ISSUER_URL=http://localhost:8080/realms/uber-rag
OIDC_AUDIENCE=uber-rag-api
WEB_BASE_URL=http://localhost:3000
API_BASE_URL=http://localhost:8000
```

- [ ] **Step 4: Verify the local stack starts**

Run: `docker compose -f infra/docker/docker-compose.yml up -d`

Expected: containers for Postgres, MinIO, and Keycloak report healthy/running.

---

### Task 2: FastAPI shell and API router

**Files:**
- Create: `apps/api/app/main.py`
- Create: `apps/api/app/api/router.py`
- Create: `apps/api/app/api/routes/health.py`
- Create: `apps/api/app/core/config.py`

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

- [ ] **Step 2: Run the health test and confirm failure**

Run: `pytest apps/api/app/tests/integration/test_health.py -v`

Expected: FAIL because `app.main` or route is missing.

- [ ] **Step 3: Implement the minimal FastAPI shell**

```python
# apps/api/app/main.py
from fastapi import FastAPI
from app.api.router import api_router

app = FastAPI(title="Uber-RAG API", version="0.1.0")
app.include_router(api_router, prefix="/api/v1")
```

```python
# apps/api/app/api/router.py
from fastapi import APIRouter
from app.api.routes.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/system", tags=["system"])
```

```python
# apps/api/app/api/routes/health.py
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run the health test and confirm pass**

Run: `pytest apps/api/app/tests/integration/test_health.py -v`

Expected: PASS.

---

### Task 3: Auth boundary and request identity context

**Files:**
- Create: `apps/api/app/core/security.py`
- Create: `apps/api/app/core/request_context.py`
- Create: `apps/api/app/schemas/auth.py`
- Modify: `apps/api/app/api/routes/documents.py`
- Test: `apps/api/app/tests/unit/test_security_context.py`

- [ ] **Step 1: Write the failing auth context test**

```python
from app.core.request_context import RequestContext


def test_request_context_captures_acl_identity() -> None:
    context = RequestContext(
        tenant_id="tenant-1",
        user_id="user-1",
        group_ids=["group-a", "group-b"],
        roles=["editor"],
        scopes=["documents:write"],
    )
    assert context.tenant_id == "tenant-1"
    assert context.group_ids == ["group-a", "group-b"]
```

- [ ] **Step 2: Run the auth context test and confirm failure**

Run: `pytest apps/api/app/tests/unit/test_security_context.py -v`

Expected: FAIL because `RequestContext` is undefined.

- [ ] **Step 3: Implement the typed request context and auth dependency seam**

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
from fastapi import Depends, HTTPException, status
from app.core.request_context import RequestContext


def get_request_context() -> RequestContext:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication not configured",
    )
```

**Implementation note:** the first pass may use a test override for `get_request_context`; wire real OIDC token verification after the seam is in place.

- [ ] **Step 4: Run the auth context test and confirm pass**

Run: `pytest apps/api/app/tests/unit/test_security_context.py -v`

Expected: PASS.

---

### Task 4: Database foundation and first migration

**Files:**
- Create: `apps/api/app/db/base.py`
- Create: `apps/api/app/db/models/{tenant,user,group,document,acl,audit}.py`
- Create: `apps/api/app/db/models/__init__.py`
- Create: `infra/migrations/alembic.ini`
- Create: `infra/migrations/env.py`
- Create: `infra/migrations/versions/20260515_0001_phase1_foundation.py`
- Test: `apps/api/app/tests/integration/test_migration_smoke.py`

- [ ] **Step 1: Write the failing migration smoke test**

```python
def test_phase1_tables_exist(inspector) -> None:
    table_names = set(inspector.get_table_names())
    assert {"tenants", "users", "groups", "user_groups", "documents", "acl_grants", "acl_allowed_users", "acl_allowed_groups", "audit_events"}.issubset(table_names)
```

- [ ] **Step 2: Run the migration smoke test and confirm failure**

Run: `pytest apps/api/app/tests/integration/test_migration_smoke.py -v`

Expected: FAIL because tables do not exist.

- [ ] **Step 3: Implement the minimum Phase 1 schema**

```python
# schema shape to include in SQLAlchemy + Alembic
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

**Required columns:** match `docs/uber-rag/DOMAIN_MODEL.md` for these tables; do not invent alternate names.

- [ ] **Step 4: Run migrations locally**

Run: `alembic -c infra/migrations/alembic.ini upgrade head`

Expected: database upgrades to the initial Phase 1 foundation revision.

- [ ] **Step 5: Run the migration smoke test and confirm pass**

Run: `pytest apps/api/app/tests/integration/test_migration_smoke.py -v`

Expected: PASS.

---

### Task 5: Upload endpoint with MinIO storage and hashing

**Files:**
- Create: `apps/api/app/services/storage.py`
- Create: `apps/api/app/services/document_service.py`
- Create: `apps/api/app/repositories/documents.py`
- Create: `apps/api/app/schemas/documents.py`
- Create: `apps/api/app/api/routes/documents.py`
- Test: `apps/api/app/tests/integration/test_documents_upload.py`

- [ ] **Step 1: Write the failing upload integration test**

```python
def test_upload_creates_document_record_and_object(client, auth_headers, minio_stub) -> None:
    response = client.post(
        "/api/v1/documents/upload",
        headers=auth_headers,
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"title": "Sample", "source_type": "loose_document"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "Sample"
    assert payload["ingestion_status"] == "uploaded"
    assert payload["source_hash"]
    assert minio_stub.last_put_object_key == payload["object_key"]
```

- [ ] **Step 2: Run the upload integration test and confirm failure**

Run: `pytest apps/api/app/tests/integration/test_documents_upload.py -v`

Expected: FAIL because upload endpoint is missing.

- [ ] **Step 3: Implement the upload API contract**

```python
@router.post("/upload", status_code=201, response_model=DocumentResponse)
async def upload_document(
    file: UploadFile,
    title: str,
    source_type: Literal["book", "loose_document"],
    context: RequestContext = Depends(get_request_context),
) -> DocumentResponse:
    return await document_service.create_uploaded_document(
        context=context,
        file=file,
        title=title,
        source_type=source_type,
    )
```

**Required behavior:**
- compute SHA-256 source hash
- persist `documents` row
- create default `acl_grants` row owned by uploader
- store original bytes in MinIO using stable object key
- return created document metadata

- [ ] **Step 4: Run the upload integration test and confirm pass**

Run: `pytest apps/api/app/tests/integration/test_documents_upload.py -v`

Expected: PASS.

---

### Task 6: ACL read/update and audit log writes

**Files:**
- Create: `apps/api/app/services/acl_service.py`
- Create: `apps/api/app/repositories/audit.py`
- Create: `apps/api/app/schemas/acl.py`
- Create: `apps/api/app/api/routes/document_acl.py`
- Test: `apps/api/app/tests/unit/test_acl_service.py`
- Test: `apps/api/app/tests/integration/test_document_acl.py`

- [ ] **Step 1: Write the failing ACL service unit test**

```python
def test_acl_filter_allows_owner_and_group_members() -> None:
    sql_filter = build_document_acl_filter(
        tenant_id="tenant-1",
        user_id="user-1",
        group_ids=["group-a"],
    )
    compiled = str(sql_filter)
    assert "tenant-1" in compiled
    assert "group-a" in compiled
```

- [ ] **Step 2: Run the ACL service test and confirm failure**

Run: `pytest apps/api/app/tests/unit/test_acl_service.py -v`

Expected: FAIL because ACL filter builder is missing.

- [ ] **Step 3: Implement ACL endpoints and audit writes**

```python
GET /api/v1/documents/{document_id}/acl
PUT /api/v1/documents/{document_id}/acl
```

**Required behavior:**
- owner or authorized admin can read/update ACL
- ACL update writes `acl.update` audit event
- response includes `visibility`, `sensitivity`, `allowed_user_ids`, `allowed_group_ids`, `expires_at`
- document upload writes `document.upload` audit event
- document list writes `document.list` audit event with filters applied and result count

- [ ] **Step 4: Run ACL tests and confirm pass**

Run: `pytest apps/api/app/tests/unit/test_acl_service.py apps/api/app/tests/integration/test_document_acl.py -v`

Expected: PASS.

---

### Task 7: ACL-filtered document list and release-blocking leakage test

**Files:**
- Modify: `apps/api/app/api/routes/documents.py`
- Modify: `apps/api/app/repositories/documents.py`
- Create: `apps/api/app/tests/integration/test_documents_list_acl.py`
- Create: `tests/integration/test_acl_leakage_ci.py`

- [ ] **Step 1: Write the failing cross-group leakage test**

```python
def test_user_cannot_list_documents_from_other_group(client, seeded_documents, auth_headers_for_group_b) -> None:
    response = client.get("/api/v1/documents", headers=auth_headers_for_group_b)
    assert response.status_code == 200

    titles = [item["title"] for item in response.json()["items"]]
    assert "Group A Secret" not in titles
    assert "Group B Visible" in titles
```

- [ ] **Step 2: Run the leakage test and confirm failure**

Run: `pytest apps/api/app/tests/integration/test_documents_list_acl.py -v`

Expected: FAIL because list filtering is missing or too permissive.

- [ ] **Step 3: Implement ACL-filtered pagination in the list endpoint**

```python
@router.get("", response_model=DocumentListResponse)
def list_documents(
    page: int = 1,
    page_size: int = 20,
    context: RequestContext = Depends(get_request_context),
) -> DocumentListResponse:
    return document_service.list_documents(context=context, page=page, page_size=page_size)
```

**Required filtering rules:**
- always constrain by `tenant_id`
- owner sees owned docs
- explicit user grant sees doc
- matching allowed group sees doc
- `visibility=tenant` visible only within tenant
- tombstoned docs excluded
- do not leak hidden counts or titles

- [ ] **Step 4: Add the CI wrapper test command**

Run target: `pytest tests/integration/test_acl_leakage_ci.py -v`

Expected: PASS and suitable for required CI gate.

- [ ] **Step 5: Run the full API test set for this slice**

Run: `pytest apps/api/app/tests/unit apps/api/app/tests/integration tests/integration/test_acl_leakage_ci.py -v`

Expected: PASS.

---

### Task 8: Minimal web UI for login, upload, and read-only document list

**Files:**
- Create: `packages/clients/typescript/src/api.ts`
- Create: `apps/web/lib/api-client.ts`
- Create: `apps/web/middleware.ts`
- Create: `apps/web/app/login/page.tsx`
- Create: `apps/web/app/upload/page.tsx`
- Create: `apps/web/app/documents/page.tsx`
- Create: `apps/web/components/upload-form.tsx`
- Create: `apps/web/components/document-list.tsx`

- [ ] **Step 1: Write the failing API client smoke test**

```ts
import { listDocuments } from "../src/api"

test("listDocuments requests the public API", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [] }) })
  await listDocuments(fetchMock, { baseUrl: "http://localhost:8000", token: "token" })
  expect(fetchMock).toHaveBeenCalledWith(
    "http://localhost:8000/api/v1/documents",
    expect.objectContaining({ method: "GET" }),
  )
})
```

- [ ] **Step 2: Run the client test and confirm failure**

Run: `pnpm test packages/clients/typescript/src/api.test.ts`

Expected: FAIL because the client does not exist.

- [ ] **Step 3: Implement the minimal UI flow**

```text
/login      -> start auth flow
/upload     -> multipart upload form calling POST /api/v1/documents/upload
/documents  -> read-only paginated list calling GET /api/v1/documents
```

**Required UI rules:**
- all data flows through the public API client
- no direct storage/database access
- show loading, empty, and denied/error states
- keep UI read-only except upload in this slice

- [ ] **Step 4: Run the web tests and a local manual smoke check**

Run: `pnpm test`

Manual check:
- log in
- upload one file
- confirm it appears in `/documents`

Expected: tests pass and the three-page flow works locally.

---

### Task 9: Memory updates and phase handoff

**Files:**
- Modify: `docs/uber-rag/PROJECT_STATE.md`
- Modify: `docs/uber-rag/TASKS.md`

- [ ] **Step 1: Update project state after the slice lands**

Record:
- repo scaffold created
- FastAPI shell live
- auth seam in place
- Phase 1 schema migrated
- upload/list/ACL/audit slice working
- ACL leakage CI gate added

- [ ] **Step 2: Update task statuses**

Mark complete where applicable:
- Create backend app skeleton
- Create frontend app skeleton
- Add docker compose for local services
- Define auth middleware
- Implement public API skeleton with OpenAPI docs

- [ ] **Step 3: Define the next handoff target**

Next implementation plan should start with:
- ingestion job table
- parse/index job endpoints
- Docling parser adapter
- quality report generation

---

## Self-review

- Spec coverage: covers the fastest-path slice the user approved: scaffold, auth, schema, upload, ACL list, audit, minimal UI.
- Placeholder scan: no `TODO`/`TBD` markers intentionally left in task instructions.
- Type consistency: uses `tenant_id`, `user_id`, `group_ids`, `source_type`, `visibility`, and `sensitivity` names consistently with project memory.
