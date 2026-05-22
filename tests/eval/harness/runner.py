"""Eval runner — iterates questions, calls ChatService, collects raw results."""

from __future__ import annotations

import time
from dataclasses import dataclass

from tests.eval.harness.loader import EvalDataset, EvalQuestion


@dataclass
class RunnerResult:
    question_id: str
    question_type: str
    response: object  # ChatResponse
    verification: object | None  # VerificationSummary
    latency_ms: float


class EvalRunner:
    """Run eval questions through a ChatService.

    Parameters
    ----------
    chat_service_factory : callable
        A callable that returns a ChatService instance.
        This enables dependency injection for testing.
    dataset : EvalDataset
        The loaded eval dataset.
    """

    def __init__(self, chat_service_factory, dataset: EvalDataset) -> None:
        self._chat_service_factory = chat_service_factory
        self._dataset = dataset

    def run(
        self,
        questions: list[EvalQuestion] | None = None,
    ) -> list[RunnerResult]:
        """Run questions through the ChatService and collect results.

        Parameters
        ----------
        questions : list[EvalQuestion] or None
            Questions to run. If None, runs all questions in the dataset.

        Returns
        -------
        list[RunnerResult]
            Raw results for each question.
        """
        if questions is None:
            questions = self._dataset.questions

        results: list[RunnerResult] = []
        for question in questions:
            chat_service = self._chat_service_factory()

            start = time.perf_counter()
            response = chat_service.answer(question.query)
            elapsed_ms = (time.perf_counter() - start) * 1000.0

            verification = getattr(response, "verification", None)

            results.append(
                RunnerResult(
                    question_id=question.id,
                    question_type=question.type,
                    response=response,
                    verification=verification,
                    latency_ms=elapsed_ms,
                )
            )

        return results
