# Stack References

This file is the durable reference map for Uber-RAG. Update it after research. Prefer official docs and primary papers. Include access dates and implementation impact.

Last reviewed: 2026-06-12 (Phase F entry).

**Model rows are frozen (binding user directive, 2026-06-11):** BGE-M3 (ADR-0013), bge-reranker-v2-m3 (ADR-0014), ppq.ai Llama 3.3 70B (ADR-0004), MiniCheck verifier variants config-only — CPU-only VPS, generation via API, no GPU. Phase-gate row-walks skip the embedding/reranker/LLM/verifier rows until the freeze lifts; their reopen triggers live in the respective ADRs.

Breadth counterpart: `~/.config/opencode/agents/RAG/_stack_refs.md` is the status-tagged candidate survey (every candidate, Accepted/Candidate/Rejected/Deferred); this file is the depth doc (what is actually wired, with implementation impact). The two are kept in sync at phase gates. As of 2026-06-12 the breadth file is behind this one (last reviewed 2026-05-15; still lists MinIO as object-store default vs ADR-0009 SeaweedFS, and pre-freeze model statuses).

## OpenCode agent configuration

- OpenCode Agents: https://opencode.ai/docs/agents/
  - Notes: Markdown agents live in `.opencode/agents/` or `~/.config/opencode/agents/`. Agent files use YAML frontmatter. `mode` can be `primary`, `subagent`, or `all`. Current docs prefer `steps` over legacy `maxSteps`.
- OpenCode Permissions: https://opencode.ai/docs/permissions/
  - Notes: Use `permission`; legacy `tools` config is deprecated. Permissions support `allow`, `ask`, and `deny`; object syntax supports patterns. Built-in keys include read, edit, glob, grep, bash, task, webfetch, websearch, external_directory, doom_loop.
- OpenCode Config: https://opencode.ai/docs/config
  - Notes: Project config can live in `opencode.json`; `.opencode/agents/` is supported. (URL normalized 2026-06-12 to the canonical `opencode.ai` domain used by the other entries; the previously recorded `open-code.ai` is an off-domain mirror.)

## Frontend

- Next.js App Router: https://nextjs.org/docs/app
- React: https://react.dev/
- TypeScript: https://www.typescriptlang.org/docs/

Frontend E2E rig (Phase F entry gate; decision pending — master plan says pick Playwright unless entry-gate evidence says otherwise):
- Playwright docs: https://playwright.dev/docs/intro
- Playwright repo: https://github.com/microsoft/playwright
- Cypress docs: https://docs.cypress.io/

Implementation impact:
- UI must call public FastAPI only.
- UI must not directly access Qdrant, OpenSearch, PostgreSQL, object storage, LLM, or worker services.
- Phase F F4 runs the chosen E2E rig in CI against the compose stack (`AUTH_MODE=dev`, stub LLM, seeded fixture corpus); specs wait on API state, not timeouts.

## API backend

- FastAPI: https://fastapi.tiangolo.com/
- FastAPI OpenAPI docs: https://fastapi.tiangolo.com/reference/openapi/docs/
- Pydantic: https://docs.pydantic.dev/
- SQLAlchemy: https://docs.sqlalchemy.org/
- Alembic: https://alembic.sqlalchemy.org/

Implementation impact:
- Use OpenAPI as public contract.
- Generate typed clients when possible.
- All endpoints must enforce auth, ACL, and audit rules.

## Auth and ACL

- Keycloak Authorization Services: https://www.keycloak.org/docs/latest/authorization_services/index.html
- Keycloak Admin REST API: https://www.keycloak.org/docs-api/latest/rest-api/index.html
- OIDC Core: https://openid.net/specs/openid-connect-core-1_0.html

Implementation impact:
- Use OIDC tokens.
- Resolve tenant, user, groups, roles, and scopes in the backend.
- Do not trust frontend-only ACL.

## Metadata database

- PostgreSQL docs: https://www.postgresql.org/docs/
- PostgreSQL Row Security Policies: https://www.postgresql.org/docs/current/ddl-rowsecurity.html

Implementation impact:
- Use PostgreSQL for metadata, ACL, jobs, versions, audit, and eval results.
- Consider row-level security for defense in depth, but keep application-level ACL mandatory.

