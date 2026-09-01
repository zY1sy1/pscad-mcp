"""Fail-closed capability checks for fixed LCC disturbance bindings."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from ....core.backend.base import BackendError

PASS = "PASS"
INCOMPLETE = "INCOMPLETE_ANALYSIS"
_EVENT_KEYS = {"kind", "target_bus", "time_s", "duration_s", "phase_mask"}
_EVENT_KINDS = {"inverter_ac_disturbance"}
_TIMER_DEFINITIONS = {"master:tfault", "master:tfaultn"}
_SHUNT_DEFINITIONS = {"master:tpflt"}


def _invalid(field: str, message: str, **details: Any) -> BackendError:
    return BackendError(
        "LCC_DYNAMIC_EVENT_INVALID",
        message,
        "hvdc",
        "validate_fixed_lcc_fault_event",
        {"field": field, **details},
    )


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(field, f"{field} must be non-empty text.")
    return value.strip()


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(field, f"{field} must be finite.")
    number = float(value)
    if not math.isfinite(number):
        raise _invalid(field, f"{field} must be finite.")
    return number


@dataclass(frozen=True)
class FixedLccFaultEvent:
    kind: str
    target_bus: str
    time_s: float
    duration_s: float
    phase_mask: tuple[int, int, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_fixed_lcc_fault_event(
    event: Mapping[str, Any] | FixedLccFaultEvent,
) -> dict[str, Any]:
    """Normalize one explicitly timed inverter AC disturbance event."""

    if isinstance(event, FixedLccFaultEvent):
        normalized = event
    else:
        if not isinstance(event, Mapping) or set(event) != _EVENT_KEYS:
            raise _invalid("event", "Fault event fields are not exact.")
        raw_mask = event["phase_mask"]
        if not isinstance(raw_mask, Sequence) or isinstance(raw_mask, (str, bytes, bytearray)):
            raise _invalid("event.phase_mask", "phase_mask must contain three binary values.")
        if len(raw_mask) != 3 or any(type(value) is not int or value not in {0, 1} for value in raw_mask):
            raise _invalid("event.phase_mask", "phase_mask must contain three binary values.")
        normalized = FixedLccFaultEvent(
            kind=_text(event["kind"], "event.kind"),
            target_bus=_text(event["target_bus"], "event.target_bus"),
            time_s=_finite(event["time_s"], "event.time_s"),
            duration_s=_finite(event["duration_s"], "event.duration_s"),
            phase_mask=tuple(raw_mask),
        )
    if normalized.kind not in _EVENT_KINDS:
        raise _invalid("event.kind", "Unsupported fixed LCC fault event kind.")
    if normalized.target_bus != "inverter_ac_bus":
        raise _invalid("event.target_bus", "Fixed LCC disturbance must target inverter_ac_bus.")
    if normalized.time_s < 0 or normalized.duration_s <= 0:
        raise _invalid("event", "Event time must be non-negative and duration positive.")
    if len(normalized.phase_mask) != 3 or not any(normalized.phase_mask):
        raise _invalid("event.phase_mask", "At least one phase must be faulted.")
    if any(type(value) is not int or value not in {0, 1} for value in normalized.phase_mask):
        raise _invalid("event.phase_mask", "phase_mask must contain three binary values.")
    return normalized.to_dict()


def _records(value: Any, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _definition_inventory(inventory: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for record in _records(inventory.get("definitions", ()), "inventory.definitions"):
        name = record.get("scoped_name", record.get("definition", record.get("name")))
        if isinstance(name, str):
            result[name] = record
    return result


def _ports(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return _records(record.get("ports", ()), "definition.ports")


def _has_port(record: Mapping[str, Any], name: str, *, kind: str, dimension: int | None = None, direction: str | None = None) -> bool:
    for port in _ports(record):
        if port.get("name") != name or port.get("kind") != kind:
            continue
        if dimension is not None and port.get("dimension") != dimension:
            continue
        if direction is not None and port.get("direction") != direction:
            continue
        return True
    return False


def inspect_fixed_lcc_fault_capability(
    blueprint: Mapping[str, Any],
    catalog: Mapping[str, Any],
    inventory: Mapping[str, Any],
) -> dict[str, Any]:
    """Inspect a blueprint for a complete fixed LCC fault/event binding."""

    if not isinstance(blueprint, Mapping) or not isinstance(catalog, Mapping) or not isinstance(inventory, Mapping):
        raise _invalid("inputs", "blueprint, catalog, and inventory must be objects.")
    components = {
        str(item.get("logical_id")): item
        for item in _records(blueprint.get("components", ()), "blueprint.components")
        if isinstance(item.get("logical_id"), str)
    }
    nets = _records(blueprint.get("nets", ()), "blueprint.nets")
    outputs = _records(blueprint.get("outputs", ()), "blueprint.outputs")
    definitions = _definition_inventory(inventory)
    reasons: list[str] = []
    timers = [
        (logical_id, component)
        for logical_id, component in components.items()
        if component.get("definition") in _TIMER_DEFINITIONS
    ]
    shunts = [
        (logical_id, component)
        for logical_id, component in components.items()
        if component.get("definition") in _SHUNT_DEFINITIONS
    ]
    events = _records(blueprint.get("dynamic_events", ()), "blueprint.dynamic_events")
    fault_outputs = [
        output
        for output in outputs
        if output.get("role") == "fault_active" or output.get("path") == "Fault/LCC Fault Active"
    ]
    if len(timers) != 1:
        reasons.append("fault_timer_missing" if not timers else "fault_timer_ambiguous")
    if len(shunts) != 1:
        reasons.append("fault_shunt_missing" if not shunts else "fault_shunt_ambiguous")
    if len(events) != 1:
        reasons.append("fault_event_missing" if not events else "fault_event_ambiguous")
    if len(fault_outputs) != 1:
        reasons.append("fault_channel_missing" if not fault_outputs else "fault_channel_ambiguous")
    if reasons:
        return {"status": INCOMPLETE, "reasons": reasons, "bindings": {}}

    try:
        event = validate_fixed_lcc_fault_event(
            {key: events[0][key] for key in _EVENT_KEYS}
        )
    except BackendError as error:
        return {"status": INCOMPLETE, "reasons": ["fault_event_invalid"], "error": error.to_dict(), "bindings": {}}
    timer_id, timer = timers[0]
    shunt_id, shunt = shunts[0]
    timer_definition = definitions.get(str(timer.get("definition")), {})
    shunt_definition = definitions.get(str(shunt.get("definition")), {})
    if not _has_port(timer_definition, "Y", kind="data", direction="output"):
        reasons.append("fault_timer_port_missing")
    if not _has_port(shunt_definition, "N", kind="electrical", dimension=3):
        reasons.append("fault_shunt_phase_port_missing")
    if not _has_port(shunt_definition, "IS", kind="data", direction="input"):
        reasons.append("fault_shunt_trigger_port_missing")
    net_ids = {str(net.get("logical_id")) for net in nets}
    if event["target_bus"] not in net_ids:
        reasons.append("fault_bus_missing")
    trigger_connected = any(
        {
            f"{timer_id}:Y",
            f"{shunt_id}:IS",
        }
        <= {
            f"{endpoint.get('component')}:{endpoint.get('port')}"
            for endpoint in _records(net.get("endpoints", ()), "net.endpoints")
        }
        for net in nets
    )
    if not trigger_connected:
        reasons.append("fault_trigger_unconnected")
    bus_connected = any(
        event["target_bus"] == net.get("logical_id")
        and any(endpoint.get("component") == shunt_id and endpoint.get("port") == "N" for endpoint in _records(net.get("endpoints", ()), "net.endpoints"))
        for net in nets
    )
    if not bus_connected:
        reasons.append("fault_shunt_unconnected")
    if reasons:
        return {"status": INCOMPLETE, "reasons": reasons, "bindings": {}}
    return {
        "status": PASS,
        "reasons": [],
        "bindings": {
            "event": event,
            "timer_component": timer_id,
            "shunt_component": shunt_id,
            "channel": fault_outputs[0].get("path"),
        },
    }


__all__ = [
    "FixedLccFaultEvent",
    "INCOMPLETE",
    "PASS",
    "inspect_fixed_lcc_fault_capability",
    "validate_fixed_lcc_fault_event",
]
