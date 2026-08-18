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
    write_event: Any | None = None,
    poll_interval_s: float = 0.01,
    max_stalled_polls: int = 100,
) -> list[dict[str, Any]]:
    if poll_interval_s <= 0 or not math.isfinite(float(poll_interval_s)):
        raise _timing_error("Polling interval must be a finite positive number.", poll_interval_s=poll_interval_s)
    if max_stalled_polls < 1:
        raise _timing_error("max_stalled_polls must be at least one.", max_stalled_polls=max_stalled_polls)
    normalized = sorted((dict(event) for event in events), key=lambda item: float(item["time_s"]))
    if any(not math.isfinite(float(event["time_s"])) for event in normalized):
        raise _timing_error("Timed event thresholds must be finite.", project_name=project_name)
    event_ids = [str(event["event_id"]) for event in normalized if event.get("event_id") is not None]
    if len(event_ids) != len(set(event_ids)):
        raise _timing_error(
            "Timed events must have unique event IDs.",
            project_name=project_name,
            duplicate_event_ids=sorted({item for item in event_ids if event_ids.count(item) > 1}),
        )
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
                **({"event_id": event["event_id"]} if "event_id" in event else {}),
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
    stalled_polls = 0
    started = time.monotonic()
    while pending:
        if liveness_deadline_s is not None and time.monotonic() - started > liveness_deadline_s:
            raise _timing_error("Simulation clock polling exceeded its liveness deadline.", project_name=project_name)
        observed = float(await backend.get_simulation_time(project_name))
        if not math.isfinite(observed) or (previous_time is not None and observed < previous_time):
            raise _timing_error("Reported simulation time must be finite and monotonic.", project_name=project_name, observed_time_s=observed)
        if previous_time is not None and observed == previous_time:
            stalled_polls += 1
            if stalled_polls >= max_stalled_polls:
                raise _timing_error(
                    "Simulation clock did not advance within the allowed polling window.",
                    project_name=project_name,
                    observed_time_s=observed,
                    stalled_polls=stalled_polls,
                )
        else:
            stalled_polls = 0
        previous_time = observed
        while pending and observed >= float(pending[0]["time_s"]):
            event = pending.pop(0)
            component_id = int(event["component_id"])
            if write_event is None:
                await backend.set_component_parameters(project_name, component_id, {str(event["parameter_name"]): event["value"]})
            else:
                await write_event(event)
            requested = float(event["time_s"])
            applied.append({
                **{key: event[key] for key in ("target", "canonical", "component_id", "parameter_name", "value") if key in event},
                **({"event_id": event["event_id"]} if "event_id" in event else {}),
                "requested_time_s": requested,
                "observed_time_s": observed,
                "timing_error_s": observed - requested,
                "mode": mode,
            })
        if pending:
            await asyncio.sleep(poll_interval_s)
    return applied
