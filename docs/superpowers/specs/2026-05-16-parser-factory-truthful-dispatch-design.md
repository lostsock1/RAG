# Parser Factory and Truthful Dispatch Metadata Design

Date: 2026-05-16
Status: Approved
Scope: Add an explicit parser factory as the runtime composition point and remove hardcoded parser backend/profile metadata from ingestion dispatch.

## Context

The new local Docling slice made real local parsing possible, but the runtime still hardcodes composition in the wrong place:

- `main.py` instantiates `DoclingDocumentParser` whenever `settings.parser_backend` is merely truthy
- `dispatcher.py` hardcodes `parser_backend="docling"` and `profile="loose"`

This violates the accepted Phase 2 architecture in ADR-0011, which requires deployment-configured backend choice across local CPU / local GPU / remote API profiles.

## Design

### 1. Parser factory boundary

Add a dedicated runtime parser factory at:

- `apps/api/app/services/parsers/factory.py`

Factory function:

- `build_document_parser(settings: Settings) -> tuple[DocumentParser, str, str]`

Returned values:

1. parser instance
2. resolved backend name for emitted metadata
3. resolved profile label for emitted metadata

### 2. Supported backend values in this slice

- `docling` → resolves to local Docling runtime
- `docling-local` → resolves to local Docling runtime
- `remote` → raises explicit not-yet-supported runtime error
- anything else → raises clear unknown-backend runtime error

### 3. Truthful dispatch metadata

`InProcessDispatcher` should carry parser metadata explicitly.

Change construction from:

- `InProcessDispatcher(parser=parser)`

to:

- `InProcessDispatcher(parser=parser, parser_backend="docling-local", parser_profile="local-cpu")`

The dispatcher then passes those values into `run_parse_stage(...)` instead of inventing them at execution time.

### 4. Backward compatibility

Keep:

- `Settings.parser_backend = "docling"`

for compatibility with existing config.

But resolve that to truthful emitted metadata:

- backend: `docling-local`
- profile: `local-cpu`

This avoids breaking current deployments while improving provenance and stage details.

## Tests

### Factory tests

- `docling` resolves to local Docling parser + `docling-local` + `local-cpu`
- `docling-local` resolves the same way
- `remote` raises explicit not-yet-supported error
- unknown backend raises clear error

### Startup/runtime tests

- startup builds dispatcher with parser instance and truthful metadata

### Dispatcher tests

- parse stage details record `docling-local`, not hardcoded `docling`
- parser provenance/profile reflect configured runtime metadata

## Non-goals

- remote parser implementation
- SeaweedFS parsing runtime
- OCR path
- DB schema changes
- parser profile persistence on ingestion run records

## Outcome

This slice fixes the composition boundary and truthfulness problem without overextending into new backends.
