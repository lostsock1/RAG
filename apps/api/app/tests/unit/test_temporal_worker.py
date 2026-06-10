from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.config import Settings
from app.workflows.temporal_workflow import build_ingestion_activity
from app.workflows.temporal_worker import (
    build_temporal_worker,
    build_temporal_worker_from_settings,
    run_temporal_worker,
)


@pytest.mark.anyio
async def test_ingestion_activity_bridge_calls_pipeline_runner() -> None:
    """The activity bridge produced by build_ingestion_activity calls runner.run()."""
    seen: list = []

    class RunnerSpy:
        def run(self, run_id_arg) -> None:
            seen.append(run_id_arg)

    activity_fn = build_ingestion_activity(RunnerSpy())
    run_id = uuid4()
    await activity_fn(str(run_id))

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


def test_build_temporal_worker_fake_client_with_config_attr_gets_skeleton() -> None:
    """P2-6: real-client detection must use isinstance(temporalio.client.Client),
    not hasattr(client, 'config') — a stub carrying a config attribute is not a
    real Temporal client and must get the skeleton, not a real Worker."""

    class RunnerStub:
        def run(self, run_id) -> None:
            return None

    class FakeClientWithConfig:
        config = {"host": "stub"}

    worker = build_temporal_worker(
        client=FakeClientWithConfig(),
        task_queue="uber-rag-ingestion",
        runner=RunnerStub(),
    )

    assert worker._task_queue == "uber-rag-ingestion"
    assert type(worker).__name__ == "_WorkerSkeleton"


def test_build_temporal_worker_real_client_detection_uses_isinstance(monkeypatch) -> None:
    """P2-6: detection uses isinstance(client, temporalio.client.Client), not
    hasattr(client, 'config'). Fakes the temporalio modules so the logic is
    exercised even where the package is not installed."""

    class RunnerStub:
        def run(self, run_id) -> None:
            return None

    class _RealClient:  # stands in for temporalio.client.Client
        config = {"host": "real"}

    built: dict = {}

    class _FakeWorker:
        def __init__(self, client, *, task_queue, workflows, activities):
            built["client"] = client
            self._task_queue = task_queue
            self._workflows = workflows
            self._activities = activities

    class _FakeWorkerModule:
        Worker = _FakeWorker

    class _FakeClientModule:
        Client = _RealClient

    def fake_import_module(name: str):
        if name == "temporalio.worker":
            return _FakeWorkerModule
        if name == "temporalio.client":
            return _FakeClientModule
        raise AssertionError(f"unexpected import {name}")

    monkeypatch.setattr("app.workflows.temporal_worker.import_module", fake_import_module)

    class FakeClientWithConfig:  # duck-typed impostor: has .config but wrong type
        config = {"host": "stub"}

    impostor_worker = build_temporal_worker(
        client=FakeClientWithConfig(), task_queue="q", runner=RunnerStub()
    )
    assert type(impostor_worker).__name__ == "_WorkerSkeleton"

    real_worker = build_temporal_worker(client=_RealClient(), task_queue="q", runner=RunnerStub())
    assert isinstance(real_worker, _FakeWorker)
    assert built["client"].config == {"host": "real"}


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

@pytest.mark.anyio
async def test_run_temporal_worker_connects_builds_runner_and_runs_worker() -> None:
    seen: dict[str, object] = {}

    class WorkerStub:
        async def run(self) -> None:
            seen["worker_ran"] = True

    async def connect_client(settings: Settings):
        seen["connected_host_port"] = settings.temporal_host_port
        return object()

    def build_runner(settings: Settings):
        seen["runner_parser_backend"] = settings.parser_backend
        return "runner-stub"

    def build_worker(settings: Settings, *, client, runner):
        seen["worker_client"] = client
        seen["worker_runner"] = runner
        seen["worker_task_queue"] = settings.temporal_task_queue
        return WorkerStub()

    await run_temporal_worker(
        Settings(
            workflow_backend="temporal",
            temporal_host_port="127.0.0.1:7233",
            temporal_task_queue="rag-live",
            parser_backend="docling",
            parser_profile="local-cpu",
        ),
        connect_client=connect_client,
        build_runner=build_runner,
        build_worker=build_worker,
    )

    assert seen["connected_host_port"] == "127.0.0.1:7233"
    assert seen["runner_parser_backend"] == "docling"
    assert seen["worker_runner"] == "runner-stub"
    assert seen["worker_task_queue"] == "rag-live"
    assert seen["worker_ran"] is True

