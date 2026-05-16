# Evaluation Harness

## Purpose

Continuously measure whether Uber-RAG retrieves, cites, answers, and refuses correctly. Every PR touching retrieval, generation, or ACL must pass the regression suite.

## Repository structure

```text
tests/
  eval/
    datasets/           # Held-out question sets
      heldout-v1.yaml   # 160-question Phase 0 seed set
      needles.yaml      # Synthetic needle tests
      acl-leakage.yaml  # Group-separation tests
      negative.yaml     # Negative-answer tests
      regression.yaml   # Bug-regression tests (populated over time)
    harness/
      __init__.py
      runner.py          # Orchestrates eval runs
      metrics.py         # Computes faithfulness, citation accuracy, etc.
      judges.py          # Deterministic + LLM-assisted judges
      reporter.py        # Produces JSON/Markdown reports
    fixtures/
      sample_corpus/     # Small synthetic corpus for harness CI smoke tests
```

## Ground-truth question format

Each dataset is a YAML file. Every question has:

```yaml
# heldout-v1.yaml (excerpt)
dataset:
  name: "Heldout v1"
  version: "1.0.0"
  description: "160-question seed set for Phase 0–4 regression"
  created: "2026-05-14"
  language_distribution:
    en: 100
    de: 30
    pt: 30

questions:
  - id: "h01"
    type: definition          # definition | exact_lookup | formula | table | multi_hop
                              # | comparison | chapter_synthesis | negative | acl_leakage
                              # | multilingual | needle | ocr_noise | deleted_document
    category: textbook        # textbook | loose_document | cross_corpus
    language: en
    query: "Define the second law of thermodynamics as stated in the textbook."
    expected:
      status: answered        # answered | partial | not_found | denied
      answer_contains:        # key phrases that must appear in a correct answer
        - "entropy"
        - "isolated system"
        - "never decreases"
      answer_absent:          # phrases that must NOT appear (hallucination checks)
        - "increases in all processes"  # wrong — only in isolated systems
      chunk_ids:              # UUIDs of ground-truth source chunks (populated after corpus indexed)
        - null                 # placeholder until corpus exists
      page_range: [42, 44]   # Expected page range in the textbook
      heading_path: ["Chapter 3", "Section 3.1", "The Second Law"]
      source_type: book
    retrieval:
      expected_recall_k: 3    # At least 1 of the ground-truth chunks should appear in top-k
    acl:
      user_context: default   # default | group_a | group_b | admin | unauthenticated

  - id: "h02"
    type: exact_lookup
    category: textbook
    language: en
    query: "What is the value of the gravitational constant G on page 87?"
    expected:
      status: answered
      answer_contains:
        - "6.674"
        - "10^-11"
      page_range: [87, 87]
      heading_path: ["Chapter 2", "Newton's Law of Gravitation"]
    retrieval:
      expected_recall_k: 1
```

### Field reference

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique within dataset. Prefix by category: `h` (heldout), `n` (needle), `a` (acl), `neg` (negative), `r` (regression) |
| `type` | Yes | Question type — drives which retrieval route is expected |
| `category` | Yes | `textbook`, `loose_document`, or `cross_corpus` |
| `language` | Yes | ISO 639-1 |
| `query` | Yes | The user-facing question string |
| `expected.status` | Yes | `answered`, `partial`, `not_found`, `denied` |
| `expected.answer_contains` | No | Key phrases for LLM-judge or substring check |
| `expected.answer_absent` | No | Anti-patterns (hallucination traps) |
| `expected.chunk_ids` | No | Ground-truth source chunks (populated post-indexing) |
| `expected.page_range` | No | For deterministic page-range checks |
| `expected.heading_path` | No | Expected section hierarchy |
| `retrieval.expected_recall_k` | No | Min expected recall at top-k |
| `acl.user_context` | No | Which test user context to use |

## Scoring stubs

Each eval run produces per-question results. Metrics are computed across the run.

### Per-question verdicts

```python
@dataclass
class QuestionVerdict:
    question_id: str
    status: str                     # answered | partial | not_found | denied | error

    # Retrieval
    retrieved_chunk_ids: list[str]
    recall_at_k: float              # 0.0–1.0 (fraction of expected chunks found)
    recall_pass: bool               # recall_at_k >= min(expected expected_recall_k across questions)

    # Answer
    generated_answer: str
    status_match: bool              # expected.status == actual.status
    answer_contains_match: float    # 0.0–1.0 (fraction of answer_contains found)
    answer_absent_fail: bool        # True if any answer_absent phrase found (hallucination)

    # Citations
    citation_ids: list[str]
    citation_accuracy: float        # fraction of citations that actually support their claim
    hallucinated_citation: bool     # citation ID doesn't resolve to a real chunk

    # ACL
    acl_leak: bool                  # forbidden chunk appeared in results
    acl_leak_detail: str | None     # description of the leak

    # Performance
    latency_ms: int
    tokens_generated: int
```

