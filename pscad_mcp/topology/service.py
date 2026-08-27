from __future__ import annotations

import asyncio
from dataclasses import replace
from time import perf_counter_ns
from typing import Any

from ..core.backend.base import BackendError
from .connectivity import build_connectivity
from .models import ProjectTopology
from .providers.live import LiveSnapshotProvider
from .providers.pscx import PscxSnapshotProvider
from .reconcile import reconcile_snapshots


class TopologyService:
    def __init__(self, backend: Any) -> None:
        self.live_provider = LiveSnapshotProvider(backend)
        self.saved_provider = PscxSnapshotProvider()

    async def inspect(
        self,
        project_name: str,
        canvas_name: str = "Main",
        *,
        mode: str = "conservative",
    ) -> ProjectTopology:
        _validate_mode(mode)
        timings: dict[str, float] = {}

        started = perf_counter_ns()
        live = await self.live_provider.capture(project_name, canvas_name)
        timings["live_capture"] = _elapsed_ms(started)

        started = perf_counter_ns()
        saved = None
        if live.project_path:
            saved = await asyncio.to_thread(
                self.saved_provider.read,
                live.project_path,
                canvas_name,
            )
        timings["file_parse"] = _elapsed_ms(started)

        started = perf_counter_ns()
        topology = reconcile_snapshots(live, saved)
        if saved is None:
            topology = replace(
                topology,
                unresolved=tuple(
                    sorted(
                        set(topology.unresolved)
                        | {"saved_project_path_unavailable"}
                    )
                ),
            )
        timings["reconcile"] = _elapsed_ms(started)

        started = perf_counter_ns()
        topology = build_connectivity(topology).topology
        timings["connectivity"] = _elapsed_ms(started)
        return replace(topology, timings_ms=tuple(sorted(timings.items())))


def _validate_mode(mode: str) -> None:
    if mode not in {"conservative", "infer"}:
        raise BackendError(
            "INVALID_ARGUMENT",
            "Unsupported topology mode.",
            "topology",
            "inspect_project_topology",
            {"mode": mode, "supported_modes": ["conservative", "infer"]},
        )


def _elapsed_ms(started_ns: int) -> float:
    return (perf_counter_ns() - started_ns) / 1_000_000
