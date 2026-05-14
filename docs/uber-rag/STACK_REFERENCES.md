# Stack References

This file is the durable reference map for Uber-RAG. Update it after research. Prefer official docs and primary papers. Include access dates and implementation impact.

Access date placeholder: replace with the current date when verified.

## OpenCode agent configuration

- OpenCode Agents: https://opencode.ai/docs/agents/
  - Notes: Markdown agents live in `.opencode/agents/` or `~/.config/opencode/agents/`. Agent files use YAML frontmatter. `mode` can be `primary`, `subagent`, or `all`. Current docs prefer `steps` over legacy `maxSteps`.
- OpenCode Permissions: https://opencode.ai/docs/permissions/
  - Notes: Use `permission`; legacy `tools` config is deprecated. Permissions support `allow`, `ask`, and `deny`; object syntax supports patterns. Built-in keys include read, edit, glob, grep, bash, task, webfetch, websearch, external_directory, doom_loop.
- OpenCode Config: https://open-code.ai/en/docs/config
  - Notes: Project config can live in `opencode.json`; `.opencode/agents/` is supported.

## Frontend

- Next.js App Router: https://nextjs.org/docs/app
- React: https://react.dev/
- TypeScript: https://www.typescriptlang.org/docs/

Implementation impact:
- UI must call public FastAPI only.
- UI must not directly access Qdrant, OpenSearch, PostgreSQL, MinIO, LLM, or worker services.

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

Implementation impact:
- Store originals and parsed artifacts in object storage.
- Never expose MinIO directly to frontend users.
- Source fetch must pass through backend ACL checks.

## Vector retrieval

- Qdrant docs: https://qdrant.tech/documentation/
- Qdrant Hybrid Queries: https://qdrant.tech/documentation/search/hybrid-queries/
- Qdrant Filtering: https://qdrant.tech/documentation/search/filtering/
- Qdrant Quantization: https://qdrant.tech/documentation/guides/quantization/

Implementation impact:
- Use payload filters for ACL and metadata.
- Use dense + sparse retrieval, fusion, and staged retrieval.
- Quantization requires measurement before production.

## Lexical search

**Decision: OpenSearch (ADR-0001, Accepted 2026-05-14).** Tantivy considered and rejected. Vespa deferred — revisit at 50M+ chunks.

- OpenSearch docs: https://docs.opensearch.org/
- OpenSearch neural/hybrid search: https://docs.opensearch.org/latest/search-plugins/neural-search/
- OpenSearch document-level security: https://docs.opensearch.org/latest/security/access-control/document-level-security/

Considered, rejected (see ADR-0001):
- Tantivy: https://tantivy-search.github.io/ — embeddable Rust BM25 engine; rejected for lack of DLS, clustering, and managed multilingual analyzers.
- Vespa hybrid search: https://docs.vespa.ai/en/learn/tutorials/hybrid-search.html — deferred; revisit at large scale.

Implementation impact:
- Exact lookup, phrase search, IDs, page references, and rare terms need lexical search.
- OpenSearch DLS is defense in depth — application-level ACL filters remain mandatory at every retrieval layer (see SECURITY_ACL.md).

## Parsing and ingestion

- Docling docs: https://docling-project.github.io/docling/
- Docling supported formats: https://docling-project.github.io/docling/usage/supported_formats/
- Tesseract OCR: https://tesseract-ocr.github.io/
- PaddleOCR: https://github.com/PaddlePaddle/PaddleOCR

Implementation impact:
- Use Docling as primary parser adapter.
- Keep parser version, artifact hash, page anchors, layout, table, and OCR quality metadata.
- Book ingestion requires hierarchy extraction.

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

## Embeddings and reranking

- BGE-M3 model card: https://huggingface.co/BAAI/bge-m3
- BGE documentation: https://bge-model.com/bge/bge_m3.html
- BGE reranker v2 m3 model card: https://huggingface.co/BAAI/bge-reranker-v2-m3
- FlagEmbedding repo: https://github.com/FlagOpen/FlagEmbedding

Implementation impact:
- BGE-M3 supports dense, sparse, and multivector retrieval.
- Start with dense + sparse + cross-encoder rerank.
- Use multivector only as a later precision stage or for selected corpora.
- Hide embedding model behind an `Embedder` interface so swap-out is a config change, not a refactor.

## LLM serving

**LLM model selection in progress (ADR-0003, Proposed 2026-05-14).** Llama 3.3 70B has been reclassified from default to candidate. Final model choice closes via ADR-0004 after the benchmark plan runs on 2×3090 hardware.

Serving runtime: vLLM is the working default per ADR-0003's benchmark plan. llama.cpp remains a candidate for lower-memory scenarios. Both stay behind an OpenAI-compatible internal adapter.

- vLLM OpenAI-compatible server: https://docs.vllm.ai/en/latest/serving/openai_compatible_server/
- llama.cpp server: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

Candidate models (to be benchmarked, see ADR-0003):
- Llama 3.3 70B Instruct: https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct — strong English, heavy on 2×3090.
- Qwen2.5 32B Instruct: https://huggingface.co/Qwen/Qwen2.5-32B-Instruct — strong multilingual, fits 2×3090 at FP8/INT8.
- Mistral Small 3.x (~24B): https://huggingface.co/mistralai — recent; researcher to confirm exact current 3.x version at benchmark time.

Implementation impact:
- Do not pick the LLM by reputation. Pick by the project's own RAG eval (faithfulness, citation accuracy, negative-answer compliance, multilingual quality).
- Hide LLM runtime behind an internal OpenAI-compatible adapter so model and runtime are independently swappable.
- Benchmark vLLM vs llama.cpp for latency, throughput, memory, and concurrency on the winning model.

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

## DeepEye and workflow-centric agent research

- DeepEye project: https://deepeye.tech/deepeye.html
- DeepEye paper: https://arxiv.org/abs/2603.28889
- DeepEye GitHub: https://github.com/HKUSTDial/DeepEye

Implementation impact:
- Useful pattern: workflow DAG, validation, optimization, execution, context isolation, auditable history.
- DeepEye is wired as a real agent (`search/deepeye`); planner and primary builder can dispatch it directly for decision-critical research.