### Aggregate metrics

```python
@dataclass
class EvalReport:
    run_id: str
    dataset: str
    model: str
    timestamp: str

    # Core quality
    faithfulness: float             # 0.0–1.0 — answer_contains_match averaged
    citation_accuracy: float        # 0.0–1.0
    status_accuracy: float          # 0.0–1.0 — status_match rate
    negative_compliance: float      # 0.0–1.0 — correct "not_found" rate on negative questions

    # Retrieval
    recall_at_5: float
    recall_at_10: float
    recall_at_20: float
    mrr: float                      # Mean Reciprocal Rank

    # Hallucination
    hallucination_rate: float       # fraction of questions with answer_absent_fail
    hallucinated_citation_rate: float

    # ACL
    acl_leak_count: int
    acl_leak_rate: float

    # Performance
    p50_latency_ms: int
    p95_latency_ms: int
    p99_latency_ms: int

    # Segmented (by category, language, type)
    segments: dict[str, "EvalReport"]  # e.g., {"textbook": ..., "de": ..., "formula": ...}
```

## Runner design (pseudocode)

```python
class EvalRunner:
    """Orchestrates an evaluation run against the API."""

    def __init__(self, api_client: APIClient, dataset_path: Path, config: EvalConfig):
        self.api = api_client
        self.dataset = load_dataset(dataset_path)
        self.config = config

    async def run(self) -> EvalReport:
        results = []
        for question in self.dataset.questions:
            verdict = await self.evaluate_one(question)
            results.append(verdict)
        return compute_metrics(results, self.dataset)

    async def evaluate_one(self, q: Question) -> QuestionVerdict:
        # 1. Search
        search_resp = await self.api.search(query=q.query, ...)

        # 2. Chat (generate answer)
        chat_resp = await self.api.chat(query=q.query, ...)

        # 3. Verify answer against sources
        verify_resp = await self.api.verify_answer(
            answer=chat_resp.answer,
            source_chunks=search_resp.results
        )

        # 4. Judge against expected
        return judge(question=q, search=search_resp, chat=chat_resp, verify=verify_resp)
```

## Judge rules

Deterministic checks run first (no LLM cost). LLM-assisted checks only for subjective dimensions.

### Deterministic (always run)

| Check | How |
|-------|-----|
| Status match | `actual.status == expected.status` |
| Recall | `len(set(retrieved_chunk_ids) & set(expected.chunk_ids)) / len(expected.chunk_ids)` |
| Citation resolution | Every `citation.chunk_id` resolves to a real chunk in the DB |
| ACL leak | No chunk from a `denied` document appears in `search_resp.results` or `chat_resp.citations` |
| Page range | `expected.page_range` overlaps with `retrieved.page_range` (when specified) |
| Answer contains | Substring or regex match for each `expected.answer_contains` phrase |
| Answer absent | Substring match for each `expected.answer_absent` phrase |

### LLM-assisted (run when deterministic check is ambiguous)

| Check | How |
|-------|-----|
| Faithfulness (semantic) | LLM judge: "Is this sentence supported by the provided sources?" (Hermes 4 for structured output) |
| Answer quality (subjective) | LLM judge: "Does the answer address the question?" Only run if deterministic checks pass |

## CI integration

```yaml
# .github/workflows/eval.yml (sketch)
name: Eval Regression
on:
  pull_request:
    paths:
      - 'services/retrieval/**'
      - 'services/generation/**'
      - 'services/verifier/**'
      - 'apps/api/**'
jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run regression suite
        run: python -m tests.eval.harness.runner --dataset heldout-v1 --fast
        env:
          LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
      - name: Check thresholds
        run: python -m tests.eval.harness.check_thresholds --report eval-results/latest.json
```

## Thresholds (Phase 4 exit criteria, per ROADMAP)

| Metric | Threshold | Consequence if failed |
|--------|-----------|----------------------|
| Faithfulness | ≥ 0.85 | PR blocked |
| Citation accuracy | ≥ 0.90 | PR blocked |
| Negative compliance | ≥ 0.90 | PR blocked |
| ACL leak count | = 0 | **PR blocked (release-blocking)** |
| Hallucination rate | ≤ 0.05 | PR warned; blocked if > 0.10 |
| P50 latency | ≤ 500 ms | PR warned; blocked if > 2000 ms |

Thresholds are configurable per dataset in `datasets/*.yaml` under `thresholds:`. The CI runner reads them dynamically.

## Smoke test (runs on every commit)

A minimal smoke test (5 questions from the heldout set, no LLM calls, deterministic checks only) runs on every `push`. This catches: API contract breaks, schema drift, import errors, ACL filter construction bugs. Full eval (160 questions + LLM) runs on PRs touching retrieval/generation/ACL paths only.
