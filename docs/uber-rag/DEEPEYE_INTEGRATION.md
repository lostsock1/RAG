# DeepEye Integration

DeepEye is a **peer primary agent** in OpenCode dedicated to exhaustive research. The Uber-RAG team dispatches DeepEye when deeper, multi-source, or decision-shaped research is needed.

This file is the project-living counterpart of the Research hierarchy in `~/.config/opencode/agents/RAG/_shared.md`. Keep both in sync.

## What DeepEye is

- **Agent path:** `/Users/djesys/.config/opencode/agents/search/deepeye.md`
- **Mode:** `primary` — DeepEye is not a subagent of the RAG team. It is a sibling primary that the RAG team dispatches via the Task tool.
- **Backed by:** `deepseek/deepseek-v4-pro`.
- **Owns its own subagents:** worker, proxy, scrapling, crawlee, translator-normalizer, instagram, maps, vision. These are DeepEye's internals, not RAG-team tools.
- **Protocol:** two-phase breadth → depth research with authority-source scraping, multilingual retrieval, and local-language-first investigation. Returns structured findings, sources, confidence levels, and follow-up questions.

## How to dispatch DeepEye

The RAG primary (`RAG/uber-rag`) and planner (`RAG/uber-rag-planner`) have `task: "search/deepeye": allow`. From those agents, dispatch via the Task tool:

```text
Task tool → subagent_type: "search/deepeye"
Prompt: detailed research question + context on why this matters for Uber-RAG
```

The researcher subagent (`RAG/uber-rag-researcher`) cannot dispatch DeepEye directly (`task: deny`); it flags candidates to the primary or planner.

## When to dispatch DeepEye

Dispatch DeepEye for:

- comparing Qdrant / OpenSearch / Vespa / Milvus for a specific deployment scenario
- benchmarking embedding or reranker candidates against current SOTA
- deep due diligence on a paper or technique surfaced by `STACK_REFERENCES.md` or [Awesome-AI-Memory](https://github.com/IAAR-Shanghai/Awesome-AI-Memory)
- investigating an ACL pattern, auth flow, or DLS implementation before committing to it
- any question that will be cited in an ADR
- background research before architecting a new pipeline stage
- multi-source synthesis where a single authoritative answer is not enough

Do **not** dispatch DeepEye for:

- a single API signature lookup (use `STACK_REFERENCES.md`, `webfetch`, or Exa)
- a version check on a known library
- one-line code changes
- typo fixes
- workflow-DAG decomposition (that is project methodology — see `WORKFLOW_DESIGN.md`)

## Pre-dispatch checklist

Before dispatching DeepEye on a RAG or memory question:

1. Check `STACK_REFERENCES.md` (project-living) and `~/.config/opencode/agents/RAG/_stack_refs.md` (seed) for relevant entries.
2. Scan [Awesome-AI-Memory](https://github.com/IAAR-Shanghai/Awesome-AI-Memory) for curated upstream sources.
3. Pass anything you find into the DeepEye prompt as starting points, so DeepEye does not re-derive what is already curated.

## After DeepEye returns

1. Extract findings relevant to the current task.
2. Record source URLs, access date, version (if available), and implementation impact in `STACK_REFERENCES.md` or a research note at `research/YYYY-MM-DD-topic.md`.
3. If findings challenge an existing ADR, draft a superseding ADR via `RAG/uber-rag-planner`.
4. Translate research-speak into plain language for the user (per the "user is not a RAG specialist" framing in `_shared.md`).

## Hard rules

- **Never dispatch DeepEye's internal subagents** (`search/worker`, `search/proxy`, `search/scrapling`, `search/crawlee`, `search/translator-normalizer`, `search/instagram`, `search/maps`, `search/vision`) directly from RAG agents. Dispatching them bypasses DeepEye's orchestration logic and produces worse output. Only `search/deepeye` is in the RAG team's task allowlist.
- **Never claim a current external fact without a source.** All DeepEye-derived claims must land in `STACK_REFERENCES.md` or a research note with access date.
- **If DeepEye is unavailable** (agent fails to load, model offline), treat it as a blocker rather than degrading to ad-hoc Exa. If the user explicitly accepts the degradation, note it in the research output and in `STACK_REFERENCES.md` so the lower rigor is on the record.

## Related

- `~/.config/opencode/agents/RAG/_shared.md` — agent-level Research hierarchy, source of truth for dispatch policy.
- `WORKFLOW_DESIGN.md` — workflow-DAG decomposition pattern. Distinct from DeepEye; DeepEye does not author workflow plans.
- `RESEARCH_PROTOCOL.md` — how research findings are recorded and referenced in the project.
- `STACK_REFERENCES.md` — project-living reference library, seeded from `~/.config/opencode/agents/RAG/_stack_refs.md`.
