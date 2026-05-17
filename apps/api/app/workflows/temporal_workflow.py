from __future__ import annotations

from datetime import timedelta
from importlib import import_module
from uuid import UUID

try:
    workflow = import_module("temporalio.workflow")
    activity = import_module("temporalio.activity")
except ImportError:  # pragma: no cover

    class _Shim:
        @staticmethod
        def defn(fn=None, *, name=None):
            if fn is not None:
                return fn
            # Called with keyword args — return a decorator
            def decorator(f):
                return f
            return decorator

        @staticmethod
        def run(func):
            return func

        @staticmethod
        async def execute_activity(fn, *args, **kwargs):
            # When temporalio is not installed, activities are called directly.
            # Await coroutines so async activities also work under the shim.
            import asyncio
            import inspect

            if callable(fn):
                result = fn(*args)
                if inspect.isawaitable(result):
                    return await result
                return result
            return None

    workflow = _Shim()
    activity = _Shim()


@workflow.defn
class IngestionWorkflow:
    """Temporal workflow that orchestrates ingestion by invoking the shared pipeline runner.

    The workflow stays thin — it delegates all business logic to the
    ``run_ingestion_activity`` which calls ``PipelineRunner.run()``.
    """

    @workflow.run
    async def run(self, run_id: str) -> str:
        await workflow.execute_activity(
            run_ingestion_activity,
            run_id,
            start_to_close_timeout=timedelta(minutes=30),
        )
        return run_id


def build_ingestion_activity(runner):
    """Build a Temporal activity function that bridges to PipelineRunner.run.

    This factory accepts a PipelineRunner instance and returns a callable
    suitable for Temporal worker registration.
    """

    @activity.defn(name="run_ingestion_activity")
    def run_ingestion_activity(run_id: str) -> None:
        runner.run(UUID(run_id))

    return run_ingestion_activity
