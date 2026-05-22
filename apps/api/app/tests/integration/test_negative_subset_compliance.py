"""Integration test: negative-answer subset compliance (empty-corpus sanity check).

Verifies that the negative questions in heldout-v1.yaml all produce
status='not_enough_evidence' when run against a ChatService with an empty
corpus (no indexed content).

This is a sanity check — the primary Phase 4 measurement runs against the
populated eval_stack fixture in tests/eval/test_negative_populated_corpus.py.

Phase 4 exit criterion #2: negative-answer compliance >= 0.90 on populated corpus.
(Empty-corpus stub compliance is expected to be 1.00.)
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.schemas.search import SearchResponse
from tests.eval.harness.loader import load_dataset, filter_questions
from tests.eval.harness.runner import EvalRunner
from tests.eval.harness.scorer import score_negative, aggregate


# Path to the real heldout set
HELDOUT_PATH = "docs/uber-rag/eval/heldout-v1.yaml"


@dataclass
class _StubSearchService:
    """Returns empty search results — simulates an empty corpus."""

    def search(self, *, context, payload) -> SearchResponse:
        return SearchResponse(items=[], total=0)


def _make_eval_chat_service() -> object:
    """Build a ChatService with empty-corpus stubs.

    With no indexed content, search returns 0 hits, and ChatService
    should return not_enough_evidence for every query.
    """
    from app.services.answer_verifier import AnswerVerifier
    from app.services.chat_service import ChatService
    from app.services.citation_resolver import CitationResolver
    from app.services.context_builder import DefaultContextBuilder

    return ChatService(
        search_service=_StubSearchService(),
        context_builder=DefaultContextBuilder(),
        llm_backend=None,  # Won't be called — empty corpus short-circuits
        citation_resolver=CitationResolver(),
        answer_verifier=AnswerVerifier(),
        max_context_characters=4000,
        max_context_blocks=None,
    )


def _make_eval_context() -> object:
    from app.core.request_context import RequestContext

    return RequestContext(
        tenant_id="00000000-0000-0000-0000-000000000000",
        user_id="00000000-0000-0000-0000-000000000001",
        group_ids=["eval-group"],
        roles=["eval"],
        scopes=["documents:read"],
    )


class TestNegativeSubsetComplianceEmptyCorpus:
    """Sanity check: negative questions with empty corpus.

    Every negative question should produce not_enough_evidence when
    there is no indexed content. This is a baseline sanity check,
    not the primary Phase 4 measurement.
    """

    @pytest.fixture(autouse=True)
    def _disable_audit(self, monkeypatch):
        """Disable audit writes — no DB bind in test."""
        monkeypatch.setattr(
            "app.services.chat_service.write_audit_event",
            lambda **kwargs: None,
        )

    @pytest.fixture()
    def negative_questions(self):
        dataset = load_dataset(HELDOUT_PATH)
        return filter_questions(dataset.questions, type="negative")

    @pytest.fixture()
    def chat_service(self):
        return _make_eval_chat_service()

    @pytest.fixture()
    def eval_context(self):
        return _make_eval_context()

    def test_negative_questions_exist(self, negative_questions):
        """Verify the heldout set contains negative questions (20 English + multilingual)."""
        assert len(negative_questions) >= 20, (
            f"Expected at least 20 negative questions, found {len(negative_questions)}"
        )

    def test_all_negative_questions_return_not_enough_evidence(
        self, negative_questions, chat_service, eval_context
    ):
        """Every negative question should produce not_enough_evidence with empty corpus."""
        runner = EvalRunner(
            chat_service=chat_service,
            dataset=load_dataset(HELDOUT_PATH),
            request_context=eval_context,
        )
        results = runner.run(questions=negative_questions)

        scores = [score_negative(q, r.response) for q, r in zip(negative_questions, results)]
        report = aggregate(scores)

        # Every negative question should be compliant with empty corpus
        assert report.negative_answer_compliance == 1.00, (
            f"Expected compliance 1.00 with empty corpus, got {report.negative_answer_compliance:.2f}. "
            f"Failures: {[s.question_id for s in scores if not s.compliant]}"
        )
