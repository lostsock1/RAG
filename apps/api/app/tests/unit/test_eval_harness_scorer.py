"""Tests for tests.eval.harness.scorer — scoring logic."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tests.eval.harness.loader import EvalQuestion, ExpectedResult
from tests.eval.harness.scorer import (
    AggregateReport,
    AnsweredScore,
    AclScore,
    NegativeScore,
    aggregate,
    score_acl,
    score_answered,
    score_negative,
)


# ---------------------------------------------------------------------------
# Stubs — lightweight stand-ins for ChatResponse / VerificationSummary
# ---------------------------------------------------------------------------

@dataclass
class _FakeResponse:
    answer_text: str
    status: str


@dataclass
class _FakeVerification:
    sentence_count: int
    supported_sentence_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_question(
    qtype: str = "definition",
    status: str = "answered",
    answer_contains: list[str] | None = None,
    answer_absent: list[str] | None = None,
) -> EvalQuestion:
    return EvalQuestion(
        id="q01",
        type=qtype,
        category="textbook",
        language="en",
        query="What is entropy?",
        expected=ExpectedResult(
            status=status,
            answer_contains=answer_contains or [],
            answer_absent=answer_absent or [],
        ),
    )


# ---------------------------------------------------------------------------
# score_answered
# ---------------------------------------------------------------------------

class TestScoreAnswered:
    def test_matching_status_all_contains_found(self):
        q = _make_question(
            status="answered",
            answer_contains=["entropy", "isolated system"],
        )
        resp = _FakeResponse(answer_text="Entropy in an isolated system never decreases.", status="answered")
        verif = _FakeVerification(sentence_count=1, supported_sentence_count=1)

        score = score_answered(q, resp, verif)

        assert isinstance(score, AnsweredScore)
        assert score.status_match is True
        assert score.answer_contains_pass_rate == 1.0
        assert score.answer_absent_fail is False
        assert score.faithfulness == 1.0

    def test_non_matching_status(self):
        q = _make_question(status="answered")
        resp = _FakeResponse(answer_text="I don't know.", status="not_enough_evidence")
        verif = _FakeVerification(sentence_count=1, supported_sentence_count=0)

        score = score_answered(q, resp, verif)

        assert score.status_match is False

    def test_partial_contains_phrases(self):
        q = _make_question(
            answer_contains=["entropy", "isolated system", "thermodynamics"],
        )
        resp = _FakeResponse(answer_text="Entropy is a concept in physics.", status="answered")
        verif = _FakeVerification(sentence_count=1, supported_sentence_count=1)

        score = score_answered(q, resp, verif)

        # Only "entropy" found -> 1/3
        assert score.answer_contains_pass_rate == pytest.approx(1 / 3)

    def test_absent_phrases_found_means_hallucination(self):
        q = _make_question(
            answer_contains=["entropy"],
            answer_absent=["always increases"],
        )
        resp = _FakeResponse(
            answer_text="Entropy always increases in all systems.",
            status="answered",
        )
        verif = _FakeVerification(sentence_count=1, supported_sentence_count=1)

        score = score_answered(q, resp, verif)

        assert score.answer_absent_fail is True

    def test_faithfulness_zero_when_no_sentences(self):
        q = _make_question()
        resp = _FakeResponse(answer_text="", status="answered")
        verif = _FakeVerification(sentence_count=0, supported_sentence_count=0)

        score = score_answered(q, resp, verif)

        assert score.faithfulness == 0.0

    def test_faithfulness_fractional(self):
        q = _make_question()
        resp = _FakeResponse(answer_text="Some answer.", status="answered")
        verif = _FakeVerification(sentence_count=4, supported_sentence_count=3)

        score = score_answered(q, resp, verif)

        assert score.faithfulness == pytest.approx(0.75)

    def test_empty_contains_list_gives_pass_rate_one(self):
        """If no answer_contains phrases are expected, pass rate is 1.0."""
        q = _make_question(answer_contains=[])
        resp = _FakeResponse(answer_text="Anything.", status="answered")
        verif = _FakeVerification(sentence_count=1, supported_sentence_count=1)

        score = score_answered(q, resp, verif)

        assert score.answer_contains_pass_rate == 1.0


# ---------------------------------------------------------------------------
# score_negative
# ---------------------------------------------------------------------------

class TestScoreNegative:
    def test_compliant_response(self):
        q = _make_question(qtype="negative", status="not_found")
        resp = _FakeResponse(answer_text="I could not find evidence.", status="not_enough_evidence")

        score = score_negative(q, resp)

        assert isinstance(score, NegativeScore)
        assert score.compliant is True

    def test_non_compliant_response(self):
        q = _make_question(qtype="negative", status="not_found")
        resp = _FakeResponse(answer_text="The answer is 42.", status="answered")

        score = score_negative(q, resp)

        assert score.compliant is False


# ---------------------------------------------------------------------------
# score_acl
# ---------------------------------------------------------------------------

class TestScoreAcl:
    def test_no_leak(self):
        q = _make_question(qtype="acl_leakage", status="denied")
        resp = _FakeResponse(answer_text="Access denied.", status="not_enough_evidence")

        score = score_acl(q, resp)

        assert isinstance(score, AclScore)
        assert score.leak is False

    def test_leak_detected(self):
        q = _make_question(qtype="acl_leakage", status="denied")
        resp = _FakeResponse(
            answer_text="The confidential restructuring plan timeline is Q3.",
            status="answered",
        )

        score = score_acl(q, resp)

        assert score.leak is True


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------

class TestAggregate:
    def test_mixed_scores(self):
        scores = [
            AnsweredScore(
                question_id="q01",
                status_match=True,
                answer_contains_pass_rate=1.0,
                answer_absent_fail=False,
                faithfulness=0.9,
            ),
            AnsweredScore(
                question_id="q02",
                status_match=True,
                answer_contains_pass_rate=0.5,
                answer_absent_fail=False,
                faithfulness=0.8,
            ),
            NegativeScore(question_id="q03", compliant=True),
            NegativeScore(question_id="q04", compliant=False),
            AclScore(question_id="q05", leak=False),
            AclScore(question_id="q06", leak=True, leak_detail="forbidden content"),
        ]

        report = aggregate(scores)

        assert isinstance(report, AggregateReport)
        assert report.total_questions == 6
        assert report.faithfulness == pytest.approx(0.85)  # (0.9 + 0.8) / 2
        assert report.negative_answer_compliance == pytest.approx(0.5)  # 1/2
        assert report.acl_leakage_count == 1
        assert report.answer_contains_pass_rate == pytest.approx(0.75)  # (1.0 + 0.5) / 2
        assert report.answer_absent_pass_rate == pytest.approx(1.0)  # both passed
        assert len(report.per_question) == 6

    def test_empty_scores(self):
        report = aggregate([])

        assert report.total_questions == 0
        assert report.faithfulness == 0.0
        assert report.negative_answer_compliance == 0.0
        assert report.acl_leakage_count == 0
        assert report.answer_contains_pass_rate == 0.0
        assert report.answer_absent_pass_rate == 0.0
        assert report.per_question == []
