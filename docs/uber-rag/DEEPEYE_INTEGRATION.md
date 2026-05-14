# DeepEye Integration

## Purpose

DeepEye-style workflow thinking is useful for Uber-RAG because complex RAG development involves many nodes:

- research
- architecture
- parser design
- ingestion workflow
- indexing
- retrieval
- ACL validation
- evaluation
- deployment

## Tool usage

If a DeepEye MCP/custom tool is configured in OpenCode, it should be exposed under names matching `deepeye_*`.

Uber-RAG may call these tools with approval for:

- workflow decomposition
- DAG validation
- multi-source research synthesis
- dependency comparison
- eval workflow design
- dataflow debugging

## Fallback

If DeepEye is not available, Uber-RAG manually uses this process:

```text
Intent
  -> constraints
  -> workflow DAG
  -> node list
  -> inputs/outputs
  -> validation rules
  -> execution order
  -> audit trail
```

## Workflow node schema

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

## When to call DeepEye

Call it for complex planning and research, not for trivial edits.

Good cases:

- compare Qdrant/OpenSearch/Vespa for a specific deployment
- design a multi-stage ingestion workflow
- create an evaluation DAG
- map ACL leakage threats
- decompose cross-corpus retrieval into testable nodes

Bad cases:

- simple typo fix
- one-line code change
- small local refactor
