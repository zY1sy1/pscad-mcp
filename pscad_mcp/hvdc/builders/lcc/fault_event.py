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
    definitions = inventory.get("definitions", ())
    if isinstance(definitions, Mapping):
        for name, record in definitions.items():
            if isinstance(name, str) and isinstance(record, Mapping):
                result[name] = record
        return result
    for record in _records(definitions, "inventory.definitions"):
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
        observed_direction = port.get("direction")
        if direction is not None and observed_direction is not None and observed_direction != direction:
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
    net_endpoint_sets = [
        {
            f"{endpoint.get('component')}:{endpoint.get('port')}"
            for endpoint in _records(net.get("endpoints", ()), "net.endpoints")
        }
        for net in nets
    ]
    outputs = _records(blueprint.get("outputs", ()), "blueprint.outputs")
    measurements = _records(
        blueprint.get("measurements", ()), "blueprint.measurements"
    )
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
        if component.get("role") == "fault_shunt"
        or component.get("definition") in _SHUNT_DEFINITIONS
    ]
    events = _records(blueprint.get("dynamic_events", ()), "blueprint.dynamic_events")
    fault_outputs = [
        output
        for output in outputs
        if output.get("role") == "fault_active" or output.get("path") == "Fault/LCC Fault Active"
    ]
    breaker_group_candidate = len(shunts) == 3 and all(
        component.get("definition") == "master:breaker1"
        for _logical_id, component in shunts
    )
    if len(timers) != 1:
        reasons.append("fault_timer_missing" if not timers else "fault_timer_ambiguous")
    if len(shunts) != 1 and not breaker_group_candidate:
        reasons.append("fault_shunt_missing" if not shunts else "fault_shunt_ambiguous")
    if len(events) != 1:
        reasons.append("fault_event_missing" if not events else "fault_event_ambiguous")
    if len(fault_outputs) != 1:
        reasons.append("fault_channel_missing" if not fault_outputs else "fault_channel_ambiguous")
    if reasons:
        return {"status": INCOMPLETE, "reasons": list(dict.fromkeys(reasons)), "bindings": {}}

    try:
        event = validate_fixed_lcc_fault_event(
            {key: events[0][key] for key in _EVENT_KEYS}
        )
    except BackendError as error:
        return {"status": INCOMPLETE, "reasons": ["fault_event_invalid"], "error": error.to_dict(), "bindings": {}}
    timer_id, timer = timers[0]
    shunt_id, shunt = shunts[0]
    if events[0].get("timer_component") != timer_id:
        reasons.append("fault_timer_reference_mismatch")
    control_components = events[0].get("control_components")
    single_control = events[0].get("control_component")
    if control_components is None and isinstance(single_control, str):
        control_components = [single_control]
    elif control_components is not None and single_control is not None:
        reasons.append("fault_control_components_ambiguous")
    if not isinstance(control_components, Sequence) or isinstance(control_components, (str, bytes, bytearray)) or not control_components or any(not isinstance(item, str) or not item.strip() for item in control_components):
        reasons.append("fault_control_components_missing")
        control_components = []
    elif len(set(control_components)) != len(control_components):
        reasons.append("fault_control_components_ambiguous")
    if not isinstance(events[0].get("control_parameter"), str) or not events[0]["control_parameter"].strip():
        reasons.append("fault_control_parameter_missing")
    if "apply_value" not in events[0] or "clear_value" not in events[0]:
        reasons.append("fault_control_values_missing")
    elif events[0]["apply_value"] == events[0]["clear_value"]:
        reasons.append("fault_control_values_identical")
    elif any(item not in components for item in control_components):
        reasons.append("fault_control_component_missing")
    timer_definition = definitions.get(str(timer.get("definition")), {})
    shunt_definition = definitions.get(str(shunt.get("definition")), {})
    if not _has_port(timer_definition, "Y", kind="data", direction="output"):
        reasons.append("fault_timer_port_missing")
    breaker_group = all(
        component.get("definition") == "master:breaker1"
        for _logical_id, component in shunts
    ) and len(shunts) == 3
    shunt_ids = {logical_id for logical_id, _component in shunts}
    if breaker_group:
        if events[0].get("shunt_component") != "inverter_fault_shunt_group":
            reasons.append("fault_shunt_reference_mismatch")
        if set(control_components) != shunt_ids:
            reasons.append("fault_control_component_missing")
        if events[0].get("channel") != fault_outputs[0].get("path"):
            reasons.append("fault_channel_reference_mismatch")
    elif events[0].get("shunt_component") != shunt_id:
        reasons.append("fault_shunt_reference_mismatch")
    resistors = [
        (logical_id, component)
        for logical_id, component in components.items()
        if component.get("role") == "fault_resistor"
    ]
    if breaker_group:
        for _logical_id, component in shunts:
            definition = definitions.get(str(component.get("definition")), {})
            if not _has_port(definition, "A", kind="electrical", dimension=1) or not _has_port(definition, "B", kind="electrical", dimension=1):
                reasons.append("fault_shunt_phase_port_missing")
        if len(resistors) != 3:
            reasons.append("fault_resistor_group_missing")
        else:
            resistor_ids = {
                logical_id
                for logical_id, component in resistors
                if component.get("definition") == "master:fault_resistor"
            }
            if len(resistor_ids) != 3:
                reasons.append("fault_resistor_definition_missing")
            branch_pairs = {
                (breaker_id, resistor_id)
                for endpoint_keys in net_endpoint_sets
                for breaker_id in shunt_ids
                for resistor_id in resistor_ids
                if {f"{breaker_id}:B", f"{resistor_id}:IN"} <= endpoint_keys
            }
            if (
                len(branch_pairs) != 3
                or {breaker_id for breaker_id, _resistor_id in branch_pairs}
                != shunt_ids
                or {resistor_id for _breaker_id, resistor_id in branch_pairs}
                != resistor_ids
            ):
                reasons.append("fault_resistor_branch_unconnected")
            ground_ids = {
                logical_id
                for logical_id, component in components.items()
                if component.get("definition") == "master:ground"
            }
            for resistor_id, _component in resistors:
                grounded = any(
                    f"{resistor_id}:OUT" in endpoint_keys
                    and any(f"{ground_id}:GND" in endpoint_keys for ground_id in ground_ids)
                    for endpoint_keys in net_endpoint_sets
                )
                if not grounded:
                    reasons.append("fault_resistor_ground_unconnected")
        adapters = [
            (logical_id, component)
            for logical_id, component in components.items()
            if component.get("definition") == "master:fault_state_integer_to_real"
        ]
        measurement_id = fault_outputs[0].get("measurement")
        state_measurements = [
            measurement
            for measurement in measurements
            if measurement.get("logical_id") == measurement_id
        ]
        if len(adapters) != 1:
            reasons.append("fault_state_adapter_missing")
        if len(state_measurements) != 1:
            reasons.append("fault_state_measurement_missing")
        if len(adapters) == 1 and len(state_measurements) == 1:
            adapter_id, adapter = adapters[0]
            adapter_definition = definitions.get(
                str(adapter.get("definition")), {}
            )
            if not _has_port(
                adapter_definition, "IN", kind="data", dimension=1
            ) or not _has_port(
                adapter_definition, "OUT", kind="data", dimension=1
            ):
                reasons.append("fault_state_adapter_port_missing")
            measurement = state_measurements[0]
            state_component = measurement.get("component")
            state_port = measurement.get("port")
            state_connected = any(
                {f"{timer_id}:Y", f"{adapter_id}:IN"} <= endpoint_keys
                for endpoint_keys in net_endpoint_sets
            ) and any(
                {
                    f"{adapter_id}:OUT",
                    f"{state_component}:{state_port}",
                }
                <= endpoint_keys
                for endpoint_keys in net_endpoint_sets
            )
            if not state_connected:
                reasons.append("fault_state_signal_unconnected")
    else:
        if not _has_port(shunt_definition, "N", kind="electrical", dimension=3):
            reasons.append("fault_shunt_phase_port_missing")
        if not _has_port(shunt_definition, "IS", kind="data", direction="input"):
            reasons.append("fault_shunt_trigger_port_missing")
    net_ids = {str(net.get("logical_id")) for net in nets}
    if event["target_bus"] not in net_ids and not breaker_group:
        reasons.append("fault_bus_missing")
    trigger_connected = breaker_group or any(
        {
            f"{timer_id}:Y",
            f"{shunt_id}:IS",
        }
        <= endpoint_keys
        for endpoint_keys in net_endpoint_sets
    )
    if not trigger_connected:
        reasons.append("fault_trigger_unconnected")
    bus_connected = (
        all(
            any(
                any(endpoint.get("component") == logical_id and endpoint.get("port") == "A" for endpoint in _records(net.get("endpoints", ()), "net.endpoints"))
                for net in nets
            )
            for logical_id, _component in shunts
        )
        if breaker_group
        else any(
        event["target_bus"] == net.get("logical_id")
        and any(endpoint.get("component") == shunt_id and endpoint.get("port") == "N" for endpoint in _records(net.get("endpoints", ()), "net.endpoints"))
        for net in nets
        )
    )
    if not bus_connected:
        reasons.append("fault_shunt_unconnected")
    if reasons:
        return {"status": INCOMPLETE, "reasons": list(dict.fromkeys(reasons)), "bindings": {}}
    return {
        "status": PASS,
        "reasons": [],
        "bindings": {
            "event": event,
            "timer_component": timer_id,
            "shunt_component": (
                "inverter_fault_shunt_group" if breaker_group else shunt_id
            ),
            "channel": fault_outputs[0].get("path"),
            "control_components": list(control_components),
            "control_parameter": events[0]["control_parameter"],
            "apply_value": events[0]["apply_value"],
            "clear_value": events[0]["clear_value"],
        },
    }


__all__ = [
    "INCOMPLETE",
    "PASS",
    "FixedLccFaultEvent",
    "inspect_fixed_lcc_fault_capability",
    "validate_fixed_lcc_fault_event",
]
