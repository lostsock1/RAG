# SeaweedFS Runtime Coverage Design

Date: 2026-05-16
Status: Approved
Scope: Exercise the SeaweedFS/S3-compatible runtime path in tests through the public upload API without introducing a live SeaweedFS server into the suite.

## Context

Phase 2 selected SeaweedFS as the accepted object-storage direction, and the code already includes an S3-compatible storage adapter seam. However, current verification only proves that the adapter exists and that local filesystem upload works. It does not yet prove that the upload runtime behaves correctly when configured to use the SeaweedFS/S3-compatible adapter.

## Design

### 1. What this slice proves

This slice proves:

1. `build_storage_adapter(settings)` selects `S3CompatibleStorageAdapter` for `storage_backend="seaweedfs"`
2. upload route runtime can operate through the S3-compatible seam
3. object uploads call the underlying client with correct bucket/key/body/content type
4. document metadata and ingestion run creation remain correct through this path

### 2. What this slice does not do

- no live SeaweedFS server in CI
- no networked integration stack
- no parser changes
- no OCR work
- no remote object retrieval/read path yet

### 3. Test strategy

#### Unit test

Add direct coverage for `S3CompatibleStorageAdapter.put_object(...)` to verify that it forwards the expected values to the underlying client.

#### Integration upload test

Add an upload test that:

- configures app storage with `S3CompatibleStorageAdapter(client=fake_client, ...)`
- uploads through `/api/v1/documents/upload`
- verifies fake client received:
  - `Bucket`
  - `Key`
  - `Body`
  - `ContentType`
- verifies DB document metadata and ingestion run creation remain correct
- verifies dedup still reuses the same object key across repeated uploads

## Outcome

After this slice, the project can honestly claim that the SeaweedFS runtime path is exercised through the application API and not merely present as an untested adapter seam.
