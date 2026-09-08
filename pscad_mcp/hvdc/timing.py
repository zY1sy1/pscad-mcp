"""Strict EMTDC-time event scheduling through the backend contract."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Mapping, Sequence
from copy import deepcopy
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
    if (
        capabilities.get("time_basis") != "EMTDC"
        or capabilities.get("time_units") != "s"
        or capabilities.get("verified") is not True
    ):
        raise _timing_error("The backend timing provider has no verified EMTDC seconds contract.", capabilities=dict(capabilities))
    if capabilities.get("native_schedule") is True:
        return "native"
    if capabilities.get("simulation_clock") is True:
        return "simulation_clock_polling"
    raise _timing_error(
        "Backend does not provide a strict EMTDC-time control capability.",
        project_name=project_name,
        capabilities=dict(capabilities),
    )


def normalize_timed_events(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate point/interval events before any scheduler or project mutation."""
    result = []
    for index, item in enumerate(events):
        event = deepcopy(dict(item))
        event["event_id"] = str(event.get("event_id") or f"event-{index:06d}")
        for field in ("time_s", "end_time_s", "value", "before_value", "after_value"):
            if field not in event:
                continue
            raw = event[field]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
                raise _timing_error("Event numeric fields must be finite numbers.", event_id=event["event_id"], field=field)
            if field in {"time_s", "end_time_s"}:
                event[field] = float(raw)
        if "time_s" not in event or event["time_s"] < 0:
            raise _timing_error("Event times must be non-negative.", event_id=event["event_id"])
        if "value" not in event:
            raise _timing_error("Each timed event must declare its value.", event_id=event["event_id"])
        if "end_time_s" in event and event["end_time_s"] <= event["time_s"]:
            raise _timing_error("Event intervals must have a positive duration.", event_id=event["event_id"])
        result.append(event)
    result.sort(key=lambda event: (event["time_s"], event["event_id"]))
    identifiers = [event["event_id"] for event in result]
    if len(identifiers) != len(set(identifiers)):
        raise _timing_error("Timed events must have unique event IDs.")
    previous: dict[tuple[str, ...], dict[str, Any]] = {}
    for event in result:
        target = event.get("target")
        if isinstance(target, Mapping):
            key = (str(target.get("instance_path", "Main")), str(target.get("owner", "")), str(target.get("parameter", "")))
        else:
            key = (str(event.get("instance_path", "Main")), str(event.get("component_id", target)), str(event.get("parameter_name", "")))
        if key[1].isdigit():
            key = (key[0], str(int(key[1])), key[2])
        earlier = previous.get(key)
        if earlier and (event["time_s"] < earlier.get("end_time_s", earlier["time_s"]) or event["time_s"] == earlier["time_s"]):
            raise _timing_error("Events conflict on the same target.", events=[earlier["event_id"], event["event_id"]])
        previous[key] = event
    return result


def validate_native_acknowledgements(events: Sequence[Mapping[str, Any]], acknowledgements: Any) -> list[dict[str, Any]]:
    if not isinstance(acknowledgements, (list, tuple)) or len(acknowledgements) != len(events):
        raise _timing_error("Native scheduler did not acknowledge every event.")
    by_id = {str(ack.get("event_id")): dict(ack) for ack in acknowledgements if isinstance(ack, Mapping)}
    if len(by_id) != len(events):
        raise _timing_error("Native acknowledgements must identify each event exactly once.")
    result = []
    for event in events:
        ack = by_id.get(str(event["event_id"]))
        fields = ("event_id", "target", "component_id", "parameter_name", "value", "end_time_s", "before_value", "after_value")
        if ack is None or any(field in event and ack.get(field) != event[field] for field in fields):
            raise _timing_error("Native acknowledgement differs from the scheduled event.", expected=dict(event), observed=ack)
        requested = ack.get("time_s", ack.get("requested_time_s"))
        if requested != event["time_s"]:
            raise _timing_error("Native acknowledgement changed the requested time.", expected=dict(event), observed=ack)
        result.append({**ack, "requested_time_s": float(event["time_s"]), "mode": "native"})
    return result


