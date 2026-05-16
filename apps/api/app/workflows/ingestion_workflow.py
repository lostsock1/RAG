from __future__ import annotations

from importlib import import_module

try:
    workflow = import_module("temporalio.workflow")
except ImportError:  # pragma: no cover
    class _WorkflowShim:
        @staticmethod
        def defn(cls):
            return cls

        @staticmethod
        def run(func):
            return func

    workflow = _WorkflowShim()


@workflow.defn
class IngestionWorkflow:
    @workflow.run
    async def run(self, ingestion_run_id: str) -> str:
        return ingestion_run_id
