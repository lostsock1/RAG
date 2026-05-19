# Uber-RAG

API-first, ACL-aware RAG platform for textbooks and loose documents.

## Quickstart

See `AGENTS.md` for agent orientation and `docs/uber-rag/PROJECT_STATE.md` for current state.

## Gate C local operational foundation

1. Copy `.env.example` to `.env` and adjust values for your machine.
2. For the local dev-header fallback, set at least:
   - `AUTH_MODE=dev`
   - `LOCAL_STORAGE_DIR=/absolute/path/for/local-document-storage`
3. Development auth headers are accepted only from loopback clients (`127.0.0.1`, `::1`, `localhost`). They are a local fallback only, not a general local-network auth mode.
4. For real Phase 1 OIDC verification, run Keycloak locally and set:
    - `AUTH_MODE=oidc`
    - `OIDC_ISSUER_URL=http://localhost:8080/realms/uber-rag`
    - `OIDC_AUDIENCE=uber-rag-api`
    - `OIDC_JWKS_URL=http://localhost:8080/realms/uber-rag/protocol/openid-connect/certs`
    - `LOCAL_STORAGE_DIR=/absolute/path/for/local-document-storage`
5. Start the local dependency stack:
    - `docker compose -f infra/docker/docker-compose.yml up -d`
6. The compose stack now imports `infra/docker/keycloak/uber-rag-realm.json`, which bootstraps:
   - realm: `uber-rag`
   - client: `uber-rag-api`
   - test users: `alice`, `bob`, `admin`
   - claims: `tenant_id`, `groups`, `permissions`, and realm roles
7. Request a real local access token, for example:
   - `curl -X POST http://localhost:8080/realms/uber-rag/protocol/openid-connect/token -d 'grant_type=password' -d 'client_id=uber-rag-api' -d 'username=alice' -d 'password=alicepass'`
8. Uploaded files are currently written through the local filesystem adapter at `LOCAL_STORAGE_DIR`.
9. Verify the API shell health endpoint:
    - `pytest apps/api/app/tests/integration/test_health.py -v`
10. Verify the auth-focused backend suite:
    - `pytest apps/api/app/tests/unit/test_oidc_claim_mapping.py apps/api/app/tests/unit/test_oidc_jwks.py apps/api/app/tests/integration/test_oidc_auth_flow.py apps/api/app/tests/integration/test_runtime_auth_startup.py -v`

The local dependency stack exposes PostgreSQL on `5432`, MinIO on `9000`/`9001`, Keycloak on `8080`, and a local Temporal dev service on `7233`/`8233`, but MinIO is still planned infrastructure rather than the active runtime document-storage path. Today, local uploads use `LOCAL_STORAGE_DIR`. The runtime verifier now validates bearer tokens against the configured JWKS endpoint; issuer-based JWKS discovery is not implemented in this Phase 1 slice.

## Local Temporal validation (Phase 2 closeout)

1. Install the repo with the Temporal SDK extra:
   - `.venv/bin/pip install -e ".[dev,temporal]"`
2. Start a local Temporal service. Use either path:
   - Docker Compose: `docker compose -f infra/docker/docker-compose.yml up -d temporal`
   - Temporal CLI fallback: `temporal server start-dev --headless --ip 127.0.0.1 --port 7233 --ui-port 8233 --db-filename ./.temporal/dev-server.db`
3. Verify the server is reachable:
   - `temporal operator cluster health --address 127.0.0.1:7233`
   - Expected: `SERVING`
4. Run the guarded live proof against the real Temporal service:
   - `.venv/bin/pytest apps/api/app/tests/integration/test_temporal_live_ingestion.py -q`
   - Expected: `1 passed` when Temporal is reachable; truthful `skipped` when no local Temporal server is running.
5. Optional manual worker process from repo settings:
   - `PYTHONPATH=apps/api WORKFLOW_BACKEND=temporal TEMPORAL_HOST_PORT=127.0.0.1:7233 TEMPORAL_TASK_QUEUE=uber-rag-ingestion DATABASE_URL=sqlite:////absolute/path/to/temporal-worker.db LOCAL_STORAGE_DIR=/absolute/path/to/local-storage PARSER_BACKEND=docling PARSER_PROFILE=local-cpu .venv/bin/python -m app.workflows.temporal_worker`
   - This command starts the repo's Temporal worker entrypoint. It requires a real parser runtime (for example Docling) plus a configured database/storage path.

## VPS run flow (Gate C — verified 2026-05-16)

**Host:** `ssh rag` (vm-1485.lnvps.cloud, user `debian`)

### Prerequisites (already provisioned)

- Docker + docker-compose installed, `debian` user has sudo access
- Python 3.12 venv at `~/RAG/.venv` with all backend deps
- `.env` configured for `AUTH_MODE=oidc` with Keycloak JWKS URLs

### Starting the stack

```bash
# 1. Start infrastructure containers
cd ~/RAG
sudo docker compose -f infra/docker/docker-compose.yml up -d

# 2. Verify all three containers are healthy
sudo docker ps --format 'table {{.Names}}\t{{.Status}}'
# Expected: postgres (healthy), minio (up), keycloak (up)

# 3. Start the API (background)
source .venv/bin/activate
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > uvicorn.log 2>&1 &

# 4. Verify health
curl -s http://localhost:8000/api/v1/system/health
# Expected: {"status":"ok"}
```

### Verified endpoints (2026-05-16)

| # | Check | Endpoint | Result |
|---|---|---|---|
| 1 | API health | `GET /api/v1/system/health` | `{"status":"ok"}` |
| 2 | Keycloak OIDC discovery | `GET :8080/realms/uber-rag/.well-known/openid-configuration` | 200, valid config |
| 3 | JWKS keys | `GET :8080/realms/uber-rag/protocol/openid-connect/certs` | 200, RSA key present |
| 4 | Token issuance (Alice) | `POST :8080/realms/uber-rag/protocol/openid-connect/token` | 200, valid JWT |
| 5 | Document upload (Alice) | `POST /api/v1/documents/upload` | 201, document created |
| 6 | Document list (Alice) | `GET /api/v1/documents` | 200, sees her documents |
| 7 | Document list (Bob) | `GET /api/v1/documents` | `{"items":[]}` — ACL enforced |
| 8 | Unauthenticated rejection | `GET /api/v1/documents` | 401, "Missing bearer token" |
| 9 | ACL read | `GET /api/v1/documents/{id}/acl` | 200, correct ACL record |
| 10 | File storage | `~/uber-rag-storage/documents/...` | Files present on disk |
| 11 | MinIO health | `GET :9000/minio/health/live` | 200 |
| 12 | Postgres | `SELECT count(*) FROM documents` | 2 rows |

### Test users (from imported realm)

| User | Password | Group | Roles | Permissions |
|---|---|---|---|---|
| `alice` | `alicepass` | `alpha` | `editor` | `documents:read documents:write` |
| `bob` | `bobpass` | `beta` | `editor` | `documents:read documents:write` |
| `admin` | `adminpass` | — | `admin` | `documents:read documents:write` |

### Important notes

- The VPS `.env` uses `OIDC_SCOPES_CLAIM=permissions` because the Keycloak realm maps API permissions into the `permissions` claim rather than the standard `scope` claim.
- Uploaded files go to `LOCAL_STORAGE_DIR=/home/debian/uber-rag-storage` (local filesystem adapter). MinIO is running but not yet wired as the active storage backend.
- The API runs on port 8000, Keycloak on 8080, Postgres on 5432, MinIO on 9000/9001.
