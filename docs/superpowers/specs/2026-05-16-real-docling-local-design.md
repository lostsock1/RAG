# Real Docling Local Parsing Design

Date: 2026-05-16
Status: Approved
Scope: Replace the injected-converter-only Docling parser path with a real local filesystem-backed Docling conversion path that normalizes pages and tables into the existing `ParsedArtifact` contract.

## Context

Phase 2 ingestion dispatch is wired and end-to-end stage execution works, but the current `DoclingDocumentParser` only supports an injected converter for tests. Real ingestion therefore proves orchestration and persistence, not real document understanding.

ADR-0011 requires Docling to serve as the parser shell and normalization boundary. The next smallest valuable slice is to enable real local parsing while preserving the current injected-converter seam for deterministic tests.

## Scope

### Included

- Local filesystem-backed Docling parsing
- Normalization into existing `ParsedArtifact` schema
- `pages[]` extraction
- `tables[]` extraction
- Provenance population
- Clear runtime failures for missing dependency, missing storage root, missing file, and conversion failure

### Deferred

- OCR fallback/invocation
- SeaweedFS runtime parsing path
- Remote parser backend wiring
- Figure extraction
- Formula extraction
- Quality report schema expansion
- Parsed artifact schema changes

## Design

### 1. Runtime behavior

When the ingestion pipeline reaches the `parse` stage:

1. `object_key` resolves against a configured local storage root.
2. `DoclingDocumentParser.parse()` runs a real Docling conversion against that file.
3. The Docling result is normalized into the existing `ParsedArtifact` contract:
   - `document_id`
   - `pages`
   - `tables`
   - `provenance`
4. The existing downstream stages continue unchanged:
   - persist artifact
   - build quality report

The injected converter path remains intact and still takes precedence when provided.

### 2. Code boundaries

Docling-specific integration stays inside `apps/api/app/services/parsers/docling_backend.py`.

Proposed private helpers:

- `_parse_with_docling(...)`
- `_normalize_docling_result(...)`
- `_extract_pages(...)`
- `_extract_tables(...)`

No workflow-layer Docling branching is introduced. The rest of the system continues to depend only on `DocumentParser` and `ParsedArtifact`.

### 3. Constructor shape

`DoclingDocumentParser` accepts:

- `converter: Callable[[ParseRequest], ParsedArtifact] | None = None`
- `storage_root: Path | None = None`

Behavior:

- if `converter` is provided, use it
- else if `storage_root` is configured, resolve the file and run real Docling conversion
- else raise a clear runtime error

### 4. Normalization target

The normalized output uses the current schema only.

`ParsedPage`:
- `page_number`
- `text`
- `blocks`

`ParsedTable`:
- `page_number`
- `bbox`
- `markdown`

`ParserProvenance`:
- `parser_backend = "docling"`
- `parser_version = <resolved version or fallback label>`
- `profile = request.profile`

This slice intentionally does not widen the schema.

### 5. Failure handling

The parser fails loudly and specifically in these cases:

1. Docling not installed → `RuntimeError` stating the package is required
2. No storage root configured → `RuntimeError` stating local Docling parsing requires a storage root
3. Resolved file missing → `RuntimeError` including the `object_key`
4. Docling conversion failure → wrapped `RuntimeError` preserving original exception via `from exc`

This preserves the current ingestion semantics: parse stage fails, dispatcher marks the run failed, and the error is checkpointed.

## Tests

### Unit tests

- injected converter path still works
- missing Docling dependency raises clear error
- missing storage root raises clear error
- missing file raises clear error

### Integration-style parser test

- create a real local file in temp storage
- instantiate `DoclingDocumentParser(storage_root=...)`
- call `parse()` without converter override
- assert returned artifact has the correct `document_id`, at least one page, and correct provenance

This test should remain narrow to avoid brittle fixture assumptions.

## Non-goals

- OCR behavior
- SeaweedFS-backed parsing
- remote backend execution
- formulas/figures contract
- quality report enrichment

## Outcome

This slice upgrades the system from fake parsing to real local parsing while preserving test determinism and keeping the rest of the ingestion pipeline unchanged.
