# Phase 1 + Phase 2 — Audit findings and coding-agent instructions

> **Status:** audit complete 2026-05-23. Phases 1 and 2 are marked done in
> `docs/uber-rag/TASKS.md` and have a 203/203 green test suite, but the code
> still carries a handful of real bugs, ACL/storage gaps, and operational
> hazards that should be closed before Phase 3 retrieval is hardened or new
> work depends on it. Items are graded **P0 (correctness/security)**, **P1
> (correctness gap, no immediate failure mode in tests)**, **P2 (operability /
> performance)**. Out-of-scope items are listed at the end.

## How to work this list

1. Pick one item, complete it on its own branch, run the suite (`pytest
   apps/api/app/tests/ -v` and the eval/integration suites), and open a PR.
2. Each fix must include the test that fails before the patch and passes
   after. The acceptance criteria below name that test.
3. For any ACL-touching item (P0-1, P1-3, P1-6) include an ACL leakage
   regression test per `DEVELOPMENT_RULES.md` "No ACL-touching feature
   without a leakage test".
4. Do **not** bundle items into one PR unless they share a file and
   acceptance criterion. They are intentionally separable.

---

## P0 — Correctness and security bugs (fix first)

### P0-1. Dead `try/except` block in `security.py` is leftover from refactor

- **File:** `apps/api/app/core/security.py`
- **Lines:** 34-45
- **Symptom:** `_get_nested_claim` returns on line 40, then lines 42-45 are
  a stray `try/except` that references an undefined `host` variable and is
  unreachable. It looks like the body of `_is_loopback_client_host` was
  duplicated during a refactor.
- **Fix:** delete lines 42-45 (the `try: return ip_address(host).is_loopback
  / except ValueError: return False` block immediately after
  `_get_nested_claim`).
- **Acceptance:**
  - File parses cleanly under `ruff` and `mypy`.
  - Existing `test_oidc_claim_mapping.py` still passes.
  - Add `apps/api/app/tests/unit/test_security_static.py` that asserts
    `_get_nested_claim` has no unreachable code (e.g. by re-importing the
    function and asserting `inspect.getsource(...)` does not contain
    `ip_address(host)`).

### P0-2. Committed SQLite database file `phase1.db`

- **File:** `phase1.db` at repo root (152 KB, in git)
- **Symptom:** A working SQLite file from a developer's local run is checked
  in. `.gitignore` does not list `*.db`. The file mixes someone's local
  tenant/user UUIDs into the public repo and confuses anyone running
  `alembic upgrade head` against Postgres.
- **Fix:**
  1. `git rm phase1.db`
  2. Add to `.gitignore`:
     ```
     *.db
     *.sqlite
     *.sqlite3
     ```
  3. If any test was relying on this file (none found in a grep, but verify
     with `grep -RIn "phase1.db" apps tests`), point it at a test-scoped
     fixture instead.
- **Acceptance:** `git ls-files | grep -E '\.(db|sqlite3?)$'` returns empty
  and the test suite still passes against a fresh in-memory or
  tempfile-backed SQLite.

### P0-3. `tenant_id` from claims is never UUID-validated before use as a filesystem path component

- **Files:**
  - `apps/api/app/core/security.py` `build_request_context_from_claims`
    (line 71–77)
  - `apps/api/app/services/document_service.py` `build_object_key`
    (line 33–35) → `LocalFilesystemStorageAdapter.put_object`
    (`apps/api/app/services/storage.py:39`)
- **Symptom:** `context.tenant_id` is taken as a raw string and used in
  `build_object_key(tenant_id=context.tenant_id, …)` which produces
  `documents/{tenant_id}/{source_hash}`. In dev mode the value comes from
  the unvalidated header `X-Dev-Auth-Tenant-Id`. In OIDC mode it comes from
  `claims["tenant_id"]`. A tenant_id of `..` or `../../etc` (or anything
  with `/`) lets the local filesystem write escape the storage root. The
  `UUID(context.tenant_id)` call in `upload_document` happens *after*
  `build_object_key`, so the bad value is already in the key. Even if the
  cast happened first, the function still uses the *raw* string for the
  path.
