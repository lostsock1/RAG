# Phase 2 Entry Research Note

Date: 2026-05-16
Phase: Phase 2 — Ingestion MVP entry gate
Status: Complete

## Question

Can Uber-RAG proceed into Phase 2 without reopening stack decisions, and what changed in the current parser/OCR, orchestration, and object-storage landscape that should affect the next default choices?

## Scope checked

- Docling parser direction
- OCR / document-understanding path for English, German, and Portuguese corpora
- Celery + Redis vs Temporal for idempotent, resumable ingestion
- MinIO vs current air-gapped object-storage alternatives
- BGE-M3 only as a Phase-2-adjacent assumption check

## Method

- Reviewed current project memory and relevant ADRs.
- Ran comparative research with the available deep-research path.
- Preferred official docs, official repos, release notes, model cards, and primary papers.
- Cross-checked Awesome-AI-Memory for major RAG/memory shifts; no direct blocker emerged for the Phase 2 choices in scope.

## Findings

### 1. Parser shell

**Docling remains a strong parser shell candidate.**

Why:

- good fit for local and air-gapped execution
- strong structure-aware parsing orientation
- useful normalization boundary for downstream chunking/provenance

Risk:

- fast-moving release train means version pinning and compatibility checks are required

### 2. OCR / document understanding

The original “choose an OCR engine” framing is now too narrow for the project’s needs.

Why:

- the corpus priorities emphasize table fidelity and rich structure, not just text extraction
- local CPU, local GPU, and remote API deployments all matter
- remote path must support full document understanding, not OCR-only

Current direction:

- Docling as parser shell
- deployment-configured backend profiles
- structured artifact contract shared across local and remote backends
- tables, layout, anchors, provenance preserved as first-class outputs

### 3. Orchestration

**Temporal emerged as the stronger Phase 2 direction for the approved priorities.**

Why:

- high expected ingestion volume
- preference for stronger resumability and correctness over lower ops complexity
- long-running heterogeneous parsing flows benefit from durable workflow execution

Tradeoff:

- more operational complexity and learning cost than Celery + Redis

### 4. Object storage

**MinIO should no longer be treated as the safest default.**

Why:

- current packaging/licensing/maintenance posture raises avoidable platform risk
- cleaner long-term alternatives exist for the project’s priorities

Current lead candidate:

- **SeaweedFS**, because it offers a cleaner posture while still fitting the Phase 2 artifact/object-storage role

Tradeoff:

- less complete S3 feature parity than MinIO-derived paths in some areas

### 5. Embedding assumption

**BGE-M3 remains acceptable as a Phase-2-adjacent assumption.**

No Phase-2 entry blocker was found here.

## Entry-gate conclusion

**Phase 2 status: Provisional Go.**

Proceeding is reasonable, but the project should close three planning decisions before treating the stack as settled for Phase 2:

1. object storage direction
2. orchestration direction
3. structured parsing / document-understanding architecture direction

## Recommended follow-up artifacts

- ADR-0009 — object storage direction (SeaweedFS lead candidate)
- ADR-0010 — orchestration direction (Temporal lead candidate)
- ADR-0011 — structured document-understanding architecture
- `PROJECT_STATE.md` update
- `TASKS.md` update
- `STACK_REFERENCES.md` refresh for Phase 2 candidates and posture notes

## Sources

Access date for all external sources: 2026-05-16.

- Docling docs — https://docling-project.github.io/docling/
- Docling releases — https://github.com/docling-project/docling/releases
- PaddleOCR docs — https://www.paddleocr.ai/latest/en/index.html
- PaddleOCR repository — https://github.com/PaddlePaddle/PaddleOCR
- Tesseract OCR — https://tesseract-ocr.github.io/
- Temporal docs — https://docs.temporal.io/
- Celery docs — https://docs.celeryq.dev/en/stable/
- SeaweedFS repository — https://github.com/seaweedfs/seaweedfs
- MinIO docs — https://min.io/docs/minio/linux/index.html
- MinIO repository — https://github.com/minio/minio
- BGE-M3 model card — https://huggingface.co/BAAI/bge-m3
- Awesome-AI-Memory — https://github.com/IAAR-Shanghai/Awesome-AI-Memory
