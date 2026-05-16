# ADR-0011: Structured Document-Understanding Architecture for Phase 2
Status: Accepted
Date: 2026-05-16

## Context

Phase 2 was initially framed as parser + OCR plumbing, but the approved design direction is now clearer. The project’s actual need is not just OCR text extraction; it is a structured document-understanding path that preserves rich artifacts for downstream retrieval quality.

Confirmed priorities:

- tables are critical
- formulas matter, but are secondary to tables
- rich structure matters more than simple Markdown extraction
- the system must work across local CPU, local GPU, and remote API deployments
- backend choice should happen per deployment config, not per document/job
- local and remote modes must feed the same downstream pipeline

## Decision

Adopt a **structured document-understanding architecture** with:

- **Docling** as the parser shell / normalization boundary
- one normalized structured parsed-artifact contract
- deployment-configured backend profiles: local CPU, local GPU, remote API
- remote path treated as document understanding, not OCR-only

This decision is **reversible** if later benchmarking proves that another parser shell or artifact contract is materially better.

## Consequences

### Positive

- Aligns the architecture with the real quality requirement: rich structural fidelity, especially for tables.
- Lets local and remote deployments stay seamless without per-job routing complexity.
- Creates a stable downstream contract for chunking, provenance, and later indexing.
- Keeps backend/provider swaps modular.

### Negative

- Increases Phase 2 scope relative to a plain OCR/text-extraction path.
- Requires explicit artifact validation and metadata discipline.
- Makes parser integration work heavier because output normalization matters as much as raw extraction.

## Alternatives considered

- **Flat OCR/text-first architecture** — rejected. Does not fit the critical table-fidelity requirement.
- **Per-job backend routing** — rejected. More flexible, but adds complexity the user does not want in Phase 2.
- **Single provider-specific remote parser path** — rejected. Conflicts with the requirement to work seamlessly across local and remote backends.
- **GPU/VLM-heavy everywhere from day one** — rejected. Strong quality upside, but heavier than the current phase needs.

## References

- Docling docs — https://docling-project.github.io/docling/ (accessed 2026-05-16)
- Docling releases — https://github.com/docling-project/docling/releases (accessed 2026-05-16)
- PaddleOCR docs — https://www.paddleocr.ai/latest/en/index.html (accessed 2026-05-16)
- Tesseract OCR — https://tesseract-ocr.github.io/ (accessed 2026-05-16)
- Internal research note — `docs/uber-rag/research/2026-05-16-phase-2-entry.md`
- Internal design spec — `docs/superpowers/specs/2026-05-16-phase-2-entry-design.md`

## Revisit triggers

- If actual corpus benchmarks show the normalized artifact contract is insufficient for retrieval quality.
- If one deployment profile produces outputs that cannot be normalized without major quality loss.
- If table fidelity remains poor enough that the parser shell itself should be replaced.
