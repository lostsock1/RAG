# Phase 2 Entry Design

Date: 2026-05-16
Topic: Uber-RAG Phase 2 entry-gate stack direction
Status: Proposed for planning

## Goal

Define the best-fit Phase 2 architecture direction for Uber-RAG ingestion given the confirmed priorities: rich structured parsing over flat text, table fidelity as a hard requirement, seamless operation across local CPU, local GPU, and remote API deployments, strong long-run resumability, and a clean long-term licensing/maintenance posture.

## Constraints and priorities

- API-first and ACL-aware architecture remain invariant.
- Phase 2 is ingestion MVP, not final retrieval or chat quality closure.
- Deployment must work in local CPU, local GPU, and remote API environments.
- Backend selection should happen per deployment config, not per document/job.
- Rich structured artifacts matter more than simple Markdown extraction.
- Tables are critical; formulas matter but are secondary.
- Higher operational complexity is acceptable if ingestion reliability improves.
- Long-term license/maintenance posture matters more than easiest dev setup.

## Approaches considered

### Approach 1: Lean-modernized

- Docling
- SeaweedFS
- Celery + Redis
- local/remote parser interface

Why rejected:

- Too much resumability and retry correctness would stay in application code.
- At expected high ingestion volume, manual recovery cost is too high.
- Stronger structure-preserving parsing deserves a more durable orchestration layer.

### Approach 2: Balanced-strong

- Docling as common parser shell and normalization boundary
- Temporal for durable ingestion orchestration
- SeaweedFS for object/artifact storage
- deployment-configured parsing backends: local CPU, local GPU, remote API
- one normalized structured parsed-artifact schema shared across all backends

Why recommended:

- Best fit for high-volume ingestion with resumability and checkpointing.
- Preserves rich structural outputs needed for table-heavy corpora.
- Supports seamless local/remote operation without per-job routing complexity.
- Keeps adapter boundaries clean so providers and local backends remain replaceable.

### Approach 3: Quality-maximal

- VLM-heavy parsing everywhere from day one
- Temporal
- SeaweedFS
- richer artifact validation and preservation on every path

Why rejected:

- Adds more complexity than Phase 2 needs.
- Raises implementation and ops burden before the core ingestion loop is proven.

## Recommended design

### 1. Parser architecture

Use a single document-understanding interface with one normalized structured artifact contract.

The interface should support three deployment profiles:

- **CPU local profile** — safe baseline for environments without useful GPU capacity.
- **GPU local profile** — higher-fidelity structured parsing path for rich layouts and table-heavy documents.
- **Remote API profile** — provider-swappable document-understanding path for deployments that prefer external inference.

Backend selection happens at deployment configuration time, not at per-document routing time.

Docling remains the parser shell because it provides strong document structure handling, good air-gapped fit, and a common output boundary for downstream chunking and provenance storage.

### 2. Parsed-artifact contract

Phase 2 should treat the parsed artifact as a first-class product, not a transient blob.

The normalized artifact should preserve at minimum:

- page anchors
- reading order
- section hierarchy where available
- tables and table boundaries
- layout regions / bounding boxes where available
- OCR/parser provenance
- parser/backend version metadata
- source artifact references

This contract is required so local CPU, local GPU, and remote API deployments can feed the same chunking/indexing pipeline without downstream branching.

### 3. OCR and document understanding strategy

Use local-first design, but keep the remote document-understanding path available in Phase 2.

- CPU local path is the baseline compatibility mode.
- GPU local path is the preferred high-fidelity mode for scanned or complex-layout documents.
- Remote API path is allowed, but must sit behind the same parser/document-understanding interface and produce the same normalized artifact shape.

Because tables are critical, flat OCR text extraction is not enough as the primary design. Structured extraction quality is the main decision driver.

### 4. Ingestion orchestration

Temporal is the current front-runner for Phase 2.

Reason:

- High expected ingestion volume
- acceptance of more operational complexity in exchange for stronger resumability
- need to coordinate heterogeneous parsing backends cleanly
- desire to checkpoint and resume long-running structured parsing flows without relying on application-only recovery logic

Celery + Redis remains the lighter fallback, but only if the project deliberately accepts more application-owned recovery complexity. Based on the confirmed priorities, it is no longer the preferred default.

### 5. Object storage

SeaweedFS is the current front-runner for Phase 2 object/artifact storage.

Reason:

- cleaner long-term license and maintenance posture than current MinIO/AIStor direction
- adequate fit for ingestion artifacts and source blobs
- supports the project goal of avoiding avoidable platform/legal risk early

Tradeoff:

- may offer less complete S3 feature parity than MinIO-derived paths
- but current Phase 2 priorities favor posture and maintainability over maximum S3 feature completeness

## Data flow

Recommended Phase 2 ingestion shape:

1. Document uploaded and stored in object storage.
2. Ingestion workflow created with durable run/stage identity.
3. Active parser backend selected from deployment config.
4. Parser produces normalized structured artifact.
5. Parsed artifact and provenance stored durably.
6. Downstream chunking/embedding/indexing consume the normalized artifact, not backend-specific output.
7. Failures resume from persisted stage boundaries rather than forcing whole-document reprocessing when avoidable.

## Error handling and resilience

- Persist stage boundaries around parse output, not only around final indexing.
- Preserve parser/backend version and artifact hashes so re-runs remain auditable.
- Treat remote and local parsing backends as interchangeable only at the interface level, not at raw output level.
- Make structured artifact validation explicit so malformed table/layout output is caught before chunking/indexing.

## Tradeoffs

### Positive

- Strong fit for high-volume, structure-sensitive ingestion.
- Preserves local/remote flexibility without per-job routing complexity.
- Keeps the parsing contract modular and future-swappable.
- Better aligned with critical table fidelity requirements.

### Negative

- More upfront design and operational work than a Celery + filesystem/MinIO-style MVP.
- Temporal raises deployment complexity and team learning cost.
- A rich parsed-artifact contract increases implementation scope in Phase 2.

## Decisions implied by this design

This design implies three Phase 2 planning/ADR closures:

1. Object storage default should be re-evaluated, with SeaweedFS as current lead candidate.
2. Ingestion orchestration should be re-evaluated, with Temporal as current lead candidate.
3. OCR/parsing design should be updated from a simple OCR-engine framing to a structured document-understanding architecture framing.

## Out of scope

- Per-job backend routing
- final retrieval quality tuning
- final chat/generation design
- formula-specialized parsing beyond baseline support
- production benchmark closure for every parser/backend candidate

## Recommended next planning step

Use this design as the basis for Phase 2 planning artifacts:

- phase-entry research note
- `PROJECT_STATE.md` update
- `TASKS.md` update
- ADR drafts for storage, orchestration, and OCR/pipeline architecture