## Object storage

- MinIO docs: https://min.io/docs/minio/linux/index.html
- MinIO S3 compatibility: https://docs.min.io/aistor/developers/s3-api-compatibility/
- SeaweedFS repo: https://github.com/seaweedfs/seaweedfs

Implementation impact:
- Store originals and parsed artifacts in object storage.
- Never expose the object store directly to frontend users.
- Source fetch must pass through backend ACL checks.

Phase 2 entry review note:
- MinIO remains documented here because it was the original candidate, but Phase 2 research now treats its licensing/maintenance posture as less attractive than before.
- SeaweedFS is the **accepted default** for Phase 2 object/artifact storage per ADR-0009.

## Vector retrieval

- Qdrant docs: https://qdrant.tech/documentation/
- Qdrant Hybrid Queries: https://qdrant.tech/documentation/search/hybrid-queries/
- Qdrant Filtering: https://qdrant.tech/documentation/search/filtering/
- Qdrant Quantization: https://qdrant.tech/documentation/guides/quantization/
- Qdrant text search: https://qdrant.tech/documentation/guides/text-search/
- Qdrant multitenancy: https://qdrant.tech/documentation/manage-data/multitenancy/

Implementation impact:
- Use payload filters for ACL and metadata.
- Use dense + sparse retrieval, fusion, and staged retrieval.
- Quantization requires measurement before production.
- Phase 3 entry review (2026-05-20): Qdrant now documents both RRF and DBSF in its hybrid-query stack, but it is still not the lexical system of record for BM25/phrase ranking.
- Phase 3 entry review (2026-05-20): require indexed ACL fields before production filtering; strict mode / unindexed-filter guards should be enabled where available.

## Lexical search

**Decision: OpenSearch (ADR-0001, Accepted 2026-05-14).** Tantivy considered and rejected. Vespa deferred — revisit at 50M+ chunks.

- OpenSearch docs: https://docs.opensearch.org/
- OpenSearch neural/hybrid search: https://docs.opensearch.org/latest/search-plugins/neural-search/
- OpenSearch document-level security: https://docs.opensearch.org/latest/security/access-control/document-level-security/
- OpenSearch hybrid query: https://docs.opensearch.org/latest/query-dsl/compound/hybrid/
- OpenSearch match phrase query: https://docs.opensearch.org/latest/query-dsl/full-text/match-phrase/
- OpenSearch bool query: https://docs.opensearch.org/latest/query-dsl/compound/bool/
- OpenSearch keyword search: https://docs.opensearch.org/latest/search-plugins/keyword-search/

Considered, rejected (see ADR-0001):
- Tantivy: https://tantivy-search.github.io/ — embeddable Rust BM25 engine; rejected for lack of DLS, clustering, and managed multilingual analyzers.
- Vespa hybrid search: https://docs.vespa.ai/en/learn/tutorials/hybrid-search.html — deferred; revisit at large scale.

Implementation impact:
- Exact lookup, phrase search, IDs, page references, and rare terms need lexical search.
- OpenSearch DLS is defense in depth — application-level ACL filters remain mandatory at every retrieval layer (see SECURITY_ACL.md).
- Phase 3 entry review (2026-05-20): use top-level hybrid/bool filters for ACL gating; do not rely on `post_filter` for ACL enforcement in hybrid retrieval.
- Phase 3 entry review (2026-05-20): OpenSearch remains the lexical/BM25/phrase-search backend of record for Search MVP.

## Parsing and ingestion

- Docling docs: https://docling-project.github.io/docling/
- Docling supported formats: https://docling-project.github.io/docling/usage/supported_formats/
- Tesseract OCR: https://tesseract-ocr.github.io/
- PaddleOCR: https://github.com/PaddlePaddle/PaddleOCR
- PaddleOCR docs: https://www.paddleocr.ai/latest/en/index.html

Implementation impact:
- Use Docling as primary parser adapter.
- Keep parser version, artifact hash, page anchors, layout, table, and OCR quality metadata.
- Book ingestion requires hierarchy extraction.
- Phase 2 entry review reframed this row from “OCR engine choice” to “structured document-understanding architecture across local CPU, local GPU, and remote API deployments”; see ADR-0011.

