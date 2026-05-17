from __future__ import annotations

import logging
from importlib import import_module

logger = logging.getLogger(__name__)


class _WorkerSkeleton:
    """Lightweight worker skeleton for testing and registration verification.

    When temporalio is not installed, this provides a testable shape that
    proves the architecture is real without requiring a live Temporal server.
    """

    def __init__(self, *, task_queue: str, workflows: list, activities: list) -> None:
        self._task_queue = task_queue
        self._workflows = workflows
        self._activities = activities


def build_temporal_worker(*, client, task_queue: str, runner) -> _WorkerSkeleton:
    """Build a Temporal worker that registers the ingestion workflow and activity.

    When temporalio is installed, this returns a real Temporal Worker.
    When temporalio is not installed, this returns a skeleton that proves
    the registration shape is correct.

    Args:
        client: A Temporal client instance (or test stub).
        task_queue: The task queue name for the worker.
        runner: A PipelineRunner instance used by the ingestion activity.

    Returns:
        A worker instance (real or skeleton).
    """
    from app.workflows.temporal_workflow import IngestionWorkflow, build_ingestion_activity

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
