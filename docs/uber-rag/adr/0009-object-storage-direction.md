# ADR-0009: Object Storage Direction for Phase 2 — SeaweedFS as Lead Candidate
Status: Accepted
Date: 2026-05-16

## Context

Phase 2 needs durable object storage for original uploads, parsed artifacts, provenance outputs, and later ingestion byproducts. The current project memory still treats MinIO as the default candidate, but the Phase 2 entry review found that MinIO’s current packaging, licensing, and maintenance posture now carries more platform risk than it did when the stack table was first drafted.

The user’s confirmed priorities for Phase 2 are:

- clean long-term license and maintenance posture over easiest dev setup
- high ingestion volume
- air-gapped readiness
- strong structured parsing outputs rather than flat blobs only
- modular adapters over vendor lock-in

The main choices reviewed were MinIO, SeaweedFS, and other self-hosted S3-compatible systems.

## Decision

Make **SeaweedFS** the default object-storage direction for Phase 2, replacing MinIO as the lead candidate.

This decision is **reversible** if a later requirement proves that Phase 2 or later phases need S3 features that SeaweedFS cannot provide with acceptable complexity.

## Consequences

### Positive

- Better matches the current preference for cleaner long-term posture.
- Keeps the object-storage layer self-hosted and air-gap friendly.
- Fits the Phase 2 need to store originals and parsed artifacts without binding the design to a more controversial platform posture.
- Preserves adapter discipline: object storage remains an infrastructure seam, not a product assumption.

### Negative

- SeaweedFS may provide less complete S3 feature parity than MinIO-derived paths in some areas.
- The team may need to validate a few concrete API/ops assumptions instead of relying on widespread MinIO examples.
- Switching the lead candidate now means some existing stack references and mental defaults must be updated.

## Alternatives considered

- **MinIO / AIStor** — not selected as the lead candidate. Technical fit remains plausible, but the current licensing/packaging/maintenance posture no longer aligns as cleanly with the project’s stated preference for low long-term platform risk.
- **MinIO-derived forks** — not selected as the lead candidate. Some may preserve stronger S3 parity, but they inherit either legal or maintenance uncertainty that the project does not need to accept by default at Phase 2.
- **Ceph RGW** — not selected. Powerful and mature, but operationally heavier than Phase 2 needs.
- **Garage** — not selected. Interesting, but weaker fit for the project’s current priority ordering than SeaweedFS.

## References

- SeaweedFS repository — https://github.com/seaweedfs/seaweedfs (accessed 2026-05-16)
- MinIO docs — https://min.io/docs/minio/linux/index.html (accessed 2026-05-16)
- MinIO repository — https://github.com/minio/minio (accessed 2026-05-16)
- Internal research note — `docs/uber-rag/research/2026-05-16-phase-2-entry.md`
- Internal stack references — `docs/uber-rag/STACK_REFERENCES.md`

## Revisit triggers

- If the required S3 compatibility surface for Phase 2/3 exceeds what SeaweedFS can support cleanly.
- If SeaweedFS operational behavior proves poor under the expected artifact/object workload.
- If MinIO or another alternative materially improves its posture and again becomes the cleaner long-term default.
