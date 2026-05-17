from __future__ import annotations

import logging
from uuid import UUID

from app.workflows.dispatcher import WorkflowDispatcher

logger = logging.getLogger(__name__)


class TemporalDispatcher:
    """WorkflowDispatcher implementation that submits ingestion runs to Temporal.

    Accepts an optional pre-built client for testing. When no client is
    provided, it attempts to connect using the temporalio SDK at dispatch time.

    Uses ``start_workflow`` (fire-and-forget) to match the non-blocking
    semantics of the in-process dispatcher. The worker completes the workflow
    asynchronously.
    """

    def __init__(
        self,
        *,
        host_port: str,
        namespace: str,
        task_queue: str,
        client: object | None = None,
    ) -> None:
        self._host_port = host_port
        self._namespace = namespace
        self._task_queue = task_queue
        self._client = client

    async def dispatch(self, run_id: UUID) -> None:
        """Submit an ingestion workflow to Temporal for the given run_id.

        Starts the workflow without waiting for completion, matching the
        fire-and-forget semantics of InProcessDispatcher.
        """
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
        """Connect to Temporal using the temporalio SDK.

        Raises RuntimeError if temporalio is not installed.
        """
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


# Explicit protocol check — fails at class creation time if the
# signature drifts from the WorkflowDispatcher protocol.
def _() -> None:
    def _check(d: WorkflowDispatcher) -> None:
        pass

    _check(TemporalDispatcher(host_port="", namespace="", task_queue=""))