- **Fix:**
  1. In `build_request_context_from_claims` (and the dev-auth branch of
     `get_request_context`), validate `tenant_id` and `user_id` with
     `uuid.UUID(value)` and reject the request with `401` (OIDC) or `400`
     (dev) if they are not valid UUIDs. Same for `group_ids`.
  2. In `build_object_key`, accept `UUID` only (typed parameter) and
     `str(tenant_id)` only after the cast. Move the `UUID(context.tenant_id)`
     cast in `upload_document` (line 45) to occur *before*
     `build_object_key` is called, and pass the `UUID` through.
- **Acceptance:**
  - New `tests/unit/test_security_tenant_validation.py` asserts that
    requests with `tenant_id="../etc"`, `tenant_id="not-a-uuid"`, and a
    URL-encoded `%2F` get rejected with the right status.
  - New `tests/integration/test_documents_upload.py` case proves the
    storage root cannot be escaped: upload as a tenant with a forged
    header tenant id containing `..` returns the rejection, and no file
    appears outside `LOCAL_STORAGE_DIR`.

### P0-4. Synchronous JWKS fetch on the event loop, no key TTL, no clock-skew leeway

- **File:** `apps/api/app/core/oidc.py`
- **Lines:** 94-120
- **Symptoms:**
  - `_fetch_jwks` uses `urllib.request.urlopen` synchronously inside an
    `async` request handler (called from `get_request_context` →
    `verify_bearer_token`). The whole event loop blocks for up to 5
    seconds when JWKS is fetched.
  - `_jwks_cache` is never expired. The only refresh path is "kid not
    found", which means a revoked-but-still-cached `kid` is still trusted
    until restart.
  - `jwt.decode` is called with no `leeway`, so a 1-second clock drift
    between Keycloak and the API rejects otherwise-valid tokens.
- **Fix:**
  1. Replace `urlopen` with `httpx.AsyncClient` (already a dependency in
     `pyproject.toml` via `dev` extras — promote it to a hard dep) and
     make `_fetch_jwks` async. Update `verify_bearer_token` to be async.
  2. Add a TTL cache (e.g. `time.monotonic()`-based, default 10 minutes,
     env-overridable via `OIDC_JWKS_TTL_SECONDS`). Expire on TTL OR
     kid-miss.
  3. Pass `leeway=settings.oidc_clock_skew_seconds` (new setting, default
     30) into `jwt.decode`.
  4. `get_request_context` is already imported as a `Depends` in async
     routes — the signature needs to be `async def` once the verifier is
     async.
- **Acceptance:**
  - New `tests/unit/test_oidc_jwks_ttl.py` proves expiry on time and on
    kid-miss.
  - `tests/unit/test_oidc_jwks.py` still passes.
  - A new integration test patches a `time.monotonic` shim and asserts
    that `verify_bearer_token` does not block longer than the configured
    `OIDC_JWKS_FETCH_TIMEOUT_SECONDS` even when the JWKS endpoint hangs.

### P0-5. `chunks` table FK type-mismatched against `documents.id` on Postgres

- **Files:**
  - `infra/migrations/versions/20260517_0006_chunks_table.py`
  - `apps/api/app/db/models/chunk.py`
- **Symptom:** the chunks migration declares `id`, `document_id`,
  `parent_id` as `sa.String()`. The ORM model declares them as
  `Mapped[UUID]`. On Postgres, `documents.id` is `uuid` (from migration
  0001), so the foreign key `chunks.document_id (varchar) →
  documents.id (uuid)` is invalid — `alembic upgrade head` will refuse on
  Postgres. The current CI run uses SQLite so this is silently OK there.
  Additionally, `is_tombstoned` uses `server_default="0"` which is not a
  valid Postgres boolean literal.
- **Fix (new migration, do not edit 0006):**
  1. Add `infra/migrations/versions/2026XXXX_00NN_chunks_postgres_compat.py`
     that:
     - Uses `op.alter_column` on `chunks.id`, `chunks.document_id`,
       `chunks.parent_id` to change them to `sa.Uuid()` (with
       `postgresql_using='id::uuid'` etc.).
     - Re-creates the PK/FK constraints once columns are typed.
     - Alters `is_tombstoned` server_default to `sa.text("false")`.
     - Guard the migration with the `bind.dialect.name == "postgresql"`
       check; the existing SQLite schema does not need the changes (it
       uses TEXT for UUIDs anyway).
  2. Add `tests/integration/test_migrations.py` case
     `test_chunks_columns_use_uuid_on_postgres` (skip if not Postgres).
