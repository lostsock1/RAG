# Keycloak JWKS Verifier Mini-Scope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement real JWKS-based Keycloak token verification so the Phase 1 auth blocker can be closed honestly.

**Architecture:** Keep the existing `AUTH_MODE=oidc` branch and `RequestContext` mapping, but replace the verifier stub with a real JWKS-backed verification path. The verifier should discover or use a configured JWKS URL, select the correct key by `kid`, verify signature and standard claims, and refresh JWKS on key miss. Route scope enforcement remains unchanged.

**Tech Stack:** FastAPI, PyJWT, Keycloak OIDC/JWKS, Pydantic, pytest

---

## File Structure Map

### Create
- `apps/api/app/tests/unit/test_oidc_jwks.py` — pure JWKS selection and refresh tests

### Modify
- `apps/api/app/core/oidc.py` — implement JWKS fetch, cache, `kid` selection, and signature verification
- `apps/api/app/core/config.py` — keep only the OIDC settings actually used by the verifier or wire them
- `apps/api/app/tests/integration/test_oidc_auth_flow.py` — replace direct verifier monkeypatching with JWKS-backed local verification
- `README.md` — update auth verification instructions only after JWKS path works
- `docs/uber-rag/PROJECT_STATE.md` — downgrade/upgrade wording based on real verifier completion
- `docs/uber-rag/TASKS.md` — mark auth closeout done only when live JWKS-backed tests pass

---

### Task 1: JWKS settings and discovery contract

**Files:**
- Modify: `apps/api/app/core/config.py`
- Create: `apps/api/app/tests/unit/test_oidc_jwks.py`

- [ ] **Step 1: Write the failing settings/discovery test**

```python
from app.core.config import Settings


def test_oidc_jwks_settings_can_be_configured() -> None:
    settings = Settings(
        auth_mode="oidc",
        oidc_issuer_url="http://localhost:8080/realms/uber-rag",
        oidc_audience="uber-rag-api",
        oidc_jwks_url="http://localhost:8080/realms/uber-rag/protocol/openid-connect/certs",
    )
    assert settings.oidc_jwks_url == "http://localhost:8080/realms/uber-rag/protocol/openid-connect/certs"
```

- [ ] **Step 2: Run test to verify it fails or is incomplete**

Run: `pytest apps/api/app/tests/unit/test_oidc_jwks.py::test_oidc_jwks_settings_can_be_configured -v`
Expected: FAIL or reveal that the settings are present but not wired into any verifier path.

- [ ] **Step 3: Ensure the verifier-facing settings are explicit and minimal**

```python
oidc_issuer_url: str | None = None
oidc_audience: str | None = None
oidc_jwks_url: str | None = None
```

If other exposed OIDC settings are not used by the verifier, remove or clearly defer them in the same task.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_oidc_jwks.py::test_oidc_jwks_settings_can_be_configured -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/core/config.py apps/api/app/tests/unit/test_oidc_jwks.py
git commit -m "feat: define minimal jwks verifier settings"
```

---

### Task 2: Key selection by `kid`

**Files:**
- Modify: `apps/api/app/core/oidc.py`
- Modify: `apps/api/app/tests/unit/test_oidc_jwks.py`

- [ ] **Step 1: Write the failing key-selection test**

```python
def test_select_jwk_by_kid_returns_matching_key() -> None:
    jwks = {
        "keys": [
            {"kid": "key-a", "kty": "RSA", "n": "a", "e": "AQAB"},
            {"kid": "key-b", "kty": "RSA", "n": "b", "e": "AQAB"},
        ]
    }
    key = select_jwk_by_kid(jwks=jwks, kid="key-b")
    assert key["kid"] == "key-b"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_oidc_jwks.py::test_select_jwk_by_kid_returns_matching_key -v`
Expected: FAIL because the selector does not exist.

- [ ] **Step 3: Implement `kid` selection and failure handling**

```python
def select_jwk_by_kid(*, jwks: dict, kid: str) -> dict:
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    raise ValueError(f"No JWKS key found for kid={kid}")
```

Also reject tokens whose header has no `kid`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_oidc_jwks.py::test_select_jwk_by_kid_returns_matching_key -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/core/oidc.py apps/api/app/tests/unit/test_oidc_jwks.py
git commit -m "feat: select jwks verification key by kid"
```

---

### Task 3: JWKS fetch, cache, and refresh-on-miss

**Files:**
- Modify: `apps/api/app/core/oidc.py`
- Modify: `apps/api/app/tests/unit/test_oidc_jwks.py`

- [ ] **Step 1: Write the failing refresh-on-miss test**

```python
def test_verifier_refreshes_jwks_when_kid_missing(monkeypatch) -> None:
    first = {"keys": [{"kid": "old-key", "kty": "RSA", "n": "a", "e": "AQAB"}]}
    second = {"keys": [{"kid": "new-key", "kty": "RSA", "n": "b", "e": "AQAB"}]}
    calls = iter([first, second])

    verifier = OidcTokenVerifier()
    monkeypatch.setattr(verifier, "_fetch_jwks", lambda: next(calls))

    key = verifier._resolve_jwk_for_kid("new-key")
    assert key["kid"] == "new-key"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/api/app/tests/unit/test_oidc_jwks.py::test_verifier_refreshes_jwks_when_kid_missing -v`
