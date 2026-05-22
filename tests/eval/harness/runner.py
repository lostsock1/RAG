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
    chat_service : ChatService
        A ChatService instance (or any object with an .answer() method).
        For testing, pass a stub that accepts the same interface.
    dataset : EvalDataset
        The loaded eval dataset.
    request_context : object
        A RequestContext to pass to ChatService.answer().
    """

    def __init__(self, chat_service, dataset: EvalDataset, request_context=None) -> None:
        self._chat_service = chat_service
        self._dataset = dataset
        self._request_context = request_context

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
            start = time.perf_counter()
            response = self._call_chat_service(question)
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

    def _call_chat_service(self, question: EvalQuestion):
        """Call the ChatService with the question.

        Tries the real ChatService interface first (keyword args),
        falls back to a simple callable for stubs.
        """
        import inspect

        sig = inspect.signature(self._chat_service.answer)
        params = list(sig.parameters.keys())

        # Real ChatService.answer(context=, payload=, delivery_mode=)
        if "context" in params and "payload" in params:
            from app.schemas.chat import ChatRequest

            payload = ChatRequest(question=question.query)
            if self._request_context is not None:
                return self._chat_service.answer(
                    context=self._request_context,
                    payload=payload,
                    delivery_mode="eval",
                )
            else:
                return self._chat_service.answer(
                    context=self._make_default_context(),
                    payload=payload,
                    delivery_mode="eval",
                )

        # Simple stub interface: answer(query_string)
        return self._chat_service.answer(question.query)

    @staticmethod
    def _make_default_context():
        """Create a default RequestContext for eval runs."""
        from app.core.request_context import RequestContext

        return RequestContext(
            tenant_id="00000000-0000-0000-0000-000000000000",
            user_id="00000000-0000-0000-0000-000000000001",
            group_ids=["eval-group"],
            roles=["eval"],
            scopes=["documents:read"],
        )
