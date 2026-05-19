from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.config import Settings
from app.workflows.temporal_workflow import build_ingestion_activity
from app.workflows.temporal_worker import build_temporal_worker, build_temporal_worker_from_settings


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

    class RunnerStub:
        def run(self, run_id) -> None:
            return None

    worker = build_temporal_worker(
        client=object(),
        task_queue="uber-rag-ingestion",
        runner=RunnerStub(),
    )

    assert worker is not None
    assert worker._task_queue == "uber-rag-ingestion"


def test_build_temporal_worker_from_settings_rejects_missing_host_port() -> None:
    with pytest.raises(RuntimeError) as exc_info:
        build_temporal_worker_from_settings(
            Settings(
                workflow_backend="temporal",
                temporal_host_port=None,
            ),
            client=object(),
            runner=object(),
        )

    assert "temporal_host_port" in str(exc_info.value)


def test_build_temporal_worker_from_settings_builds_worker_without_connecting() -> None:

    class RunnerStub:
        def run(self, run_id) -> None:
            return None

    worker = build_temporal_worker_from_settings(
        Settings(
            workflow_backend="temporal",
            temporal_host_port="temporal.internal:7233",
            temporal_task_queue="rag-workers",
        ),
        client=object(),
        runner=RunnerStub(),
    )

    assert worker._task_queue == "rag-workers"
    assert len(worker._workflows) == 1
    assert len(worker._activities) == 1