Expected: FAIL because there is no cache/refresh path.

- [ ] **Step 3: Implement minimal in-memory JWKS cache**

```python
class OidcTokenVerifier:
    def __init__(self) -> None:
        self._jwks_cache: dict | None = None

    def _resolve_jwk_for_kid(self, kid: str) -> dict:
        if self._jwks_cache is None:
            self._jwks_cache = self._fetch_jwks()
        try:
            return select_jwk_by_kid(jwks=self._jwks_cache, kid=kid)
        except ValueError:
            self._jwks_cache = self._fetch_jwks()
            return select_jwk_by_kid(jwks=self._jwks_cache, kid=kid)
```

**Do not** implement an elaborate cache invalidation system in Phase 1.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest apps/api/app/tests/unit/test_oidc_jwks.py::test_verifier_refreshes_jwks_when_kid_missing -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/core/oidc.py apps/api/app/tests/unit/test_oidc_jwks.py
git commit -m "feat: cache and refresh jwks on key miss"
```

---

### Task 4: Real signature verification using JWKS-derived key

**Files:**
- Modify: `apps/api/app/core/oidc.py`
- Modify: `apps/api/app/tests/integration/test_oidc_auth_flow.py`

- [ ] **Step 1: Write the failing unknown-`kid` integration test**

```python
def test_oidc_unknown_kid_gets_401(monkeypatch) -> None:
    token = issue_test_token(..., kid="missing-key")
    response = client.get(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/api/app/tests/integration/test_oidc_auth_flow.py::test_oidc_unknown_kid_gets_401 -v`
Expected: FAIL because the verifier does not yet perform real JWKS key resolution.

- [ ] **Step 3: Implement JWKS-backed verification**

```python
header = jwt.get_unverified_header(token)
kid = header.get("kid")
if not kid:
    raise ValueError("token kid is missing")

jwk = self._resolve_jwk_for_kid(kid)
public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
claims = jwt.decode(
    token,
    key=public_key,
    algorithms=["RS256"],
    audience=settings.oidc_audience,
    issuer=settings.oidc_issuer_url,
)
```

Prefer a single accepted algorithm (`RS256`) unless Keycloak config proves otherwise.

- [ ] **Step 4: Run the OIDC integration tests to verify they pass**

Run: `pytest apps/api/app/tests/integration/test_oidc_auth_flow.py -v`
Expected: PASS for valid token, missing scope, wrong issuer, and unknown `kid` failure path.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/core/oidc.py apps/api/app/tests/integration/test_oidc_auth_flow.py
git commit -m "feat: verify oidc bearer tokens against jwks"
```

---

### Task 5: Docs truth and closeout verification

**Files:**
- Modify: `README.md`
- Modify: `docs/uber-rag/PROJECT_STATE.md`
- Modify: `docs/uber-rag/TASKS.md`

- [ ] **Step 1: Write the failing docs-truth test**

```python
from pathlib import Path


def test_project_state_does_not_claim_oidc_complete_before_jwks_runtime_exists() -> None:
    text = Path("docs/uber-rag/PROJECT_STATE.md").read_text()
    assert "JWKS" in text
```
```

- [ ] **Step 2: Run test to verify it fails or exposes stale wording**

Run: `pytest apps/api/app/tests/unit/test_oidc_jwks.py::test_project_state_does_not_claim_oidc_complete_before_jwks_runtime_exists -v`
Expected: FAIL or expose that docs still over/under-claim the auth state.

- [ ] **Step 3: Update docs only after verifier works**

`README.md` must say:

```text
Real Phase 1 OIDC verification requires:
- AUTH_MODE=oidc
- OIDC_ISSUER_URL=...
- OIDC_AUDIENCE=...
- OIDC_JWKS_URL=... (or issuer-based discovery if implemented)
```

`PROJECT_STATE.md` and `TASKS.md` must distinguish between:
- signed-token route tests
- live JWKS-backed verifier completion

- [ ] **Step 4: Run the full auth verifier suite**

Run: `pytest apps/api/app/tests/unit/test_oidc_claim_mapping.py apps/api/app/tests/unit/test_oidc_jwks.py apps/api/app/tests/integration/test_oidc_auth_flow.py apps/api/app/tests/integration/test_runtime_auth_startup.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/uber-rag/PROJECT_STATE.md docs/uber-rag/TASKS.md apps/api/app/tests/unit/test_oidc_jwks.py
git commit -m "docs: close phase 1 oidc verifier truthfully"
```

---

## Self-review

- Spec coverage: covers the exact remaining auth blocker — real JWKS-backed verification instead of monkeypatched acceptance.
- Placeholder scan: no `TODO` or `TBD` markers remain.
- Type consistency: keeps `tenant_id`, `sub`, `groups`, `realm_access.roles`, and `scope` aligned with the existing `RequestContext` mapping.
