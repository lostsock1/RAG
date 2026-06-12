from __future__ import annotations

import asyncio
import logging
from importlib import import_module
from typing import Any, Callable

from app.core.config import Settings, get_settings
from app.services.contextualizers.factory import build_chunk_contextualizer
from app.services.ocr import build_ocr_service
from app.services.parsers.factory import build_document_parser
from app.services.storage import build_storage_adapter
from app.workflows.pipeline_runner import PipelineRunner
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
        client_module = import_module("temporalio.client")
    except ImportError:
        logger.info("temporalio not installed; returning worker skeleton for task_queue=%s", task_queue)
    else:
        # isinstance, not hasattr(client, "config"): duck-typed stubs must not
        # be handed to a real Worker (P2-6).
        if isinstance(client, client_module.Client):
            return worker_module.Worker(
                client,
                task_queue=task_queue,
                workflows=[IngestionWorkflow],
                activities=[activity_fn],
            )

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


def build_pipeline_runner_from_settings(settings: Settings) -> PipelineRunner:
    parser, parser_backend, parser_profile = build_document_parser(settings)
    return PipelineRunner(
        parser=parser,
        parser_backend=parser_backend,
        parser_profile=parser_profile,
        ocr_service=build_ocr_service(settings),
        storage=build_storage_adapter(settings),
        contextualizer=build_chunk_contextualizer(settings),
    )


async def connect_temporal_client(settings: Settings):
    _validate_temporal_runtime_settings(settings)

    try:
        from temporalio.client import Client
    except ImportError as exc:
        raise RuntimeError(
            "Temporal worker requires the temporalio package. Install it with: pip install temporalio"
        ) from exc

    return await Client.connect(
        settings.temporal_host_port or "",
        namespace=settings.temporal_namespace,
    )


async def temporal_server_is_available(
    *,
    host_port: str,
    namespace: str,
    connect: Callable[..., Any] | None = None,
) -> bool:
    if not host_port.strip() or not namespace.strip():
        return False

    try:
        if connect is None:
            from temporalio.client import Client

            connect = Client.connect
        client = await connect(host_port, namespace=namespace)
    except Exception:
        return False

    return client is not None


async def run_temporal_worker(
    settings: Settings,
    *,
    connect_client: Callable[[Settings], Any] = connect_temporal_client,
    build_runner: Callable[[Settings], PipelineRunner] = build_pipeline_runner_from_settings,
    build_worker: Callable[..., Any] = build_temporal_worker_from_settings,
) -> None:
    client = await connect_client(settings)
    runner = build_runner(settings)
    worker = build_worker(settings, client=client, runner=runner)
    await worker.run()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_temporal_worker(get_settings()))


if __name__ == "__main__":  # pragma: no cover
    main()
