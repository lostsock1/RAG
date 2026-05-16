# Keycloak OIDC Phase 1 Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the temporary loopback-only dev auth path with a real Keycloak/OIDC-backed authentication path so Phase 1 can close honestly on backend auth.

**Architecture:** Keep the existing `RequestContext` boundary, but make `get_request_context()` resolve identity from a verified bearer token in `AUTH_MODE=oidc`. Parse tenant, user, roles, groups, and scopes from token claims, enforce issuer/audience checks, and keep `AUTH_MODE=dev` only as a local fallback. Route scope checks stay unchanged and continue to consume the resolved `RequestContext`.

**Tech Stack:** FastAPI, Pydantic, PyJWT or python-jose, Keycloak OIDC, pytest, Docker Compose

---

## File Structure Map

### Create
- `apps/api/app/core/oidc.py` — OIDC token verifier and JWKS/key handling boundary
- `apps/api/app/tests/unit/test_oidc_claim_mapping.py` — claim extraction and validation tests
- `apps/api/app/tests/integration/test_oidc_auth_flow.py` — protected-route auth integration tests using signed test tokens

### Modify
- `apps/api/app/core/config.py` — add OIDC settings
- `apps/api/app/core/security.py` — add `AUTH_MODE=oidc` path and claim-to-context mapping
- `apps/api/app/tests/integration/test_runtime_auth_startup.py` — keep dev-mode tests explicit and local-only
- `README.md` — add real local auth run instructions for Keycloak mode
- `docs/uber-rag/PROJECT_STATE.md` — record real OIDC auth landing when complete
- `docs/uber-rag/TASKS.md` — mark auth closeout done when verified

---

### Task 1: OIDC settings surface

**Files:**
- Modify: `apps/api/app/core/config.py`
- Test: `apps/api/app/tests/unit/test_oidc_claim_mapping.py`

- [ ] **Step 1: Write the failing settings test**

```python
from app.core.config import Settings


def test_oidc_settings_exist() -> None:
    settings = Settings(
        auth_mode="oidc",
        oidc_issuer_url="http://localhost:8080/realms/uber-rag",
        oidc_audience="uber-rag-api",
        oidc_client_id="uber-rag-api",
    )
    assert settings.auth_mode == "oidc"
    assert settings.oidc_issuer_url == "http://localhost:8080/realms/uber-rag"
    assert settings.oidc_audience == "uber-rag-api"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_oidc_claim_mapping.py::test_oidc_settings_exist -v`
Expected: FAIL because the OIDC settings fields do not exist.

- [ ] **Step 3: Add minimal OIDC settings**

```python
oidc_issuer_url: str | None = None
oidc_audience: str | None = None
oidc_client_id: str | None = None
oidc_jwks_url: str | None = None
oidc_username_claim: str = "preferred_username"
oidc_groups_claim: str = "groups"
oidc_roles_claim: str = "realm_access.roles"
oidc_scopes_claim: str = "scope"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_oidc_claim_mapping.py::test_oidc_settings_exist -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/core/config.py apps/api/app/tests/unit/test_oidc_claim_mapping.py
git commit -m "feat: add oidc auth settings"
```

---

### Task 2: Token verification boundary

**Files:**
- Create: `apps/api/app/core/oidc.py`
- Test: `apps/api/app/tests/unit/test_oidc_claim_mapping.py`

- [ ] **Step 1: Write the failing token-validation test**

```python
def test_decode_and_validate_token_rejects_wrong_audience() -> None:
    claims = {
        "sub": "11111111-1111-1111-1111-111111111111",
        "iss": "http://localhost:8080/realms/uber-rag",
        "aud": "wrong-audience",
        "scope": "documents:read",
    }
    with pytest.raises(ValueError, match="audience"):
        decode_and_validate_claims(
            claims,
            issuer="http://localhost:8080/realms/uber-rag",
            audience="uber-rag-api",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_oidc_claim_mapping.py::test_decode_and_validate_token_rejects_wrong_audience -v`
Expected: FAIL because `decode_and_validate_claims` does not exist.

- [ ] **Step 3: Implement the verification boundary**

```python
def decode_and_validate_claims(*, claims: dict, issuer: str, audience: str) -> dict:
    if claims.get("iss") != issuer:
        raise ValueError("issuer mismatch")
    aud = claims.get("aud")
    if aud != audience and not (isinstance(aud, list) and audience in aud):
        raise ValueError("audience mismatch")
    if "sub" not in claims:
        raise ValueError("subject missing")
    return claims
```

```python
class OidcTokenVerifier:
    def verify_bearer_token(self, token: str) -> dict:
        """Production implementation verifies signature and standard claims against Keycloak JWKS."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_oidc_claim_mapping.py::test_decode_and_validate_token_rejects_wrong_audience -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/core/oidc.py apps/api/app/tests/unit/test_oidc_claim_mapping.py
git commit -m "feat: add oidc token verification boundary"
```

---

### Task 3: Claim-to-RequestContext mapping

**Files:**
- Modify: `apps/api/app/core/security.py`
- Test: `apps/api/app/tests/unit/test_oidc_claim_mapping.py`

- [ ] **Step 1: Write the failing claim-mapping test**

```python
from app.core.request_context import RequestContext
from app.core.security import build_request_context_from_claims


def test_build_request_context_from_keycloak_claims() -> None:
    claims = {
        "sub": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "tenant-1",
        "groups": ["group-a", "group-b"],
        "realm_access": {"roles": ["editor"]},
        "scope": "documents:read documents:write",
    }
    context = build_request_context_from_claims(claims)
    assert isinstance(context, RequestContext)
    assert context.user_id == "11111111-1111-1111-1111-111111111111"
    assert context.group_ids == ["group-a", "group-b"]
    assert context.scopes == ["documents:read", "documents:write"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_oidc_claim_mapping.py::test_build_request_context_from_keycloak_claims -v`
