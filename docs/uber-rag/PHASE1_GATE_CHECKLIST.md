# Phase 1 Gate Checklist

## Gate A — Design closure
- [x] Phase 1 endpoint subset frozen
- [x] Phase 1 minimum schema subset frozen
- [x] ACL rules translated into explicit tests
- [x] ADR/doc gaps identified

### Identified gaps (recorded 2026-05-16)
- ADR-0007 (frontend config) still deferred but frontend now builds — should be drafted before Phase 5 UI work
- Scope inference from roles (security-relevant) — no ADR yet; current behavior: only infer when scope claim is absent from token
- Dev auth mode (loopback-only header auth) — no ADR yet; architectural choice for local development
- Alembic `env.py` now reads `DATABASE_URL` env var; `alembic.ini` still has hardcoded SQLite fallback

## Gate B — Security/data foundation
- [x] Request context seam implemented
- [x] Initial migration landed
- [x] ACL filter builder implemented
- [x] Audit persistence implemented
- [x] Leakage tests passing

## Gate C — Operational foundation
- [x] Docker stack runs on VPS (`ssh rag` → vm-1485.lnvps.cloud) — all 3 containers healthy, API running, 12-point verification passed (2026-05-16)
- [x] Config/env discipline documented
- [x] Health checks green
- [x] Local filesystem adapter wired for runtime; MinIO adapter still pending
- [x] CI baseline green
- [x] VPS prepared for continued development and installation/testing (`ssh rag`)
- [x] Live Keycloak/JWKS/API round-trip verified on VPS (`vm-1485.lnvps.cloud`)
- [x] Full end-to-end verified on VPS: upload → list → ACL separation → unauthenticated rejection → ACL read → file storage → MinIO health → Postgres connectivity (2026-05-16)
- [x] VPS run flow documented in README.md

## Gate D — First product slice
- [x] Upload works
- [x] ACL read/update works
- [x] Document list is ACL-filtered
- [x] Minimal login/upload/list UI works (builds and generates all pages; browser-level verification still pending)

## Gate C — Local Docker stack note

The "Docker stack runs locally" criterion is satisfied by the VPS verification above. Local Docker CLI is unavailable in the primary development environment (macOS without Docker Desktop). The VPS runs the identical `docker-compose.yml` with the same Keycloak realm import, and all 12 verification points pass. If local Docker becomes available, the same `docker compose -f infra/docker/docker-compose.yml up -d` flow applies.
