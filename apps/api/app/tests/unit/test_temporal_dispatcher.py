from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.config import Settings
from app.workflows.temporal_dispatcher import TemporalDispatcher, build_temporal_dispatcher


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
async def test_temporal_dispatcher_raises_when_no_client_and_no_temporalio(monkeypatch: pytest.MonkeyPatch) -> None:
    """TemporalDispatcher.dispatch raises clearly when no client is injected and temporalio is not installed."""
    import builtins

    dispatcher = TemporalDispatcher(
        host_port="temporal:7233",
        namespace="default",
        task_queue="uber-rag-ingestion",
    )

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "temporalio.client":
            raise ImportError("temporalio missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="temporalio"):
        await dispatcher.dispatch(uuid4())


def test_build_temporal_dispatcher_rejects_missing_host_port() -> None:
    with pytest.raises(RuntimeError) as exc_info:
        build_temporal_dispatcher(
            Settings(
                workflow_backend="temporal",
                temporal_host_port=None,
            )
        )

    assert "temporal_host_port" in str(exc_info.value)


def test_build_temporal_dispatcher_uses_settings_and_injected_client() -> None:
    client = object()

    dispatcher = build_temporal_dispatcher(
        Settings(
            workflow_backend="temporal",
            temporal_host_port="temporal.internal:7233",
            temporal_namespace="rag-prod",
            temporal_task_queue="rag-q",
        ),
        client=client,
    )

    assert isinstance(dispatcher, TemporalDispatcher)
    assert dispatcher._host_port == "temporal.internal:7233"
    assert dispatcher._namespace == "rag-prod"
    assert dispatcher._task_queue == "rag-q"
    assert dispatcher._client is client


@pytest.mark.anyio
async def test_temporal_dispatcher_caches_connected_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """P2-5: dispatch connects once and reuses the client across calls."""
    connects: list[int] = []

    class ClientStub:
        async def start_workflow(self, workflow, *, id: str, task_queue: str, args: list) -> None:
            return None

    stub = ClientStub()

    async def fake_connect(self):
        connects.append(1)
        return stub

    monkeypatch.setattr(TemporalDispatcher, "_connect_client", fake_connect)

    dispatcher = TemporalDispatcher(
        host_port="temporal:7233", namespace="default", task_queue="uber-rag-ingestion"
    )
    await dispatcher.dispatch(uuid4())
    await dispatcher.dispatch(uuid4())

    assert connects == [1]
    assert dispatcher._client is stub


@pytest.mark.anyio
async def test_temporal_dispatcher_close_closes_and_clears_cached_client() -> None:
    """P2-5: close() releases the cached client and is idempotent."""
    closed: list[int] = []

    class ClientStub:
        async def start_workflow(self, workflow, *, id: str, task_queue: str, args: list) -> None:
            return None

        async def close(self) -> None:
            closed.append(1)

    dispatcher = TemporalDispatcher(
        host_port="temporal:7233",
        namespace="default",
        task_queue="uber-rag-ingestion",
        client=ClientStub(),
    )

    await dispatcher.close()
    assert closed == [1]
    assert dispatcher._client is None

    await dispatcher.close()
    assert closed == [1]


@pytest.mark.anyio
async def test_temporal_dispatcher_close_tolerates_clients_without_close() -> None:
    """P2-5: clients lacking close() (stubs, older SDKs) do not break shutdown."""
    dispatcher = TemporalDispatcher(
        host_port="temporal:7233",
        namespace="default",
        task_queue="uber-rag-ingestion",
        client=object(),
    )
    await dispatcher.close()
    assert dispatcher._client is None
