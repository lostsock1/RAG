from __future__ import annotations

import logging
from uuid import UUID

from app.core.config import Settings
from app.workflows.dispatcher import WorkflowDispatcher

logger = logging.getLogger(__name__)


def _validate_temporal_runtime_settings(settings: Settings) -> None:
    if settings.workflow_backend != "temporal":
        raise RuntimeError(
            "Temporal runtime helpers require workflow_backend='temporal'. Switch WORKFLOW_BACKEND to temporal or use the in-process dispatcher."
        )
    if not settings.temporal_host_port:
        raise RuntimeError(
            "workflow_backend=temporal requires temporal_host_port to be configured. "
            "Set TEMPORAL_HOST_PORT or switch WORKFLOW_BACKEND to in_process."
        )
    if not settings.temporal_task_queue.strip():
        raise RuntimeError("workflow_backend=temporal requires a non-empty temporal_task_queue.")
    if not settings.temporal_namespace.strip():
        raise RuntimeError("workflow_backend=temporal requires a non-empty temporal_namespace.")


class TemporalDispatcher:
    """WorkflowDispatcher implementation that submits ingestion runs to Temporal."""

    def __init__(
        self,
        *,
        host_port: str,
        namespace: str,
        task_queue: str,
        client: object | None = None,
    ) -> None:
        if not host_port.strip():
            raise RuntimeError("Temporal dispatcher requires a non-empty host_port.")
        if not namespace.strip():
            raise RuntimeError("Temporal dispatcher requires a non-empty namespace.")
        if not task_queue.strip():
            raise RuntimeError("Temporal dispatcher requires a non-empty task_queue.")

        self._host_port = host_port
        self._namespace = namespace
        self._task_queue = task_queue
        self._client = client

    async def dispatch(self, run_id: UUID) -> None:
        client = self._client
        if client is None:
            client = await self._connect_client()

        from app.workflows.temporal_workflow import IngestionWorkflow

        await client.start_workflow(
            IngestionWorkflow.run,
            id=f"ingestion-run:{run_id}",
            task_queue=self._task_queue,
            args=[str(run_id)],
        )

    async def _connect_client(self):
        try:
            from temporalio.client import Client
        except ImportError as exc:
            raise RuntimeError(
                "Temporal dispatch requires the temporalio package. "
                "Install it with: pip install temporalio"
            ) from exc

        return await Client.connect(
            self._host_port,
            namespace=self._namespace,
        )


def build_temporal_dispatcher(settings: Settings, *, client: object | None = None) -> TemporalDispatcher:
    _validate_temporal_runtime_settings(settings)
    return TemporalDispatcher(
        host_port=settings.temporal_host_port or "",
        namespace=settings.temporal_namespace,
        task_queue=settings.temporal_task_queue,
        client=client,
    )


# Explicit protocol check — fails at class creation time if the
# signature drifts from the WorkflowDispatcher protocol.
def _() -> None:
    def _check(d: WorkflowDispatcher) -> None:
        pass

    _check(TemporalDispatcher(host_port="temporal:7233", namespace="default", task_queue="queue"))