## Workflow orchestration

**Decision: Celery + Redis for MVP (ADR-0002, Accepted 2026-05-14).** Temporal kept on the roadmap; ingestion stages must follow the 6 idempotency rules in ADR-0002 so a future migration is wrapping work, not a rewrite.

- Celery docs: https://docs.celeryq.dev/en/stable/
- Flower (Celery monitoring): https://flower.readthedocs.io/
- Redis docs: https://redis.io/docs/latest/

Deferred (see ADR-0002):
- Temporal docs: https://docs.temporal.io/ — durable workflow engine; migrate when a single run regularly exceeds 30 min OR more than 10% of runs need manual resumption.
- RabbitMQ docs: https://www.rabbitmq.com/docs — alternative broker, not adopted; Redis is sufficient given existing dependency footprint.

Implementation impact:
- Every ingestion stage must be idempotent and externally checkpointed (Postgres run/stage tables).
- Stage functions must accept `run_id` and `stage_id` as inputs; never rely on Celery task IDs for identity.
- This discipline earns the right to migrate to Temporal later without rewriting stage logic.

Phase 2 entry review note:
- Temporal is now the **accepted default** for the approved high-volume / high-resumability Phase 2 profile per ADR-0010.

## Embeddings and reranking

- BGE-M3 model card: https://huggingface.co/BAAI/bge-m3
- BGE documentation: https://bge-model.com/bge/bge_m3.html
- BGE reranker v2 m3 model card: https://huggingface.co/BAAI/bge-reranker-v2-m3
- BGE reranker v2 gemma model card: https://huggingface.co/BAAI/bge-reranker-v2-gemma
- BGE reranker v2 MiniCPM layerwise model card: https://huggingface.co/BAAI/bge-reranker-v2-minicpm-layerwise
- FlagEmbedding repo: https://github.com/FlagOpen/FlagEmbedding
- BGE multilingual Gemma 2 model card: https://huggingface.co/BAAI/bge-multilingual-gemma2

Implementation impact:
- BGE-M3 supports dense, sparse, and multivector retrieval.
- Start with dense + sparse + cross-encoder rerank.
- Use multivector only as a later precision stage or for selected corpora.
- Hide embedding model behind an `Embedder` interface so swap-out is a config change, not a refactor.
- Phase 3 entry review (2026-05-20): no deprecation signal found for BGE-M3. `bge-multilingual-gemma2` is a candidate for stronger multilingual dense retrieval, but not a clean replacement for BGE-M3's single-model dense+sparse+multivector role.
- Phase 4 entry review (2026-05-21): BGE-M3 remains source-backed for the embedding row. ADR-0014 closes the reranker row by explicitly reconfirming `bge-reranker-v2-m3` as the Phase 4 default because it best fits the current hot-path latency, no-GPU development, and low-friction operational/security constraints. `bge-reranker-v2-gemma` remains the first reopen candidate if quality targets are missed; `bge-reranker-v2-minicpm-layerwise` is not the default because of `trust_remote_code` friction.
- DeepEye verification (2026-05-21): independent research unanimously confirms ADR-0014. New findings: (1) `v2-gemma` is deprecated by HuggingFace Inference — weakens it as reopen candidate; (2) `bge-reranker-v2.5-gemma2-lightweight` (9B, BEIR 63.1) is a future GPU-era candidate; (3) community ONNX export (`newtechstudio/bge-reranker-v2-m3-onnx`) with TEI ORT backend delivers ~400ms CPU latency for 20 pairs; (4) `trust_remote_code` risk is worse than originally documented — CVE-2026-27893 (HIGH 8.8), demonstrated RCE PoCs; (5) MIRACL multilingual gap between v2-m3 and v2-gemma is only +0.6 nDCG@10 — negligible for Uber-RAG's trilingual corpus.

## LLM serving

**Decision: ppq.ai (OpenAI-compatible aggregator) with Llama 3.3 70B Instruct as default (ADR-0004, Accepted 2026-05-14; provider renamed from OpenRouter to ppq.ai 2026-05-15 — same concept, OpenAI-compat).** Hermes 4 70B as instruction-heavy fallback. Local serving (vLLM, llama.cpp) deferred until GPU hardware available.

