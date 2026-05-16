# ADR-0006: OCR Stack — Docling Built-in as Default, PaddleOCR as Upgrade Path

Status: Accepted
Date: 2026-05-14

## Context

The ingestion pipeline must handle scanned PDFs, image-based pages, and mixed-content documents (text + images + tables). `STACK_REFERENCES.md` lists Tesseract and PaddleOCR as OCR candidates. The project is air-gapped-ready, multilingual (German, Portuguese, English), and the parsing pipeline is backed by Docling (ADR-0002 cover).

Docling already ships with built-in OCR support. Its pipeline wraps Tesseract via pytesseract and optionally EasyOCR as a fallback. This means the "add OCR" question is not "which engine do we integrate" but "do we accept Docling's built-in, do we swap the engine, or do we add a second engine for specific languages."

Three constraints shape this decision:

1. **Air-gapped deployment** — no cloud OCR APIs (Google Vision, Azure OCR, Amazon Textract). All engines must run locally.
2. **Corpus profile** — the initial corpus is primarily digital-born PDFs. OCR is a fallback for scanned pages within otherwise digital documents, not the primary extraction path. The quality report tracks which pages required OCR.
3. **Lean priority** — add complexity only when measured quality demands it. A second OCR engine is not justified without benchmark data showing the first engine underperforms on the actual corpus.

## Decision

Use **Docling's built-in OCR** (Tesseract via pytesseract, with EasyOCR as optional fallback) as the default. Keep the `Parser` interface open to a future engine swap so PaddleOCR (or another engine) can be dropped in when and if corpus-specific quality gaps are measured.

This means:

- MVP ships with one OCR engine: Tesseract, as already bundled in Docling.
- The `Parser` adapter accepts an optional `ocr_engine` parameter (default: `"tesseract"`).
- If PaddleOCR proves better on German or Portuguese corpus samples, it is added behind the same interface and the `ocr_engine` parameter supports `"paddleocr"`.
- No second engine is installed or configured until a quality gap is demonstrated in the evaluation harness.

## Consequences

### Positive

- Zero incremental integration work for MVP. Docling's OCR path is battle-tested on mixed documents.
- Tesseract supports German, Portuguese, and English with mature language data files (deu, por, eng). Air-gapped installation is a single `apt install tesseract-ocr tesseract-ocr-deu tesseract-ocr-por` (or equivalent).
- The `Parser` interface prevents vendor lock — swapping OCR engines is a config change, not a refactor.
- Lean: no second model, no second dependency, no second failure mode to debug in Phase 1–2.

### Negative

- Tesseract's accuracy on complex layouts (multi-column, dense tables, low-contrast scans) is lower than PaddleOCR's. Scanned textbooks with mixed German/English text on the same page may produce degraded output.
- EasyOCR (Docling's optional fallback) is Python-pure but slower than Tesseract and weaker on German.
- If the production corpus turns out to be 30%+ scanned pages with complex layouts, we will need PaddleOCR early — and the eval harness must catch this before it becomes a user-visible quality issue.

## Upgrade path

If the evaluation harness measures unacceptable OCR quality on the production corpus, the upgrade is:

1. Add PaddleOCR as a dependency (`pip install paddlepaddle paddleocr`).
2. Implement `PaddleOCREngine` behind the `Parser` interface.
3. Configure per-language or per-document-type engine selection.
4. Re-run the corpus through ingestion (idempotent, parser-version-aware — per ADR-0002 rules).
5. Update `STACK_REFERENCES.md` with the PaddleOCR pin.

This is a 1–2 day change given the interface discipline, not a replumbing.

## Alternatives considered

- **PaddleOCR as the only engine from day one** — rejected. Over-engineering for a corpus that is primarily digital-born. The dependency is heavier (PaddlePaddle framework), and the gain is theoretical until measured.
- **EasyOCR as primary** — rejected. Weaker multilingual support than Tesseract, no compelling advantage for our languages.
- **Tesseract + PaddleOCR hybrid from day one** — rejected. Two engines double the integration surface, the failure modes, and the dependency weight. The Parser interface makes a future hybrid trivial; no need to pay the cost now.
- **Surya OCR** (https://github.com/VikParuchuri/surya) — rejected. Newer, promising for layout-aware extraction, but less mature than Tesseract and not yet in Docling's integration path. Revisit in Phase 7 if advanced retrieval requires better table/formula extraction from scans.
- **Cloud OCR APIs** — rejected immediately. Violates air-gapped readiness.

## Revisit triggers

Reopen this ADR if any of the following happens:

- The Phase 2 quality report shows OCR confidence below 70% on more than 5% of pages on the production corpus.
- A specific document type (scanned German legal documents, Portuguese academic papers) consistently underperforms in retrieval eval due to OCR errors.
- A newer local OCR engine (Surya, or a successor) is integrated into Docling's pipeline and benchmarks better on our corpus.
- PaddleOCR releases a significantly lighter install (no PaddlePaddle framework required) — reduces the cost of adding a second engine.

## References

- Tesseract OCR — https://github.com/tesseract-ocr/tesseract (accessed 2026-05-14)
- PaddleOCR — https://github.com/PaddlePaddle/PaddleOCR (accessed 2026-05-14)
- Docling OCR documentation — https://docling-project.github.io/docling/ (accessed 2026-05-14; researcher to pin exact OCR section at implementation time)
- EasyOCR — https://github.com/JaidedAI/EasyOCR (accessed 2026-05-14)
- Surya OCR — https://github.com/VikParuchuri/surya (accessed 2026-05-14, for future reference only)
- Internal: `docs/uber-rag/INGESTION_PIPELINES.md`
- Internal: `docs/uber-rag/STACK_REFERENCES.md` § Parsing and ingestion
- Internal: ADR-0002 (ingestion orchestration — parser-version-aware idempotency rules)
