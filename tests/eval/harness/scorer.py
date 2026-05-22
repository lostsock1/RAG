"""Score eval results — per-question and aggregate metrics."""

from __future__ import annotations

from dataclasses import dataclass, field

from tests.eval.harness.loader import EvalQuestion


# ---------------------------------------------------------------------------
# Per-question score types
# ---------------------------------------------------------------------------

@dataclass
class AnsweredScore:
    question_id: str
    status_match: bool
    answer_contains_pass_rate: float  # fraction of answer_contains found
    answer_absent_fail: bool  # True if any answer_absent phrase found
    faithfulness: float  # supported / total sentences


@dataclass
class NegativeScore:
    question_id: str
    compliant: bool  # True if status == "not_enough_evidence"


@dataclass
class AclScore:
    question_id: str
    leak: bool  # True if forbidden content appeared
    leak_detail: str | None = None


@dataclass
class AggregateReport:
    total_questions: int
    faithfulness: float
    negative_answer_compliance: float
    acl_leakage_count: int
    answer_contains_pass_rate: float
    answer_absent_pass_rate: float
    per_question: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def score_answered(
    question: EvalQuestion,
    response: object,
    verification: object,
) -> AnsweredScore:
    """Score an answered question against expected results.

    Parameters
    ----------
    response : object with .answer_text (str) and .status (str)
    verification : object with .sentence_count (int) and .supported_sentence_count (int)
    """
    answer_text = response.answer_text
    answer_lower = answer_text.casefold()

    # status_match
    status_match = question.expected.status == response.status

    # answer_contains_pass_rate
    contains_phrases = question.expected.answer_contains
    if contains_phrases:
        found = sum(1 for phrase in contains_phrases if phrase.casefold() in answer_lower)
        contains_rate = found / len(contains_phrases)
    else:
        contains_rate = 1.0

    # answer_absent_fail
    absent_phrases = question.expected.answer_absent
    absent_fail = any(phrase.casefold() in answer_lower for phrase in absent_phrases)

    # faithfulness
    sentence_count = verification.sentence_count
    supported_count = verification.supported_sentence_count
    faithfulness = supported_count / sentence_count if sentence_count > 0 else 0.0

    return AnsweredScore(
        question_id=question.id,
        status_match=status_match,
        answer_contains_pass_rate=contains_rate,
        answer_absent_fail=absent_fail,
        faithfulness=faithfulness,
    )


def score_negative(question: EvalQuestion, response: object) -> NegativeScore:
    """Score a negative (not-found) question.

    Compliant if the system responded with 'not_enough_evidence'.
    """
    compliant = response.status == "not_enough_evidence"
    return NegativeScore(question_id=question.id, compliant=compliant)


def score_acl(question: EvalQuestion, response: object) -> AclScore:
    """Score an ACL leakage question.

    A leak is detected if the response status is 'answered' when it should be 'denied'.
    """
    # If the expected status is 'denied' but the system answered, that's a leak
    if question.expected.status == "denied" and response.status == "answered":
        return AclScore(
            question_id=question.id,
            leak=True,
            leak_detail=f"Expected 'denied' but got 'answered' with content: {response.answer_text[:200]}",
        )

    # Also check if the answer contains obviously leaked content
    # (placeholder for more sophisticated detection)
    leak = False
    detail = None
    if question.expected.status in ("denied", "partial") and response.status == "answered":
        leak = True
        detail = f"Response contained content that should be denied: {response.answer_text[:200]}"

    return AclScore(question_id=question.id, leak=leak, leak_detail=detail)


def aggregate(scores: list[AnsweredScore | NegativeScore | AclScore]) -> AggregateReport:
    """Compute aggregate metrics from per-question scores."""
    if not scores:
        return AggregateReport(
            total_questions=0,
            faithfulness=0.0,
            negative_answer_compliance=0.0,
            acl_leakage_count=0,
            answer_contains_pass_rate=0.0,
            answer_absent_pass_rate=0.0,
        )

    answered: list[AnsweredScore] = []
    negatives: list[NegativeScore] = []
    acls: list[AclScore] = []

    for s in scores:
        if isinstance(s, AnsweredScore):
            answered.append(s)
        elif isinstance(s, NegativeScore):
            negatives.append(s)
        elif isinstance(s, AclScore):
            acls.append(s)

    faithfulness = (
        sum(s.faithfulness for s in answered) / len(answered) if answered else 0.0
    )
    negative_compliance = (
        sum(1 for s in negatives if s.compliant) / len(negatives) if negatives else 0.0
    )
    acl_leakage_count = sum(1 for s in acls if s.leak)
    contains_rate = (
        sum(s.answer_contains_pass_rate for s in answered) / len(answered) if answered else 0.0
    )
    absent_pass_rate = (
        sum(1 for s in answered if not s.answer_absent_fail) / len(answered) if answered else 0.0
    )

    per_question = []
    for s in scores:
        entry: dict = {"question_id": s.question_id}
        if isinstance(s, AnsweredScore):
            entry.update({
                "type": "answered",
                "status_match": s.status_match,
                "answer_contains_pass_rate": s.answer_contains_pass_rate,
                "answer_absent_fail": s.answer_absent_fail,
                "faithfulness": s.faithfulness,
            })
        elif isinstance(s, NegativeScore):
            entry.update({"type": "negative", "compliant": s.compliant})
        elif isinstance(s, AclScore):
            entry.update({"type": "acl", "leak": s.leak})
            if s.leak_detail:
                entry["leak_detail"] = s.leak_detail
        per_question.append(entry)

    return AggregateReport(
        total_questions=len(scores),
        faithfulness=faithfulness,
        negative_answer_compliance=negative_compliance,
        acl_leakage_count=acl_leakage_count,
        answer_contains_pass_rate=contains_rate,
        answer_absent_pass_rate=absent_pass_rate,
        per_question=per_question,
    )
