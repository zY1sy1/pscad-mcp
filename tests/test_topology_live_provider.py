from unittest.mock import AsyncMock

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.topology.models import TopologySnapshot
from pscad_mcp.topology.providers.live import LiveSnapshotProvider


@pytest.mark.asyncio
async def test_live_provider_retries_one_unstable_capture():
    backend = AsyncMock()
    stable = TopologySnapshot("live", "case", source_fingerprint="a" * 64)
    backend.inspect_canvas_topology.side_effect = [
        BackendError(
            "TOPOLOGY_SNAPSHOT_UNSTABLE",
            "changed",
            "legacy",
            "inspect_canvas_topology",
        ),
        stable,
    ]
    result = await LiveSnapshotProvider(backend).capture("case", "Main")
    assert result is stable
    assert backend.inspect_canvas_topology.await_count == 2


@pytest.mark.asyncio
async def test_live_provider_stops_after_second_unstable_capture():
    backend = AsyncMock()
    backend.inspect_canvas_topology.side_effect = BackendError(
        "TOPOLOGY_SNAPSHOT_UNSTABLE",
        "changed",
        "legacy",
        "inspect_canvas_topology",
    )
    with pytest.raises(BackendError) as raised:
        await LiveSnapshotProvider(backend).capture("case", "Main")
    assert raised.value.code == "TOPOLOGY_SNAPSHOT_UNSTABLE"
    assert backend.inspect_canvas_topology.await_count == 2


@pytest.mark.asyncio
async def test_live_provider_preserves_non_retryable_backend_error():
    backend = AsyncMock()
    error = BackendError(
        "NOT_FOUND",
        "missing",
        "legacy",
        "inspect_canvas_topology",
    )
    backend.inspect_canvas_topology.side_effect = error

    with pytest.raises(BackendError) as raised:
        await LiveSnapshotProvider(backend).capture("case", "Main")

    assert raised.value is error
    assert backend.inspect_canvas_topology.await_count == 1
