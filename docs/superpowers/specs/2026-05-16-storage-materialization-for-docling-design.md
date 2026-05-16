# Storage Materialization Seam for Docling Parsing Design

Date: 2026-05-16
Status: Approved
Scope: Make SeaweedFS-backed parsing runnable by adding a general storage materialization seam that yields a local file path for Docling regardless of storage backend.

## Context

The current ingestion runtime supports:

- local storage + local Docling parser
- SeaweedFS/S3-compatible upload seam coverage
- honest startup rejection for `SeaweedFS + local Docling` because parsing still expects `storage_root / object_key`

This means the system is structurally correct but still missing the real feature that Phase 2 needs: SeaweedFS-backed parsing that can actually run end-to-end.

The smallest architecture-correct way to unlock that path is to add a general storage materialization seam. Storage should be responsible for yielding a readable local file path for parsers; parsers should not know how objects are fetched.

## Decision

Add a general `materialize_for_read()` capability to `StorageAdapter`, and update the ingestion parse flow so Docling always receives a materialized local file path via `ParseRequest.local_source_path`.

This is reversible, but it is the cleanest near-term way to make both local and SeaweedFS-backed parsing work without introducing a separate remote parser service.

## Design

### 1. New storage seam

Add to `StorageAdapter`:

- `materialize_for_read(*, object_key: str) -> MaterializedObject`

Add a new return type:

- `MaterializedObject`
  - `local_path: Path`
  - `cleanup: Callable[[], None] | None`

Backend behavior:

- **LocalFilesystemStorageAdapter**
  - resolves the existing local file path
  - returns `cleanup=None`

- **S3CompatibleStorageAdapter**
  - downloads the object to a temp local file
  - returns a cleanup callback that deletes the temp file

### 2. Parse request contract

Extend `ParseRequest` with:

- `local_source_path: str | None = None`

This keeps storage identity (`object_key`) separate from parser input (`local_source_path`).

### 3. Parser behavior

`DoclingDocumentParser.parse()` should:

- still honor the injected converter path first
- prefer `request.local_source_path` when present
- keep the legacy `storage_root + object_key` fallback only if still needed temporarily
- use the local path as the source passed into Docling conversion

This reduces parser ownership of storage-specific behavior.

### 4. Dispatcher/runtime flow

New runtime flow:

1. dispatcher loads document metadata
2. dispatcher gets the configured storage adapter from a runtime seam
3. dispatcher calls `materialize_for_read(object_key=...)`
4. dispatcher passes `local_source_path` into `run_parse_stage(...)`
5. parser runs Docling against that local path
6. dispatcher always invokes cleanup after parse attempt (success or failure)

### 5. Guard evolution

The current `SeaweedFS + local Docling` startup guard should be removed or narrowed after this path is implemented and tested, because the configuration will no longer be inherently invalid.

## Tests

### Storage tests

- local adapter returns existing file path and no cleanup
- S3 adapter downloads to temp file and cleanup removes it

### Parser tests

- parser uses `local_source_path` when provided
- injected converter path remains unchanged

### Dispatcher/integration tests

- upload through S3-compatible adapter
- dispatcher materializes temp local file
- parser uses materialized local path
- artifact persists and run completes

### Startup/guard tests

- current guard removed or narrowed only after the new end-to-end path is green

## Non-goals

- remote parser service
- OCR path
- formula/figure extraction changes
- production observability improvements beyond current stage errors

## VPS / deployment impact

This slice likely requires runtime deployment changes after code lands:

- add `boto3` to runtime dependencies
- rebuild/redeploy the API container
- validate temp-file materialization path on the VPS

But the code should remain fully testable locally with fake S3 clients first.

## Outcome

After this slice, SeaweedFS becomes a real end-to-end parsing path instead of just an accepted direction plus an upload seam.
