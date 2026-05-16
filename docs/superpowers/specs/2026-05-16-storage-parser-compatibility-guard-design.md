# Storage/Parser Compatibility Guard Design

Date: 2026-05-16
Status: Approved
Scope: Fail fast at startup when the configured object storage backend and parser runtime are incompatible.

## Context

SeaweedFS runtime seam coverage now proves that uploads can talk to the S3-compatible adapter interface, but the current parser runtime still requires a locally readable file path. That means a SeaweedFS-backed configuration can accept uploads and only fail later when parsing starts.

This is a misleading runtime state. The system should reject the incompatible configuration at startup instead.

## Design

### Guard location

The compatibility rule belongs in:

- `apps/api/app/services/parsers/factory.py`

That file already owns parser backend resolution and unsupported backend errors, so it is the correct boundary for parser/storage compatibility rules.

### Guard rule

If:

- `settings.storage_backend == "seaweedfs"`
- and parser backend resolves to the current local-file-only Docling runtime (`docling` / `docling-local`)

then startup should raise a clear `RuntimeError`.

### Error message

The error should clearly explain:

- SeaweedFS object storage is not yet compatible with the current local Docling parser runtime
- the current parser expects files to be readable from local disk
- use local storage for now, or implement a remote object-read parsing path first

### Tests

#### Factory-level tests

- `storage_backend="seaweedfs"` + `parser_backend="docling"` raises clear `RuntimeError`
- `storage_backend="local"` + `parser_backend="docling"` still resolves successfully
- existing `remote` unsupported backend case remains explicit

#### Startup integration test

- app startup fails with the same clear message when the incompatible configuration is injected through settings/environment

## Non-goals

- no SeaweedFS read-path implementation
- no parser redesign
- no OCR work
- no `boto3` dependency changes

## Outcome

After this slice, the app cannot enter a misleading “upload succeeds, parse later fails” state for the SeaweedFS + local Docling combination.
