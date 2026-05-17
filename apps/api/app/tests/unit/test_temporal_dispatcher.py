from __future__ import annotations

from uuid import uuid4

import pytest

from app.workflows.temporal_dispatcher import TemporalDispatcher


@pytest.mark.anyio
async def test_temporal_dispatcher_submits_ingestion_workflow() -> None:
    """TemporalDispatcher.dispatch starts a workflow with the correct identity and args."""
    submitted: dict = {}

    class ClientStub:
        async def start_workflow(
            self,
            workflow,
            *,
            id: str,
            task_queue: str,
            args: list,
        ) -> None:
            submitted["workflow"] = workflow
            submitted["id"] = id
            submitted["task_queue"] = task_queue
            submitted["args"] = args

    dispatcher = TemporalDispatcher(
        host_port="temporal:7233",
        namespace="default",
        task_queue="uber-rag-ingestion",
        client=ClientStub(),
    )

    run_id = uuid4()
    await dispatcher.dispatch(run_id)

    assert submitted["id"] == f"ingestion-run:{run_id}"
    assert submitted["task_queue"] == "uber-rag-ingestion"
    assert submitted["args"] == [str(run_id)]


@pytest.mark.anyio
async def test_temporal_dispatcher_raises_when_no_client_and_no_temporalio() -> None:
    """TemporalDispatcher.dispatch raises clearly when no client is injected and temporalio is not installed."""
    dispatcher = TemporalDispatcher(
        host_port="temporal:7233",
        namespace="default",
        task_queue="uber-rag-ingestion",
    )

    with pytest.raises(RuntimeError, match="temporalio"):
        await dispatcher.dispatch(uuid4())