Expected: FAIL because the mapping helper does not exist.

- [ ] **Step 3: Implement the mapping helper and OIDC route path**

```python
def build_request_context_from_claims(claims: dict) -> RequestContext:
    realm_access = claims.get("realm_access") or {}
    raw_scopes = claims.get("scope", "")
    return RequestContext(
        tenant_id=claims["tenant_id"],
        user_id=claims["sub"],
        group_ids=list(claims.get("groups") or []),
        roles=list(realm_access.get("roles") or []),
        scopes=[scope for scope in raw_scopes.split(" ") if scope],
    )
```

```python
if settings.auth_mode == "oidc":
    # extract bearer token, verify it, map claims to RequestContext
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_oidc_claim_mapping.py::test_build_request_context_from_keycloak_claims -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/core/security.py apps/api/app/tests/unit/test_oidc_claim_mapping.py
git commit -m "feat: map keycloak oidc claims into request context"
```

---

### Task 4: Protected-route integration with signed test tokens

**Files:**
- Create: `apps/api/app/tests/integration/test_oidc_auth_flow.py`
- Modify: `apps/api/app/core/security.py`
- Modify: `apps/api/app/core/oidc.py`

- [ ] **Step 1: Write the failing OIDC route integration test**

```python
def test_oidc_token_allows_document_list(monkeypatch) -> None:
    token = issue_test_token(
        sub="11111111-1111-1111-1111-111111111111",
        tenant_id="tenant-1",
        groups=["group-a"],
        roles=["editor"],
        scopes=["documents:read"],
    )
    response = client.get(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/api/app/tests/integration/test_oidc_auth_flow.py::test_oidc_token_allows_document_list -v`
Expected: FAIL because OIDC verification is not wired.

- [ ] **Step 3: Implement the minimal OIDC auth path**

```python
authorization: str | None = Header(default=None)
if not authorization or not authorization.startswith("Bearer "):
    raise HTTPException(status_code=401, detail="Missing bearer token")
token = authorization.removeprefix("Bearer ").strip()
claims = verifier.verify_bearer_token(token)
return build_request_context_from_claims(claims)
```

**Test helper direction:** use a deterministic local signing key in the test and monkeypatch the verifier/JWKS fetch so the test proves route behavior, not Keycloak network reachability.

- [ ] **Step 4: Run the OIDC integration test to verify it passes**

Run: `pytest apps/api/app/tests/integration/test_oidc_auth_flow.py::test_oidc_token_allows_document_list -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/tests/integration/test_oidc_auth_flow.py apps/api/app/core/security.py apps/api/app/core/oidc.py
git commit -m "feat: add oidc-protected route auth flow"
```

---

### Task 5: Scope, failure-path, and local docs closeout

**Files:**
- Modify: `apps/api/app/tests/integration/test_oidc_auth_flow.py`
- Modify: `apps/api/app/tests/integration/test_runtime_auth_startup.py`
- Modify: `README.md`
- Modify: `docs/uber-rag/PROJECT_STATE.md`
- Modify: `docs/uber-rag/TASKS.md`

- [ ] **Step 1: Write the failing scope/failure-path tests**

```python
def test_oidc_token_missing_scope_gets_403() -> None:
    token = issue_test_token(
        sub="11111111-1111-1111-1111-111111111111",
        tenant_id="tenant-1",
        groups=[],
        roles=["editor"],
        scopes=[],
    )
    response = client.get(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_oidc_wrong_issuer_gets_401() -> None:
    token = issue_test_token(
        sub="11111111-1111-1111-1111-111111111111",
        tenant_id="tenant-1",
        groups=[],
        roles=["editor"],
        scopes=["documents:read"],
        issuer="http://wrong-issuer",
    )
    response = client.get(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/api/app/tests/integration/test_oidc_auth_flow.py -v`
Expected: FAIL until the route uses verified OIDC claims consistently.

- [ ] **Step 3: Finish docs and closeout wording**

Update `README.md` with:

```text
For real Phase 1 auth verification, run Keycloak locally and set:
- AUTH_MODE=oidc
- OIDC_ISSUER_URL=http://localhost:8080/realms/uber-rag
- OIDC_AUDIENCE=uber-rag-api
```

Update `PROJECT_STATE.md` and `TASKS.md` to mark the auth seam complete only after the OIDC test suite passes.

- [ ] **Step 4: Run the full auth-focused backend suite**

Run: `pytest apps/api/app/tests/unit/test_oidc_claim_mapping.py apps/api/app/tests/integration/test_oidc_auth_flow.py apps/api/app/tests/integration/test_runtime_auth_startup.py apps/api/app/tests/integration/test_documents_list_acl.py apps/api/app/tests/integration/test_document_acl.py apps/api/app/tests/integration/test_documents_upload.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/tests/integration/test_oidc_auth_flow.py apps/api/app/tests/integration/test_runtime_auth_startup.py README.md docs/uber-rag/PROJECT_STATE.md docs/uber-rag/TASKS.md
git commit -m "feat: close phase 1 auth with keycloak oidc path"
```

---

## Self-review

- Spec coverage: this plan covers the strict Phase 1 blocker the user picked — replacing temporary dev auth with real Keycloak/OIDC-backed auth.
- Placeholder scan: no `TODO` or `TBD` markers remain.
- Type consistency: uses `tenant_id`, `user_id`, `groups`, `roles`, and `scopes` consistently with current `RequestContext` and security docs.
