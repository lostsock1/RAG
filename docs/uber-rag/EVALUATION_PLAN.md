# Evaluation Plan

## Goal

Continuously measure whether Uber-RAG can retrieve, cite, answer, and refuse correctly across books and loose documents.

## Evaluation layers

1. Ingestion completeness
2. Retrieval recall and precision
3. Reranking quality
4. Citation correctness
5. Answer faithfulness
6. Negative answer behavior
7. ACL leakage resistance
8. Latency and throughput
9. Update/delete correctness
10. Cross-lingual quality

## Minimum datasets

### Internal goldset

Create project-specific questions with known source spans.

Types:

- definitions
- exact source lookups
- formulas
- tables
- chapter/section questions
- comparisons
- multi-hop questions
- negative questions
- ACL tests

### Synthetic needles

Inject known statements into long documents and large corpora. Verify exact retrieval and answer citation.

### Regression set

Every bug becomes a regression test.

## Metrics

- ingestion completeness percent
- retrieval recall@k
- MRR
- reranker precision@k
- answer supported-claim rate
- unsupported-claim rate
- citation accuracy
- not-found accuracy
- ACL leakage count
- p50/p95 latency

## Judge rules

Local LLM judge can assist but must not be the only signal. Use deterministic checks where possible:

- expected document id present
- expected page range present
- forbidden document absent
- answer contains not-found when expected
- citation resolver returns authorized source only

## Eval API

See `API_CONTRACT.md` for endpoints.