async def dispatch_timed_events(
    backend: Any,
    project_name: str,
    events: Sequence[Mapping[str, Any]],
    *,
    mode: str,
    liveness_deadline_s: float | None = None,
    write_event: Any | None = None,
    # Keep the default cadence short enough for callers that only yield to the
    # event loop (rather than sleeping for a wall-clock interval) to observe
    # timely writes, while retaining a positive delay to avoid a busy loop.
    poll_interval_s: float = 0.0005,
    max_stalled_polls: int = 100,
) -> list[dict[str, Any]]:
    if poll_interval_s <= 0 or not math.isfinite(float(poll_interval_s)):
        raise _timing_error("Polling interval must be a finite positive number.", poll_interval_s=poll_interval_s)
    if max_stalled_polls < 1:
        raise _timing_error("max_stalled_polls must be at least one.", max_stalled_polls=max_stalled_polls)
    normalized = normalize_timed_events(events)
    for event in normalized:
        target = event.get("target")
        binding = target if isinstance(target, Mapping) else {"owner": event.get("component_id"), "parameter": event.get("parameter_name")}
        if not str(binding.get("owner", "")).isdigit() or not isinstance(binding.get("parameter"), str) or not binding["parameter"].strip():
            raise _timing_error("Every dispatched event requires an exact numeric owner and parameter.", event_id=event["event_id"])
        if isinstance(target, Mapping):
            if ("component_id" in event and str(event["component_id"]) != str(binding["owner"])) or ("parameter_name" in event and event["parameter_name"] != binding["parameter"]):
                raise _timing_error("Flat and nested timed-control targets conflict.", event_id=event["event_id"])
            event.setdefault("component_id", str(binding["owner"]))
            event.setdefault("parameter_name", binding["parameter"])
    if mode == "native":
        if await select_timing_mode(backend, project_name) != "native":
            raise _timing_error("Native registration requires verified native capability.")
        acknowledgements = await backend.schedule_timed_controls(project_name, deepcopy(normalized))
        return validate_native_acknowledgements(normalized, acknowledgements)
    if mode != "simulation_clock_polling":
        raise _timing_error("Unknown timed-control mode.", mode=mode)
    if any("end_time_s" in event for event in normalized):
        raise _timing_error("Clock polling accepts point events only; explicitly schedule both interval edges.")
    if await select_timing_mode(backend, project_name) not in {"native", "simulation_clock_polling"}:
        raise _timing_error("Clock polling requires a verified provider.")
    capabilities = await backend.get_timed_control_capabilities(project_name)
    bound = capabilities.get("max_timing_error_s")
    if isinstance(bound, bool) or not isinstance(bound, (int, float)) or not math.isfinite(bound) or bound < 0 or capabilities.get("simulation_clock") is not True:
        raise _timing_error("Clock polling requires a finite predeclared timing error bound.")
    pending = list(normalized)
    applied: list[dict[str, Any]] = []
    previous_time: float | None = None
    stalled_polls = 0
    started = time.monotonic()
    while pending:
        if liveness_deadline_s is not None and time.monotonic() - started > liveness_deadline_s:
            raise _timing_error("Simulation clock polling exceeded its liveness deadline.", project_name=project_name)
        observed = float(await backend.get_simulation_time(project_name))
        if not math.isfinite(observed) or observed < 0 or (previous_time is not None and observed < previous_time):
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
            requested = float(event["time_s"])
            if observed - requested > bound:
                raise _timing_error("The event timing error exceeded its bound before writing.", requested_time_s=requested, observed_time_s=observed, max_timing_error_s=bound)
            component_id = int(event["component_id"])
            if write_event is None:
                await backend.set_component_parameters(project_name, component_id, {str(event["parameter_name"]): event["value"]})
                readback = await backend.get_component_parameters(project_name, component_id)
                if readback.get(str(event["parameter_name"])) != event["value"]:
                    raise _timing_error("The polled event did not read back correctly.", event_id=event["event_id"])
            else:
                await write_event(event)
            completed = float(await backend.get_simulation_time(project_name))
            if not math.isfinite(completed) or completed < observed or completed - requested > bound:
                raise _timing_error("The event timing error exceeded its bound or the clock regressed during writing.", requested_time_s=requested, observed_time_s=completed, max_timing_error_s=bound)
            observed = completed
            previous_time = completed
            applied.append({
                **{key: event[key] for key in ("target", "canonical", "component_id", "parameter_name", "value") if key in event},
                **({"event_id": event["event_id"]} if "event_id" in event else {}),
                "requested_time_s": requested,
                "observed_time_s": observed,
                "timing_error_s": observed - requested,
                "max_timing_error_s": bound,
                "mode": mode,
            })
        if pending:
            await asyncio.sleep(poll_interval_s)
    return applied
