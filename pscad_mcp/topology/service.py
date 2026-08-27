from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import replace
from time import perf_counter_ns
from typing import Any

from ..core.backend.base import BackendError
from .connectivity import build_connectivity
from .diagnostics.generic import diagnose_generic, infer_candidate_edges
from .hashing import topology_sha256
from .models import DiagnosticReport, ProjectTopology
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
        if mode == "infer":
            topology = replace(
                topology,
                candidate_edges=infer_candidate_edges(topology),
            )
        return replace(topology, timings_ms=tuple(sorted(timings.items())))

    async def diagnose(
        self,
        project_name: str,
        canvas_name: str = "Main",
        *,
        ruleset: str = "generic",
        mode: str = "conservative",
    ) -> DiagnosticReport:
        _validate_ruleset(ruleset)
        topology = await self.inspect(
            project_name,
            canvas_name,
            mode=mode,
        )
        started = perf_counter_ns()
        findings = diagnose_generic(topology)
        generic_rules_ms = _elapsed_ms(started)
        counts = Counter(finding.severity for finding in findings)
        valid = not any(
            finding.severity == "error"
            or finding.status in {"conflict", "unresolved"}
            for finding in findings
        )
        timings = dict(topology.timings_ms)
        timings["generic_rules"] = generic_rules_ms
        return DiagnosticReport(
            topology_hash=topology_sha256(topology),
            valid=valid,
            findings=findings,
            summary=tuple(
                (severity, counts.get(severity, 0))
                for severity in ("error", "info", "warning")
            ),
            timings_ms=tuple(sorted(timings.items())),
        )


def _validate_mode(mode: str) -> None:
    if mode not in {"conservative", "infer"}:
        raise BackendError(
            "INVALID_ARGUMENT",
            "Unsupported topology mode.",
            "topology",
            "inspect_project_topology",
            {"mode": mode, "supported_modes": ["conservative", "infer"]},
        )


def _validate_ruleset(ruleset: str) -> None:
    if ruleset != "generic":
        raise BackendError(
            "INVALID_ARGUMENT",
            "Unsupported topology ruleset.",
            "topology",
            "diagnose_project_topology",
            {"ruleset": ruleset, "supported_rulesets": ["generic"]},
        )


def _elapsed_ms(started_ns: int) -> float:
    return (perf_counter_ns() - started_ns) / 1_000_000
