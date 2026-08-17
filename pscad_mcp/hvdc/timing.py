"""Strict EMTDC-time event scheduling through the backend contract."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Mapping, Sequence
from typing import Any

from ..core.backend.base import BackendError


def _timing_error(message: str, **details: Any) -> BackendError:
    return BackendError(
        "HVDC_TIMED_CONTROL_UNAVAILABLE",
        message,
        "hvdc",
        "timed_control",
        details,
    )


async def select_timing_mode(backend: Any, project_name: str) -> str:
    capabilities = await backend.get_timed_control_capabilities(project_name)
    if capabilities.get("native_schedule") is True:
        return "native"
    if capabilities.get("simulation_clock") is True:
        return "simulation_clock_polling"
    raise _timing_error(
        "Backend does not provide a strict EMTDC-time control capability.",
        project_name=project_name,
        capabilities=dict(capabilities),
    )


async def dispatch_timed_events(
    backend: Any,
    project_name: str,
    events: Sequence[Mapping[str, Any]],
    *,
    mode: str,
    liveness_deadline_s: float | None = None,
) -> list[dict[str, Any]]:
    normalized = sorted((dict(event) for event in events), key=lambda item: float(item["time_s"]))
    if any(not math.isfinite(float(event["time_s"])) for event in normalized):
        raise _timing_error("Timed event thresholds must be finite.", project_name=project_name)
    if mode == "native":
        acknowledgements = await backend.schedule_timed_controls(project_name, normalized)
        if len(acknowledgements) != len(normalized):
            raise _timing_error(
                "Native scheduler did not acknowledge every event.",
                project_name=project_name,
                expected=len(normalized),
                observed=len(acknowledgements),
            )
        return [
            {
                **dict(ack),
                "requested_time_s": float(event["time_s"]),
                "mode": "native",
            }
            for event, ack in zip(normalized, acknowledgements)
        ]
    if mode != "simulation_clock_polling":
        raise _timing_error("Unknown timed-control mode.", mode=mode)
    pending = list(normalized)
    applied: list[dict[str, Any]] = []
    previous_time: float | None = None
    started = time.monotonic()
    while pending:
        if liveness_deadline_s is not None and time.monotonic() - started > liveness_deadline_s:
            raise _timing_error("Simulation clock polling exceeded its liveness deadline.", project_name=project_name)
        observed = float(await backend.get_simulation_time(project_name))
        if not math.isfinite(observed) or (previous_time is not None and observed < previous_time):
            raise _timing_error("Reported simulation time must be finite and monotonic.", project_name=project_name, observed_time_s=observed)
        previous_time = observed
        while pending and observed >= float(pending[0]["time_s"]):
            event = pending.pop(0)
            component_id = int(event["component_id"])
            await backend.set_component_parameters(project_name, component_id, {str(event["parameter_name"]): event["value"]})
            requested = float(event["time_s"])
            applied.append({
                "requested_time_s": requested,
                "observed_time_s": observed,
                "timing_error_s": observed - requested,
                "mode": mode,
            })
        if pending:
            await asyncio.sleep(0)
    return applied
