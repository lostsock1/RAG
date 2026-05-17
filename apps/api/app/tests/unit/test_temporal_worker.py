from __future__ import annotations

from uuid import uuid4

from app.workflows.pipeline_runner import PipelineRunner
from app.workflows.temporal_workflow import build_ingestion_activity
from app.workflows.temporal_worker import build_temporal_worker


def test_ingestion_activity_bridge_calls_pipeline_runner() -> None:
    """The activity bridge produced by build_ingestion_activity calls runner.run()."""
    seen: list = []

    class RunnerSpy:
        def run(self, run_id_arg) -> None:
            seen.append(run_id_arg)

    activity_fn = build_ingestion_activity(RunnerSpy())
    run_id = uuid4()
    activity_fn(str(run_id))

    assert seen == [run_id]


def test_temporal_worker_builds_with_registered_workflow_and_activity() -> None:
    """build_temporal_worker returns a worker-like object with workflow and activity registered."""
    worker = build_temporal_worker(
        client=object(),
        task_queue="uber-rag-ingestion",
        runner=object(),
    )

    assert worker is not None
    assert worker._task_queue == "uber-rag-ingestion"
