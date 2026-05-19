from __future__ import annotations

import logging
from importlib import import_module

from app.core.config import Settings
from app.workflows.temporal_dispatcher import _validate_temporal_runtime_settings

logger = logging.getLogger(__name__)


class _WorkerSkeleton:
    """Lightweight worker skeleton for testing and registration verification."""

    def __init__(self, *, task_queue: str, workflows: list, activities: list) -> None:
        self._task_queue = task_queue
        self._workflows = workflows
        self._activities = activities


def build_temporal_worker(*, client, task_queue: str, runner) -> _WorkerSkeleton:
    from app.workflows.temporal_workflow import IngestionWorkflow, build_ingestion_activity

    if not task_queue.strip():
        raise RuntimeError("Temporal worker requires a non-empty task_queue.")
    if not hasattr(runner, "run"):
        raise RuntimeError("Temporal worker requires a runner with a run(run_id) method.")

    activity_fn = build_ingestion_activity(runner)

    try:
        worker_module = import_module("temporalio.worker")
        Worker = worker_module.Worker
        return Worker(
            client,
            task_queue=task_queue,
            workflows=[IngestionWorkflow],
            activities=[activity_fn],
        )
    except ImportError:
        logger.info("temporalio not installed; returning worker skeleton for task_queue=%s", task_queue)
        return _WorkerSkeleton(
            task_queue=task_queue,
            workflows=[IngestionWorkflow],
            activities=[activity_fn],
        )


def build_temporal_worker_from_settings(settings: Settings, *, client, runner):
    _validate_temporal_runtime_settings(settings)
    return build_temporal_worker(
        client=client,
        task_queue=settings.temporal_task_queue,
        runner=runner,
    )
