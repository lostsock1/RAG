# Workflow Design

Conventions for decomposing Uber-RAG work into testable, traceable nodes. Use when planning a non-trivial feature (ingestion pipeline, retrieval flow, evaluation harness, ACL change) before implementation.

This is project-internal methodology. It is **not** related to the DeepEye agent — see `DEEPEYE_INTEGRATION.md` for that.

## Why this exists

Complex RAG development spans many interlocking concerns:

- research
- architecture
- parser design
- ingestion workflow
- indexing
- retrieval
- ACL validation
- evaluation
- deployment

Modeling a feature as a DAG of nodes — each with explicit inputs, outputs, validation rules, and dependencies — keeps the work auditable, testable, and resumable. It also surfaces hidden dependencies before they become integration pain.

## Decomposition process

For a non-trivial feature or change, walk this path before writing code:

```text
Intent
  -> constraints (ACL, latency, evaluability, ops)
  -> workflow DAG
  -> node list
  -> inputs / outputs per node
  -> validation rules per node
  -> execution order
  -> audit trail
```

The output is a written plan — in `TASKS.md`, an ADR, or a research note — listing the nodes, their dependencies, and the validation each must pass. Implementation then proceeds node by node.

## Workflow node schema

When the plan is structured enough to warrant a formal artifact, capture nodes in this shape:

```json
{
  "node_id": "string",
  "type": "tool|agent|human_review",
  "description": "string",
  "inputs": [
    {"name": "string", "type": "string", "description": "string"}
  ],
  "outputs": [
    {"name": "string", "type": "string", "description": "string"}
  ],
  "validation": ["string"],
  "depends_on": ["node_id"]
}
```

## When to use formal decomposition

Use it for:

- multi-stage ingestion workflow design
- evaluation DAG specification
- ACL threat decomposition
- cross-corpus retrieval breakdown
- any feature touching 3+ services or pipeline stages

Skip it for:

- single-file edits
- one-line code changes
- small local refactors
- typo fixes

## Relationship to other docs

- **ADRs** (`adr/NNNN-slug.md`) capture durable decisions about a node or a set of nodes. A workflow plan is operational; an ADR is durable.
- **`TASKS.md`** tracks live state of nodes in progress.
- **`DEEPEYE_INTEGRATION.md`** covers the DeepEye agent, which can be dispatched to research what informs a node's design. DeepEye does not author the workflow plan itself.
- **`RESEARCH_PROTOCOL.md`** covers how findings are recorded and referenced.
