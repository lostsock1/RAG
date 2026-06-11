"""Parse heldout-v1.yaml into typed dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ExpectedResult:
    status: str  # "answered" | "not_found" | "denied" | "partial"
    answer_contains: list[str] = field(default_factory=list)
    answer_absent: list[str] = field(default_factory=list)
    chunk_ids: list[str | None] = field(default_factory=list)


@dataclass
class EvidenceSpan:
    """Span-anchored ground truth: a verbatim quote from a fixture document.

    Relevant chunk IDs are resolved at eval time by exact substring match
    against the ingested chunks of ``doc`` (content-anchored — survives
    re-chunking; index-anchored chunk IDs would rot silently)."""

    doc: str   # fixture document slug (file stem, e.g. "physics_textbook_ch3_thermodynamics")
    span: str  # verbatim substring of that document


@dataclass
class RetrievalExpectation:
    expected_recall_k: int | None = None


@dataclass
class AclExpectation:
    user_context: str = "default"


@dataclass
class EvalQuestion:
    id: str
    type: str
    category: str
    language: str
    query: str
    expected: ExpectedResult
    retrieval: RetrievalExpectation = field(default_factory=RetrievalExpectation)
    acl: AclExpectation = field(default_factory=AclExpectation)
    evidence: list[EvidenceSpan] = field(default_factory=list)


@dataclass
class DatasetThresholds:
    faithfulness: float = 0.85
    citation_accuracy: float = 0.90
    negative_compliance: float = 0.90
    acl_leak_count: int = 0
    hallucination_rate: float = 0.05
    p50_latency_ms: int = 500


@dataclass
class EvalDataset:
    name: str
    version: str
    description: str
    thresholds: DatasetThresholds
    questions: list[EvalQuestion]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_STATUSES = {"answered", "partial", "not_found", "denied"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_dataset(path: str | Path) -> EvalDataset:
    """Load and validate an eval dataset from a YAML file."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError("YAML root must be a mapping")

    ds_meta = raw.get("dataset")
    if not isinstance(ds_meta, dict):
        raise ValueError("Missing 'dataset' key in YAML")

    thresholds_raw = ds_meta.get("thresholds", {})
    thresholds = DatasetThresholds(**{k: v for k, v in thresholds_raw.items() if hasattr(DatasetThresholds, k) and v is not None})

    questions_raw = raw.get("questions", [])
    if not isinstance(questions_raw, list):
        raise ValueError("'questions' must be a list")

    questions = [_parse_question(q) for q in questions_raw]

    return EvalDataset(
        name=ds_meta.get("name", ""),
        version=ds_meta.get("version", ""),
        description=ds_meta.get("description", ""),
        thresholds=thresholds,
        questions=questions,
    )


def filter_questions(
    questions: list[EvalQuestion],
    *,
    type: str | None = None,
    category: str | None = None,
    limit: int | None = None,
) -> list[EvalQuestion]:
    """Filter questions by type, category, and/or limit."""
    result = questions
    if type is not None:
        result = [q for q in result if q.type == type]
    if category is not None:
        result = [q for q in result if q.category == category]
    if limit is not None:
        result = result[:limit]
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_question(raw: dict) -> EvalQuestion:
    """Parse and validate a single question dict."""
    # Required fields
    for field_name in ("id", "type", "query"):
        if field_name not in raw or raw[field_name] is None:
            raise ValueError(f"Question is missing required field: {field_name}")

    # Required 'expected' section
    expected_raw = raw.get("expected")
    if expected_raw is None:
        raise ValueError(f"Question '{raw.get('id', '?')}' is missing required 'expected' section")

    if not isinstance(expected_raw, dict):
        raise ValueError(f"Question '{raw.get('id', '?')}' has non-mapping 'expected' section")

    # Required expected.status
    status = expected_raw.get("status")
    if status is None:
        raise ValueError(f"Question '{raw['id']}' is missing required 'expected.status'")
    if status not in _VALID_STATUSES:
        raise ValueError(
            f"Question '{raw['id']}' has invalid status '{status}'. "
            f"Must be one of: {', '.join(sorted(_VALID_STATUSES))}"
        )

    expected = ExpectedResult(
        status=status,
        answer_contains=expected_raw.get("answer_contains", []),
        answer_absent=expected_raw.get("answer_absent", []),
        chunk_ids=expected_raw.get("chunk_ids", []),
    )

    retrieval_raw = raw.get("retrieval", {})
    retrieval = RetrievalExpectation(
        expected_recall_k=retrieval_raw.get("expected_recall_k") if isinstance(retrieval_raw, dict) else None,
    )

    acl_raw = raw.get("acl", {})
    acl = AclExpectation(
        user_context=acl_raw.get("user_context", "default") if isinstance(acl_raw, dict) else "default",
    )

    evidence_raw = raw.get("evidence", [])
    if evidence_raw is None:
        evidence_raw = []
    if not isinstance(evidence_raw, list):
        raise ValueError(f"Question '{raw['id']}' has non-list 'evidence' section")
    evidence: list[EvidenceSpan] = []
    for entry in evidence_raw:
        if not isinstance(entry, dict):
            raise ValueError(f"Question '{raw['id']}' has a non-mapping evidence entry")
        doc = entry.get("doc")
        span = entry.get("span")
        if not doc or not isinstance(doc, str) or not doc.strip():
            raise ValueError(f"Question '{raw['id']}' evidence entry is missing a non-empty 'doc'")
        if not span or not isinstance(span, str) or not span.strip():
            raise ValueError(f"Question '{raw['id']}' evidence entry is missing a non-empty 'span'")
        evidence.append(EvidenceSpan(doc=doc.strip(), span=span))

    return EvalQuestion(
        id=raw["id"],
        type=raw["type"],
        category=raw.get("category", ""),
        language=raw.get("language", "en"),
        query=raw["query"],
        expected=expected,
        retrieval=retrieval,
        acl=acl,
        evidence=evidence,
    )