- **Acceptance:**
  - On Postgres: `alembic upgrade head` succeeds against a clean DB.
  - On SQLite: existing test suite remains green.
  - New integration test asserts `chunks.id` reflected type is `UUID` on
    Postgres.

### P0-6. `recover_orphaned_runs` resets every "running" run/stage on startup — no instance-id guard

- **File:** `apps/api/app/repositories/ingestion.py`
- **Lines:** 492-514, also `main.py:32-45`
- **Symptom:** Whenever any process starts up, every IngestionRun and
  IngestionStage with status `"running"` is reset to `"queued"`. On a
  single-instance VPS this is fine. The moment a second worker is added
  (Temporal task queue scaling, blue/green deploy, restart while the
  in-process dispatcher is mid-pipeline on another instance), Instance B
  starting up will reset Instance A's in-flight runs, and the run will be
  re-claimed by whichever dispatcher gets there first. The README
  advertises "Resumable" and "Claim-based dispatch prevents double-
  execution" — neither claim survives multi-instance.
- **Fix:**
  1. Add a `worker_id` column to `ingestion_runs` and `ingestion_stages`
     (UUID, nullable). New migration. Set during `try_claim_ingestion_run`
     to a per-process UUID (created at startup, stored on `app.state`).
  2. Add an `updated_at` heartbeat — `PipelineRunner` already mutates
     stages, so `update_stage_status` should bump `updated_at` (it
     already does via the model's `onupdate`).
  3. Change `recover_orphaned_runs` to only reset runs/stages where
     `worker_id != current_worker_id` **and** `updated_at < now() -
     stale_threshold` (default 5 minutes, configurable as
     `INGESTION_STALE_THRESHOLD_SECONDS`).
  4. Until a worker_id exists in the schema, the in-process recovery
     should be opt-in via env var (`INGESTION_RECOVER_ORPHANED=true`,
     default `false` on multi-instance, `true` on the dev VPS).
- **Acceptance:**
  - `tests/unit/test_ingestion_repository.py` adds two cases: only stale
    runs of *other* workers are recovered; runs of the current worker are
    left alone.
  - A new integration test starts two `PipelineRunner` instances against
    the same SQLite DB and asserts that a still-running run is not
    reclaimed.

### P0-7. `IngestionRun.workflow_backend` is hard-coded to `"scaffold"` regardless of dispatcher

- **File:** `apps/api/app/repositories/ingestion.py:23-31`
  (`create_ingestion_run`)
- **Symptom:** The model accepts `workflow_backend`, the migration backs
  it with `server_default="scaffold"`, but the repository's
  `create_ingestion_run` always writes the literal `"scaffold"` instead
  of the dispatcher in use (in-process vs temporal). README and PROJECT
  STATE both reference this column as a telemetry signal for which
  backend processed a run; today it always says "scaffold".
- **Fix:**
  - Take `workflow_backend` as a parameter to `create_ingestion_run`
    (default `"in_process"`).
  - In `documents.upload_document_route`, fetch
    `settings.workflow_backend` and pass it through `upload_document` →
    `create_ingestion_run`.
  - For retry path, leave the existing column value alone (the retried
    run keeps its original backend).
- **Acceptance:**
  - `tests/unit/test_ingestion_repository.py::test_create_ingestion_run_writes_workflow_backend`
    asserts the column reflects the dispatcher in use.
  - `tests/integration/test_temporal_live_ingestion.py` adds an assertion
    that the resulting run has `workflow_backend == "temporal"`.

### P0-8. Upload reads the entire file into RAM and hashes it twice in memory

- **Files:**
  - `apps/api/app/api/routes/documents.py:44`
  - `apps/api/app/services/document_service.py:44`
- **Symptom:** `content = await file.read()` materializes the whole upload
  as `bytes`, then `sha256(payload.content).hexdigest()` walks it again.
  A 500 MB textbook PDF allocates ≥1 GB in the request handler. A small
  number of concurrent uploads will OOM the API container.
- **Fix:**
  1. Stream the upload to a `NamedTemporaryFile` chunk-by-chunk while
     simultaneously updating a `hashlib.sha256()` and a running byte
     count.
  2. Change `UploadPayload.content: bytes` to
     `UploadPayload.source: Path | BinaryIO` and have the storage adapter
     accept a streaming reader (`put_object_stream(object_key, fp,
     content_type, content_length)`).
  3. Update both `LocalFilesystemStorageAdapter` (copy from the temp file)
     and `S3CompatibleStorageAdapter` (use `upload_fileobj`).
  4. Pass the precomputed hash through to `upload_document` so it isn't
     recomputed.
- **Acceptance:**
  - `tests/integration/test_documents_upload.py` adds a 100 MB upload
    that asserts resident memory stays below ~150 MB during the request
    (use `tracemalloc` or `resource.getrusage` deltas).
  - Existing small-file tests still pass.

---

## P1 — Correctness gaps

### P1-1. Storage adapter has no `get_object`, `delete_object`, or `exists`; failed uploads leak files

- **File:** `apps/api/app/services/storage.py`
- **Symptom:** `upload_document` calls `storage.put_object(...)` **before**
  `create_document_with_owner_acl`. If the DB call raises (FK violation,
  unique violation that the fallback didn't catch, schema drift, network
  blip on Postgres), the object remains in MinIO/local FS with no DB row.
  Over time this orphans bytes.
- **Fix:**
  1. Add `StorageAdapter.delete_object(object_key)` and implement it on
     both adapters.
  2. Wrap `upload_document`'s put + DB writes in a try/except that
     deletes the object on failure (best-effort; log if delete fails).
  3. Alternatively, swap the order: create the DB row first with
     `ingestion_status="pending_storage"`, then write the object, then
     flip to `"uploaded"`. Pick whichever you can write fewer races
     against; the first option is closer to current behavior.
- **Acceptance:**
  - `tests/unit/test_storage_adapters.py::test_delete_object_local`
    and `…_s3` pass.
  - `tests/integration/test_documents_upload.py::test_storage_cleanup_on_db_failure`
    monkeypatches the DB to raise after `put_object` succeeds and
    asserts no orphan exists in storage.

### P1-2. Retrieval ACL filter uses pre-fetched `allowed_document_ids` instead of payload predicates

- **File:** `apps/api/app/services/retrieval/qdrant_retriever.py:53-61`
  and `apps/api/app/services/retrieval/opensearch_retriever.py` (mirror
  logic)
- **Symptom:** The Qdrant filter is just
  `document_id IN (allowed_document_ids)`. The whole point of indexing
  `tenant_id`, `owner_user_id`, `allowed_user_ids`, `allowed_group_ids`,
  `visibility`, `sensitivity_rank`, `expires_at` into the Qdrant payload
  (see `QdrantVectorIndexer.upsert`) is to support payload-side ACL
  predicates without first fetching a list of doc IDs from Postgres. The
  current design (a) does not scale past a few thousand allowed docs per
  user, (b) duplicates ACL evaluation across two code paths, and (c)
  removes the defense-in-depth claim from `SECURITY_ACL.md`.
- **Fix:**
  1. Add `build_qdrant_acl_filter(tenant_id, user_id, group_ids)` that
     produces a `Filter` object mirroring `build_document_acl_filter` —
     same OR-of-clauses, same expiry check (use `Range(lte=…)` on
     `expires_at` or `IsNull`), same tenant-scoping.
  2. Replace `_build_document_filter` callers with the new ACL filter.
     Keep `allowed_document_ids` only as an opt-in narrow filter (e.g.
     "search inside these 3 docs").
  3. Add an equivalent for OpenSearch (`bool.filter` clauses).
  4. Add `tests/integration/test_acl_leakage_ci.py` cases that prove
     `/search` does not return Bob's documents to Alice **even when the
     pre-fetched allowed-doc list is bypassed**.
- **Acceptance:**
  - ACL leakage test fails without the change (force an injected
    `allowed_document_ids` that contains Bob's id and prove the retriever
    no longer returns it because the payload filter blocks it).
  - Latency benchmark unchanged or better (see
    `tests/benchmark_search_latency.py`).

### P1-3. `LocalFilesystemStorageAdapter.materialize_for_read` returns the *write* path

- **File:** `apps/api/app/services/storage.py:44-50`
- **Symptom:** The local adapter returns
  `MaterializedObject(local_path=source_path, cleanup=None)` — the actual
  storage path under `LOCAL_STORAGE_DIR`. The parser receives that path
  and Docling reads from it. If a future parser ever writes to its input
  (e.g. updates EXIF, normalizes encoding in place), the original
  immutable source bytes are mutated. `DEVELOPMENT_RULES.md` non-
  negotiable: "Original file is immutable after upload."
- **Fix:** copy to a `NamedTemporaryFile` (delete=False), return the copy
  with a `cleanup` callback. Same shape as the S3 adapter.
- **Acceptance:**
  - `tests/unit/test_storage_adapters.py::test_local_materialize_does_not_yield_storage_path`
    asserts the returned `local_path` is not under `LOCAL_STORAGE_DIR`.
  - Existing Docling integration tests still pass.

### P1-4. `httpx.Client` in `RemoteDocumentParser` is created at construction and never closed

- **File:** `apps/api/app/services/parsers/remote_backend.py:26`
- **Symptom:** `self._transport = transport or httpx.Client()` — an
  `httpx.Client` is constructed eagerly and never `.close()`d. Each
  parser instance leaks one connection pool. Under the current
  `build_document_parser` factory, this is created once per process,
  which is not catastrophic, but it (a) blocks the event loop on
  shutdown timing and (b) breaks the test cases that monkeypatch
  `httpx.Client` because the patched class is bound at import time.
- **Fix:** lazy-init: only create the client in `_parse_via_http` (or
  reuse a module-level `httpx.Client` with `with` / `lifespan`). On
  FastAPI lifespan shutdown, close the client.
- **Acceptance:**
  - `tests/unit/test_parser_backends.py::test_remote_parser_does_not_construct_client_eagerly`
    asserts `RemoteDocumentParser()` does not touch `httpx.Client`
    unless `parse()` is called.

### P1-5. `DocumentConverter()` is instantiated per parse call

- **File:** `apps/api/app/services/parsers/docling_backend.py:60`
- **Symptom:** Docling's `DocumentConverter()` constructor loads the
  Docling pipeline (multi-second cold start, multi-hundred-MB models).
  The current code instantiates it on every `parse()` call. Each
  ingestion request pays the full cold-start cost.
- **Fix:** cache the `DocumentConverter` instance on the
  `DoclingDocumentParser` (lazy, similar to `BgeM3Embedder._ensure_model`).
  Document that the parser instance is not thread-safe across processes
  if Docling is not — keep the existing one-per-FastAPI-process pattern.
- **Acceptance:**
  - `tests/unit/test_parser_backends.py::test_docling_parser_reuses_converter`
    constructs the parser with a mocked module and asserts
    `DocumentConverter()` is called exactly once across two `parse()`
    calls.

### P1-6. Dev-auth headers accepted from non-loopback when the X-Forwarded-For chain says so

- **File:** `apps/api/app/core/security.py:21-31, 126-151`
- **Symptom:** `_is_loopback_client_host` checks `request.client.host`.
  Under uvicorn behind a reverse proxy (the deploy guide tells the user
  to run `uvicorn --host 0.0.0.0`), `request.client.host` is the proxy
  IP, not the real client. If you accidentally start the API with
  `AUTH_MODE=dev` behind a public reverse proxy that loopbacks to
  127.0.0.1, every request appears loopback and `X-Dev-Auth-*` headers
  are accepted from anyone. This is documented in Starlette's
  TrustedHostMiddleware docs as a real foot-gun.
- **Fix:**
  1. Refuse to start when `AUTH_MODE=dev` and the bind address is not
     `127.0.0.1`/`::1`/`localhost`. Check at app factory time.
  2. Add a runtime `request.client.host in {"127.0.0.1", "::1"}` *and*
     `request.headers.get("X-Forwarded-For") is None` belt-and-
     suspenders check.
  3. Emit a loud warning log on every dev-auth request.
- **Acceptance:**
  - `tests/integration/test_oidc_auth_flow.py` adds two cases: dev auth
    via loopback works; dev auth via a request with
    `X-Forwarded-For: 1.2.3.4` is rejected.
  - `tests/unit/test_request_context.py::test_dev_auth_rejects_when_bind_not_loopback`
    patches the bind address and asserts startup raises.

### P1-7. `persist_chunks` deletes all existing chunks before insert — non-transactional rollback hole

- **File:** `apps/api/app/repositories/chunks.py:18-89`
- **Symptom:** `delete(ChunkModel).where(...)` runs *inside* the same
  session as the inserts, but the function does a manual `flush` after
  the parents (line 51) before the children are added. If the
  child-insert step fails after a flush (e.g. a unique-index violation
  on `(document_id, chunk_index)` because a separate process re-chunked
  concurrently), the parents have been written but children have not,
  and the prior chunks are gone. Idempotent re-runs are then in a
  partial state.
- **Fix:**
  1. Move the parent flush to after all rows are added. Use a single
     `session.flush()` then `session.commit()` at the end.
  2. Wrap the delete + inserts in an explicit `begin()` block. On
     exception, ensure the entire delete is rolled back (currently
     SQLAlchemy's autobegin handles this — but a `try/except` around the
     loop with explicit `session.rollback()` reads more clearly).
  3. Add a sanity assert that `parent_chunks` has exactly 1 entry for
     loose docs, since the current code path only correctly maps
     children for that case (line 63-68 documents this assumption).
- **Acceptance:**
  - `tests/unit/test_chunks_repository.py::test_persist_chunks_rolls_back_on_child_insert_failure`
    induces a child-insert failure and asserts no rows were lost.

### P1-8. `oidc_username_claim` is read but never used

- **File:** `apps/api/app/core/config.py:21`,
  `apps/api/app/core/security.py:48-77`
- **Symptom:** `Settings.oidc_username_claim` defaults to
  `"preferred_username"` but `build_request_context_from_claims` never
  reads it (only `sub` is used as `user_id`). Either the setting is
  cruft, or the intent was to populate a display name in
  `RequestContext`. The README lists it under OIDC config as if it's
  active.
- **Fix:** either:
  - Remove the setting and the matching `.env.example` entry (none today,
    so just drop the setting); **or**
  - Wire it through to `RequestContext.display_name` (new optional
    field) and surface it in audit events.

  Recommended: remove until there's a consumer. Cruft in `Settings`
  encourages drift.
- **Acceptance:**
  - `tests/unit/test_oidc_claim_mapping.py` is updated to remove any
    reference to the dropped field, or to assert the new behavior.

---

## P2 — Operability and performance

### P2-1. `OpenSearchLexicalIndexer` always uses `verify_certs=False`

- **File:** `apps/api/app/services/indexers/opensearch_indexer.py:43-48`
- **Symptom:** The client is constructed with `verify_certs=False`
  unconditionally, ignoring `settings.opensearch_verify_certs` (which
  exists in `config.py` line 51 but is never read here).
- **Fix:** wire `settings.opensearch_verify_certs` and
  `settings.opensearch_use_ssl` through `build_search_retriever` /
  whichever factory constructs the indexer.
- **Acceptance:** new unit test asserts the constructed client honors
  the setting.

### P2-2. JWKS cache and Settings are process-singletons but no clean shutdown

- **Files:** `apps/api/app/core/oidc.py:123-125`,
  `apps/api/app/core/config.py:88-90`
- **Symptom:** `lru_cache` is process-global. Tests that mutate env vars
  must call `get_settings.cache_clear()` and `get_oidc_token_verifier.cache_clear()`
  to see changes; this is undocumented and reproducibly bites new tests.
- **Fix:** add a `reset_dependency_caches()` helper in
  `app/core/__init__.py` that clears both. Wire it into `conftest.py`
  fixtures so tests automatically get a clean cache between cases.

### P2-3. Ingestion `IntegrityError` fallback in
`get_or_create_document_by_source_hash` does not commit before the
re-read

- **File:** `apps/api/app/repositories/documents.py:251-272`
- **Symptom:** When two workers race the same upload, one wins, the
  other catches `IntegrityError`, then immediately calls
  `get_live_document_by_source_hash`. That helper opens a *new*
  `session_factory()` (line 276) which under SQLite's default isolation
  may not yet see the other transaction's commit. Tests don't hit this
  because they share a single connection. Postgres in read-committed is
  fine. SQLite + tempfile is not.
- **Fix:** add a short retry loop (3 attempts, 50 ms apart) in the
  fallback; on each iteration re-open the session.

### P2-4. `recover_orphaned_runs` swallows table-missing exceptions silently

- **File:** `apps/api/app/main.py:32-45`
- **Symptom:** The startup recovery wraps the call in
  `try/except Exception` and logs at DEBUG level, with the message
  "Orphaned-run recovery skipped (table may not exist yet)". This hides
  real failures (auth issues, FK violations, schema drift) — any
  exception is silently demoted.
- **Fix:** narrow the except to `sqlalchemy.exc.OperationalError` and
  `sqlalchemy.exc.ProgrammingError`. Re-raise others.

### P2-5. `TemporalDispatcher` creates a new client per `dispatch` call when not pre-injected

- **File:** `apps/api/app/workflows/temporal_dispatcher.py:51-77`
- **Symptom:** If `self._client is None`, `dispatch` calls
  `Client.connect` every time. Under burst uploads, this builds up TCP
  connections.
- **Fix:** cache the client on first use; expose a
  `close()` method and call it in the FastAPI lifespan shutdown.

### P2-6. `build_temporal_worker` falls back to `_WorkerSkeleton` when `client.config` is absent

- **File:** `apps/api/app/workflows/temporal_worker.py:40-54`
- **Symptom:** the worker factory uses `hasattr(client, "config")` to
  detect "real Temporal client" vs "test stub". If a future temporalio
  release renames `config`, the factory silently returns a no-op
  skeleton in production.
- **Fix:** detect by `isinstance(client, temporalio.client.Client)`
  inside a `try/except ImportError`. Document the test stub contract
  explicitly in a comment near the function.

### P2-7. `runtime.py` recovery and orphan handling depend on a shared singleton dispatcher

- **File:** `apps/api/app/main.py:51-67`
- **Symptom:** `app.state.dispatcher` is built at lifespan startup. The
  Temporal dispatcher's connection error (e.g. Temporal not reachable)
  raises at startup, which is good — but the in-process dispatcher path
  silently swallows a misconfigured storage backend (it just passes
  `storage=None`). Uploads then succeed but fail to parse with a
  confusing error.
- **Fix:** fail fast at startup if `settings.parser_backend == "docling"
  and settings.workflow_backend == "in_process"` but storage is `None`.

---

## Documentation drift to fix alongside

These are not bugs but the docs/code disagree:

1. **README.md** "12-point verification passed (2026-05-16)" — restate
   the date next to the verification artifact location (`docs/uber-rag/`
   has no 12-point report; surface it).
2. **AGENTS.md** "Project memory location" lists `docs/uber-rag/` but
   `docs/superpowers/` is where active plans actually live. Cross-link
   them.
3. **PROJECT_STATE.md** (>26k tokens) — split into PROJECT_STATE.md
   (current state, < 5 KB) and an archive directory. Reading the whole
   file should not blow context budgets for downstream agents.
4. **ROADMAP.md** Phase 2 "Deliverables" still lists "Book profile
   chunking" as remaining inside Phase 2, but TASKS.md and PROJECT_STATE
   have moved it to Phase 3. Reconcile.

---

## Out of scope (do not pick up in this batch)

These were noticed during the audit but belong to later phases or to
the wider design conversation, not to a Phase 1/2 fix PR.

- **Book profile chunking** — Phase 3 deliverable, intentionally
  deferred; flagged here only because PROJECT_STATE and TASKS disagree
  (see doc drift item 4 above).
- **Hybrid retrieval / reranking / generation correctness** — Phase 3/4
  scope. Out of scope here except where retrieval ACL touches Phase 1/2
  (P1-2 above).
- **Frontend e2e** — Phase 1 README admits "scaffold only, never tested
  E2E". Handled by Phase 5.
- **Postgres RLS** — repeatedly suggested in `SECURITY_ACL.md`. Defer
  until a separate ADR exists; current SQL-level ACL filter is good
  enough.
- **OCR engine selection** — ADR-0006 already accepted Docling-default
  with PaddleOCR upgrade path; not a Phase 1/2 fix.

---

## Acceptance summary (what "done" looks like for this list)

- All P0 items merged.
- All P1 items merged or explicitly deferred with an ADR.
- `pytest apps/api/app/tests/ -v` green.
- `pytest tests/integration/test_acl_leakage_ci.py -v` green.
- `alembic upgrade head` succeeds against a fresh Postgres 17 container.
- `git ls-files | grep -E '\.(db|sqlite3?)$'` is empty.
- One new ACL leakage test exists for each ACL-touching P0/P1 item.
- `README.md` "What's Built" section updated to match the post-fix
  reality (especially: storage cleanup, payload-side ACL filtering,
  workflow_backend column truthful).