- ppq.ai landing: https://ppq.ai (verify exact docs URL on first use)
- ppq.ai OpenAI-compatible endpoint: `https://api.ppq.ai/v1` (verify exact path on first use)
- OpenRouter (pricing reference for ADR-0004 cost analysis only): https://openrouter.ai/docs
- Default model: `meta-llama/llama-3.3-70b-instruct` — https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct
- Fallback model: `nousresearch/hermes-4-70b` — https://huggingface.co/NousResearch/Hermes-4

### LLM adapter

All LLM calls go through an internal OpenAI-compatible adapter (`LlmBackend` interface). Provider swap is a config change: `LLM_ADAPTER` env var (`ppq` | `vllm` | `llamacpp`).

Serving runtime: vLLM remains an expected future candidate once GPU hardware lands. llama.cpp remains a candidate for lower-memory scenarios. Phase 4 entry review (2026-05-21) adds **SGLang** as a first-class future runtime candidate; current TGI docs are now in maintenance mode and explicitly recommend vLLM, SGLang, and llama.cpp going forward.

Deferred until GPU hardware available:
- vLLM OpenAI-compatible server: https://docs.vllm.ai/en/latest/serving/openai_compatible_server/
- SGLang docs: https://docs.sglang.ai/
- llama.cpp server: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- Hugging Face TGI docs: https://huggingface.co/docs/text-generation-inference

## Evaluation and quality

- RAGBench: https://arxiv.org/abs/2407.11005
- CRUD-RAG: https://arxiv.org/abs/2401.17043
- MultiHop-RAG: https://arxiv.org/abs/2401.15391
- HotpotQA: https://hotpotqa.github.io/
- MuSiQue: https://github.com/stonybrooknlp/musique
- 2WikiMultiHopQA: https://github.com/Alab-NII/2wikimultihop

Implementation impact:
- Build internal goldsets first.
- Include exact, semantic, book hierarchy, table, formula, negative, cross-lingual, and ACL leakage tests.

### Grounding verifiers (Phase D entry, verified 2026-06-11)

- MiniCheck (paper, EMNLP 2024): https://arxiv.org/abs/2404.10774 — sentence-level grounding fact-checker family
- `lytang/MiniCheck-Flan-T5-Large`: https://huggingface.co/lytang/MiniCheck-Flan-T5-Large — **MIT**, 783M, plain transformers (no trust_remote_code); LLM-AggreFact best-under-1B per card. **ADR-0019 default.**
- `lytang/MiniCheck-RoBERTa-Large`: MIT, 0.4B — faster fallback candidate.
- `bespokelabs/Bespoke-MiniCheck-7B`: **no license on card** + custom_code — disqualified for commercial default.
- `vectara/hallucination_evaluation_model` (HHEM-2.x): Apache-2.0 but requires `trust_remote_code=True` (HHEMv2 custom architecture) — rejected for default per the ADR-0014 trust_remote_code posture; revisit if standard-architecture release appears.
- `ibm-granite/granite-guardian-3.1/3.2`: Apache-2.0, 2–3B, generation-style judging — GPU-era reopen candidates.
- Full comparison + extracted inference recipe: `docs/uber-rag/research/2026-06-11-phase-d-entry.md`.

## Meta research sources

- Awesome-AI-Memory (curated RAG/memory papers, projects, benchmarks): https://github.com/IAAR-Shanghai/Awesome-AI-Memory

Implementation impact:
- Pre-check this index before dispatching DeepEye on any RAG- or memory-shaped question, and pass relevant starting points into the DeepEye prompt (research hierarchy per `~/.config/opencode/agents/RAG/_shared.md` and `DEEPEYE_INTEGRATION.md`).

## DeepEye and workflow-centric agent research

- DeepEye project: https://deepeye.tech/deepeye.html
- DeepEye paper: https://arxiv.org/abs/2603.28889
- DeepEye GitHub: https://github.com/HKUSTDial/DeepEye

Implementation impact:
- Useful pattern: workflow DAG, validation, optimization, execution, context isolation, auditable history.
- DeepEye is wired as a real agent (`search/deepeye`); planner and primary builder can dispatch it directly for decision-critical research.
