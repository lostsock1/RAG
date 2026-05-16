from __future__ import annotations

from importlib import import_module


async def build_temporal_client(*, host_port: str, namespace: str):
    try:
        client_module = import_module("temporalio.client")
    except ImportError as exc:
        raise RuntimeError(
            "Temporal runtime requires the temporalio package. Install it before enabling the Temporal workflow scaffold."
        ) from exc

    Client = client_module.Client
    return await Client.connect(host_port, namespace=namespace)
