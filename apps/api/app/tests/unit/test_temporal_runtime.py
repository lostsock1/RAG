from __future__ import annotations

import pytest

from app.services.temporal_runtime import build_temporal_client


@pytest.mark.anyio
async def test_build_temporal_client_requires_temporalio_dependency() -> None:
    with pytest.raises(RuntimeError) as exc_info:
        await build_temporal_client(host_port="temporal:7233", namespace="default")

    assert "Temporal runtime requires the temporalio package" in str(exc_info.value)
