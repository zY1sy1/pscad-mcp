from __future__ import annotations

from typing import Any

from ...core.backend.base import BackendError
from ..models import TopologySnapshot


class LiveSnapshotProvider:
    def __init__(self, backend: Any) -> None:
        self.backend = backend

    async def capture(
        self,
        project_name: str,
        canvas_name: str,
    ) -> TopologySnapshot:
        for attempt in range(2):
            try:
                return await self.backend.inspect_canvas_topology(
                    project_name,
                    canvas_name,
                )
            except BackendError as error:
                if (
                    error.code != "TOPOLOGY_SNAPSHOT_UNSTABLE"
                    or attempt == 1
                ):
                    raise
        raise AssertionError("unreachable")
