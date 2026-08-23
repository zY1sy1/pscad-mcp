"""Strict parsing for the JSON blueprint consumed by the LCC builder."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from ....core.backend.base import BackendError
from .models import (
    LccBlueprint,
    LccComponentSpec,
    LccEndpoint,
    LccNetSpec,
    LccOutputSpec,
    LccRoute,
)
from .parametric_models import (
    LccModeEvent,
    LccModeRequest,
    LccRatings,
    LccTemplateMapping,
    ParametricLccRequest,
)


_TOP_LEVEL_KEYS = {
    "schema_version",
    "name",
    "topology",
    "poles",
    "terminals",
    "profile",
    "benchmark_profile",
    "settings",
    "canvases",
    "components",
    "nets",
    "measurements",
    "outputs",
    "structural_assertions",
}
_SETTINGS_KEYS = {
    "time_step_s",
    "output_step_s",
    "simulation_duration_s",
    "compiler_target",
    "compiler",
    "output_enabled",
    "pscad_version",
    "x64",
    "frequency_hz",
    "project_type",
    "simulation_set",
}
_COMPONENT_KEYS = {
    "logical_id",
    "definition",
    "canvas",
    "location",
    "orientation",
    "parameters",
    "ports",
    "bounding_box",
    "role",
}
_LOCATION_KEYS = {"x", "y"}
_PORT_KEYS = {"name", "kind", "dimension"}
_NET_KEYS = {"logical_id", "kind", "endpoints", "route", "label"}
_ENDPOINT_KEYS = {"component", "port", "kind"}
_ROUTE_KEYS = {"vertices", "policy"}
_OUTPUT_KEYS = {
    "logical_id",
    "path",
    "units",
    "role",
    "call_id",
    "location",
    "measurement",
}
_CANVAS_KEYS = {"name", "width", "height", "grid"}
_MEASUREMENT_KEYS = {"logical_id", "kind", "component", "port", "channels"}
_ASSERTION_KEYS = {"kind", "logical_id", "expected", "message"}
_PARAMETRIC_TOP_LEVEL_KEYS = {
    "topology",
    "ratings",
    "engineering_overrides",
    "operation_modes",
    "return_path_assets",
    "mode_requests",
    "template_mappings",
}
_PARAMETRIC_RATING_KEYS = {
    "rated_power_mw",
    "dc_voltage_kv",
    "dc_current_ka",
    "ac_voltage_kv",
    "frequency_hz",
    "scr",
    "escr",
}
_PARAMETRIC_MODE_KEYS = {"mode", "events"}
_PARAMETRIC_EVENT_KEYS = {"event_id", "time_s", "target", "value"}
_PARAMETRIC_TEMPLATE_KEYS = {"role", "definition", "ports", "parameters", "confidence", "source"}
_SUPPORTED_TOPOLOGIES = {"monopolar", "bipolar"}
_SUPPORTED_OPERATION_MODES = {
    "bipolar_run",
    "monopolar_earth_return",
    "monopolar_metallic_return",
    "metallic_return",
    "positive_pole_outage",
    "negative_pole_outage",
    "pole_outage",
    "scheduled_switching",
}


def _invalid(message: str, **details: Any) -> BackendError:
    return BackendError(
        "LCC_BLUEPRINT_INVALID",
        message,
        "hvdc",
        "parse_lcc_blueprint",
        details,
    )


def _object(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{context} must be an object.", context=context)
    return value


def _keys(value: Mapping[str, Any], allowed: set[str], context: str) -> None:
    non_string = [key for key in value if not isinstance(key, str)]
    if non_string:
        raise _invalid(
            f"{context} keys must be strings.",
            context=context,
            keys=[repr(key) for key in non_string],
        )
    unknown = sorted(key for key in value if key not in allowed)
    if unknown:
        raise _invalid(
            f"{context} contains unknown field(s): {', '.join(unknown)}.",
            context=context,
            unknown=unknown,
        )


def _sequence(value: Any, context: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise _invalid(f"{context} must be an array.", context=context)
    return value


def _text(value: Any, context: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{context} must be a string.", context=context)
    result = value.strip()
    if required and not result:
        raise _invalid(f"{context} must not be empty.", context=context)
    return result


def _integer(value: Any, context: str, *, positive: bool = False, nonnegative: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(f"{context} must be an integer.", context=context)
    if positive and value <= 0:
        raise _invalid(f"{context} must be positive.", context=context)
    if nonnegative and value < 0:
        raise _invalid(f"{context} must be non-negative.", context=context)
    return value


def _number(value: Any, context: str, *, positive: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(f"{context} must be a number.", context=context)
    try:
        finite = math.isfinite(float(value))
    except (OverflowError, ValueError):
        finite = False
    if not finite:
        raise _invalid(f"{context} must be finite.", context=context)
    if positive and value <= 0:
        raise _invalid(f"{context} must be positive.", context=context)
    return value


def _json_value(value: Any, context: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _invalid(f"{context} contains a non-finite number.", context=context)
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _invalid(f"{context} keys must be strings.", context=context)
            result[key] = _json_value(item, f"{context}.{key}")
        return result
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [_json_value(item, f"{context}[{index}]") for index, item in enumerate(value)]
    raise _invalid(f"{context} contains a non-JSON value.", context=context)


def _parse_location(value: Any, context: str) -> tuple[int, int]:
    location = _object(value, context)
    _keys(location, _LOCATION_KEYS, context)
    if set(location) != _LOCATION_KEYS:
        raise _invalid(f"{context} requires x and y.", context=context)
    return (
        _integer(location["x"], f"{context}.x"),
        _integer(location["y"], f"{context}.y"),
    )


def _parse_route(value: Any, context: str) -> LccRoute:
    route = _object(value, context)
    _keys(route, _ROUTE_KEYS, context)
    vertices = _sequence(route.get("vertices"), f"{context}.vertices")
    if len(vertices) < 2:
        raise _invalid(f"{context}.vertices requires at least two points.", context=context)
    parsed: list[tuple[int, int]] = []
    for index, vertex in enumerate(vertices):
        point = _sequence(vertex, f"{context}.vertices[{index}]")
        if len(point) != 2:
            raise _invalid(
                f"{context}.vertices[{index}] requires two coordinates.",
                context=f"{context}.vertices[{index}]",
            )
        parsed.append(
            (
                _integer(point[0], f"{context}.vertices[{index}][0]"),
                _integer(point[1], f"{context}.vertices[{index}][1]"),
            )
        )
    for index, (left, right) in enumerate(zip(parsed, parsed[1:])):
        if left == right:
            raise _invalid(
                f"{context}.vertices contains a zero-length segment.",
                context=context,
                segment=index,
            )
        if left[0] != right[0] and left[1] != right[1]:
            raise _invalid(
                f"{context}.vertices contains a diagonal segment.",
                context=context,
                segment=index,
            )
    policy = route.get("policy")
    return LccRoute(
        vertices=tuple(parsed),
        policy=None if policy is None else _text(policy, f"{context}.policy"),
    )


def _parse_component(value: Any, index: int) -> LccComponentSpec:
    context = f"components[{index}]"
    component = _object(value, context)
    _keys(component, _COMPONENT_KEYS, context)
    required = {"logical_id", "definition", "location"}
    missing = sorted(required - set(component))
    if missing:
        raise _invalid(f"{context} requires {', '.join(missing)}.", context=context)
    logical_id = _text(component["logical_id"], f"{context}.logical_id")
    definition = _text(component["definition"], f"{context}.definition")
    orientation = _integer(component.get("orientation", 0), f"{context}.orientation")
    if not 0 <= orientation <= 7:
        raise _invalid(f"{context}.orientation must be between 0 and 7.", context=context)
    parameters_value = component.get("parameters", {})
    parameters = _object(parameters_value, f"{context}.parameters")
    parsed_parameters: dict[str, Any] = {}
    for key, value in parameters.items():
        if not isinstance(key, str):
            raise _invalid(
                f"{context}.parameters keys must be strings.",
                context=f"{context}.parameters",
                key=repr(key),
            )
        parsed_parameters[key] = _json_value(value, f"{context}.parameters.{key}")
    ports_value = component.get("ports", ())
    ports = _sequence(ports_value, f"{context}.ports")
    parsed_ports: list[str] = []
    port_contracts: list[dict[str, Any]] = []
    for port_index, port in enumerate(ports):
        port_context = f"{context}.ports[{port_index}]"
        if isinstance(port, Mapping):
            _keys(port, _PORT_KEYS, port_context)
            if "name" not in port:
                raise _invalid(f"{port_context} requires name.", context=port_context)
            port_name = _text(port["name"], f"{port_context}.name")
            if "kind" in port:
                _text(port["kind"], f"{port_context}.kind")
            if "dimension" in port:
                _integer(port["dimension"], f"{port_context}.dimension", positive=True)
            port_contracts.append(
                {
                    key: _json_value(item, f"{port_context}.{key}")
                    for key, item in port.items()
                }
            )
            parsed_ports.append(port_name)
        else:
            port_name = _text(port, port_context)
            parsed_ports.append(port_name)
            port_contracts.append({"name": port_name})
    bounding_box = component.get("bounding_box")
    parsed_box = None
    if bounding_box is not None:
        box = _sequence(bounding_box, f"{context}.bounding_box")
        if len(box) != 4:
            raise _invalid(f"{context}.bounding_box requires four integers.", context=context)
        parsed_box = tuple(
            _integer(item, f"{context}.bounding_box[{box_index}]")
            for box_index, item in enumerate(box)
        )
    canvas = _text(component.get("canvas", "Main"), f"{context}.canvas")
    role = component.get("role")
    return LccComponentSpec(
        logical_id=logical_id,
        definition=definition,
        location=_parse_location(component["location"], f"{context}.location"),
        orientation=orientation,
        parameters=parsed_parameters,
        ports=tuple(parsed_ports),
        port_contracts=tuple(port_contracts),
        canvas=canvas,
        bounding_box=parsed_box,
        role=None if role is None else _text(role, f"{context}.role"),
    )


def _parse_net(value: Any, index: int, component_map: Mapping[str, LccComponentSpec]) -> LccNetSpec:
    context = f"nets[{index}]"
    net = _object(value, context)
    _keys(net, _NET_KEYS, context)
    required = {"logical_id", "kind", "endpoints"}
    missing = sorted(required - set(net))
    if missing:
        raise _invalid(f"{context} requires {', '.join(missing)}.", context=context)
    logical_id = _text(net["logical_id"], f"{context}.logical_id")
    kind = _text(net["kind"], f"{context}.kind")
    if kind not in {"electrical", "data"}:
        raise _invalid(f"{context}.kind must be electrical or data.", context=context)
    endpoints_value = _sequence(net["endpoints"], f"{context}.endpoints")
    if len(endpoints_value) < 2:
        raise _invalid(f"{context}.endpoints requires at least two endpoints.", context=context)
    endpoints: list[LccEndpoint] = []
    for endpoint_index, value in enumerate(endpoints_value):
        endpoint_context = f"{context}.endpoints[{endpoint_index}]"
        endpoint = _object(value, endpoint_context)
        _keys(endpoint, _ENDPOINT_KEYS, endpoint_context)
        if not {"component", "port"} <= set(endpoint):
            raise _invalid(
                f"{endpoint_context} requires component and port.",
                context=endpoint_context,
            )
        component_id = _text(endpoint["component"], f"{endpoint_context}.component")
        port = _text(endpoint["port"], f"{endpoint_context}.port")
        component = component_map.get(component_id)
        if component is None:
            raise _invalid(
                f"{endpoint_context} references an unknown component.",
                context=endpoint_context,
                component=component_id,
            )
        if component.ports and port not in component.ports:
            raise _invalid(
                f"{endpoint_context} references an undeclared port.",
                context=endpoint_context,
                component=component_id,
                port=port,
            )
        endpoint_kind = endpoint.get("kind")
        endpoints.append(
            LccEndpoint(
                component=component_id,
                port=port,
                kind=None if endpoint_kind is None else _text(endpoint_kind, f"{endpoint_context}.kind"),
            )
        )
    route_value = net.get("route")
    route = None if route_value is None else _parse_route(route_value, f"{context}.route")
    label = net.get("label")
    return LccNetSpec(
        logical_id=logical_id,
        kind=kind,
        endpoints=tuple(endpoints),
        route=route,
        label=None if label is None else _text(label, f"{context}.label"),
    )


def _parse_output(value: Any, index: int) -> LccOutputSpec:
    context = f"outputs[{index}]"
    output = _object(value, context)
    _keys(output, _OUTPUT_KEYS, context)
    required = {"logical_id", "path", "units", "role"}
    missing = sorted(required - set(output))
    if missing:
        raise _invalid(f"{context} requires {', '.join(missing)}.", context=context)
    call_id = output.get("call_id")
    if call_id is not None:
        call_id = _integer(call_id, f"{context}.call_id", positive=True)
    return LccOutputSpec(
        logical_id=_text(output["logical_id"], f"{context}.logical_id"),
        path=_text(output["path"], f"{context}.path"),
        units=_text(output["units"], f"{context}.units"),
        role=_text(output["role"], f"{context}.role"),
        call_id=call_id,
        location=None if output.get("location") is None else _text(output["location"], f"{context}.location"),
        measurement=None if output.get("measurement") is None else _text(output["measurement"], f"{context}.measurement"),
    )


def _parse_canvases(value: Any) -> tuple[dict[str, Any], ...]:
    records = _sequence(value, "canvases")
    parsed: list[dict[str, Any]] = []
    for index, record_value in enumerate(records):
        context = f"canvases[{index}]"
        record = _object(record_value, context)
        _keys(record, _CANVAS_KEYS, context)
        if "name" not in record:
            raise _invalid(f"{context} requires name.", context=context)
        output = {"name": _text(record["name"], f"{context}.name")}
        for key in ("width", "height"):
            if key in record:
                output[key] = _integer(record[key], f"{context}.{key}", positive=True)
        if "grid" in record:
            output["grid"] = _number(record["grid"], f"{context}.grid", positive=True)
        parsed.append(output)
    return tuple(parsed)


def _parse_measurements(value: Any) -> tuple[dict[str, Any], ...]:
    records = _sequence(value, "measurements")
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, record_value in enumerate(records):
        context = f"measurements[{index}]"
        record = _object(record_value, context)
        _keys(record, _MEASUREMENT_KEYS, context)
        for key in ("logical_id", "kind"):
            if key not in record:
                raise _invalid(f"{context} requires {key}.", context=context)
        logical_id = _text(record["logical_id"], f"{context}.logical_id")
        if logical_id in seen:
            raise _invalid("measurement logical IDs must be unique.", logical_id=logical_id)
        seen.add(logical_id)
        output: dict[str, Any] = {
            "logical_id": logical_id,
            "kind": _text(record["kind"], f"{context}.kind"),
        }
        for key in ("component", "port"):
            if key in record:
                output[key] = _text(record[key], f"{context}.{key}")
        if "channels" in record:
            channels = _sequence(record["channels"], f"{context}.channels")
            output["channels"] = tuple(
                _text(channel, f"{context}.channels[{channel_index}]")
                for channel_index, channel in enumerate(channels)
            )
        parsed.append(output)
    return tuple(parsed)


def _parse_assertions(value: Any) -> tuple[dict[str, Any], ...]:
    records = _sequence(value, "structural_assertions")
    parsed: list[dict[str, Any]] = []
    for index, record_value in enumerate(records):
        context = f"structural_assertions[{index}]"
        record = _object(record_value, context)
        _keys(record, _ASSERTION_KEYS, context)
        if "kind" not in record:
            raise _invalid(f"{context} requires kind.", context=context)
        output: dict[str, Any] = {"kind": _text(record["kind"], f"{context}.kind")}
        if "logical_id" in record:
            output["logical_id"] = _text(record["logical_id"], f"{context}.logical_id")
        if "expected" in record:
            output["expected"] = _json_value(record["expected"], f"{context}.expected")
        if "message" in record:
            output["message"] = _text(record["message"], f"{context}.message")
        parsed.append(output)
    return tuple(parsed)


def _parse_named_records(value: Any, allowed: set[str], context: str) -> tuple[dict[str, Any], ...]:
    records = _sequence(value, context)
    parsed: list[dict[str, Any]] = []
    for index, record_value in enumerate(records):
        record_context = f"{context}[{index}]"
        record = _object(record_value, record_context)
        _keys(record, allowed, record_context)
        parsed.append({key: _json_value(item, f"{record_context}.{key}") for key, item in record.items()})
    return tuple(parsed)


def _parametric_invalid(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", "parse_parametric_request", details)


def _parametric_object(value: Any, context: str, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _parametric_invalid(code, f"{context} must be an object.", context=context)
    return value


def _parametric_keys(value: Mapping[str, Any], allowed: set[str], context: str, code: str) -> None:
    non_string = [key for key in value if not isinstance(key, str)]
    if non_string:
        raise _parametric_invalid(
            code,
            f"{context} keys must be strings.",
            context=context,
            keys=[repr(key) for key in non_string],
        )
    unknown = sorted(key for key in value if key not in allowed)
    if unknown:
        raise _parametric_invalid(
            code,
            f"{context} contains unknown field(s): {', '.join(unknown)}.",
            context=context,
            unknown=unknown,
        )


def _parametric_number(value: Any, context: str, code: str, *, positive: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _parametric_invalid(code, f"{context} must be a number.", context=context)
    try:
        finite = math.isfinite(float(value))
    except (OverflowError, ValueError):
        finite = False
    if not finite:
        raise _parametric_invalid(code, f"{context} must be finite.", context=context)
    if positive and value <= 0:
        raise _parametric_invalid(code, f"{context} must be positive.", context=context)
    return value


def _parametric_text(value: Any, context: str, code: str) -> str:
    if not isinstance(value, str):
        raise _parametric_invalid(code, f"{context} must be a string.", context=context)
    result = value.strip()
    if not result:
        raise _parametric_invalid(code, f"{context} must not be empty.", context=context)
    return result


def _parse_parametric_ratings(value: Any) -> LccRatings:
    ratings = _parametric_object(value, "ratings", "LCC_RATING_INVALID")
    _parametric_keys(ratings, _PARAMETRIC_RATING_KEYS, "ratings", "LCC_RATING_INVALID")
    required = {"rated_power_mw", "dc_voltage_kv", "dc_current_ka", "ac_voltage_kv", "frequency_hz", "scr"}
    missing = sorted(required - set(ratings))
    if missing:
        raise _parametric_invalid(
            "LCC_RATING_INVALID",
            f"ratings requires {', '.join(missing)}.",
            context="ratings",
        )
    payload: dict[str, Any] = {}
    for key in required:
        payload[key] = _parametric_number(ratings[key], f"ratings.{key}", "LCC_RATING_INVALID", positive=True)
    if "escr" in ratings:
        payload["escr"] = _parametric_number(ratings["escr"], "ratings.escr", "LCC_RATING_INVALID", positive=True)
    try:
        return LccRatings(**payload)
    except (TypeError, ValueError) as error:
        raise _parametric_invalid("LCC_RATING_INVALID", str(error), context="ratings") from error


def _parse_parametric_event(value: Any, index: int) -> LccModeEvent:
    context = f"mode_requests[{index}]"
    event = _parametric_object(value, context, "LCC_OPERATING_MODE_INVALID")
    _parametric_keys(event, _PARAMETRIC_EVENT_KEYS, context, "LCC_OPERATING_MODE_INVALID")
    required = {"event_id", "time_s", "target", "value"}
    missing = sorted(required - set(event))
    if missing:
        raise _parametric_invalid(
            "LCC_OPERATING_MODE_INVALID",
            f"{context} requires {', '.join(missing)}.",
            context=context,
        )
    try:
        return LccModeEvent(
            event_id=_parametric_text(event["event_id"], f"{context}.event_id", "LCC_OPERATING_MODE_INVALID"),
            time_s=_parametric_number(event["time_s"], f"{context}.time_s", "LCC_OPERATING_MODE_INVALID"),
            target=_parametric_text(event["target"], f"{context}.target", "LCC_OPERATING_MODE_INVALID"),
            value=_json_value(event["value"], f"{context}.value"),
        )
    except (TypeError, ValueError) as error:
        raise _parametric_invalid("LCC_OPERATING_MODE_INVALID", str(error), context=context) from error


def _parse_parametric_mode_request(value: Any, index: int, supported_modes: set[str]) -> LccModeRequest:
    context = f"mode_requests[{index}]"
    request = _parametric_object(value, context, "LCC_OPERATING_MODE_INVALID")
    _parametric_keys(request, _PARAMETRIC_MODE_KEYS, context, "LCC_OPERATING_MODE_INVALID")
    required = {"mode", "events"}
    missing = sorted(required - set(request))
    if missing:
        raise _parametric_invalid(
            "LCC_OPERATING_MODE_INVALID",
            f"{context} requires {', '.join(missing)}.",
            context=context,
        )
    mode = _parametric_text(request["mode"], f"{context}.mode", "LCC_OPERATING_MODE_INVALID")
    if mode not in supported_modes:
        raise _parametric_invalid(
            "LCC_OPERATING_MODE_INVALID",
            f"{context}.mode is not supported.",
            context=context,
            mode=mode,
        )
    events_value = _sequence(request["events"], f"{context}.events")
    if not events_value:
        raise _parametric_invalid("LCC_OPERATING_MODE_INVALID", f"{context}.events must not be empty.", context=context)
    events = tuple(_parse_parametric_event(value, event_index) for event_index, value in enumerate(events_value))
    previous_time: float | None = None
    for event in events:
        if event.time_s < 0:
            raise _parametric_invalid(
                "LCC_OPERATING_MODE_INVALID",
                f"{context}.events contains a negative time.",
                context=context,
                event_id=event.event_id,
            )
        if previous_time is not None and event.time_s <= previous_time:
            raise _parametric_invalid(
                "LCC_OPERATING_MODE_INVALID",
                f"{context}.events must be strictly increasing.",
                context=context,
                event_id=event.event_id,
            )
        previous_time = event.time_s
    try:
        return LccModeRequest(mode=mode, events=events)
    except (TypeError, ValueError) as error:
        raise _parametric_invalid("LCC_OPERATING_MODE_INVALID", str(error), context=context) from error


def _parse_parametric_template_mapping(value: Any, index: int) -> LccTemplateMapping:
    context = f"template_mappings[{index}]"
    mapping = _parametric_object(value, context, "LCC_OPERATING_MODE_INVALID")
    _parametric_keys(mapping, _PARAMETRIC_TEMPLATE_KEYS, context, "LCC_OPERATING_MODE_INVALID")
    required = {"role", "definition"}
    missing = sorted(required - set(mapping))
    if missing:
        raise _parametric_invalid(
            "LCC_OPERATING_MODE_INVALID",
            f"{context} requires {', '.join(missing)}.",
            context=context,
        )
    kwargs: dict[str, Any] = {
        "role": _parametric_text(mapping["role"], f"{context}.role", "LCC_OPERATING_MODE_INVALID"),
        "definition": _parametric_text(mapping["definition"], f"{context}.definition", "LCC_OPERATING_MODE_INVALID"),
    }
    if "ports" in mapping:
        kwargs["ports"] = tuple(_parametric_text(port, f"{context}.ports", "LCC_OPERATING_MODE_INVALID") for port in _sequence(mapping["ports"], f"{context}.ports"))
    if "parameters" in mapping:
        kwargs["parameters"] = tuple(
            _parametric_text(parameter, f"{context}.parameters", "LCC_OPERATING_MODE_INVALID")
            for parameter in _sequence(mapping["parameters"], f"{context}.parameters")
        )
    if "confidence" in mapping:
        kwargs["confidence"] = _parametric_number(mapping["confidence"], f"{context}.confidence", "LCC_OPERATING_MODE_INVALID")
    if "source" in mapping:
        kwargs["source"] = _parametric_text(mapping["source"], f"{context}.source", "LCC_OPERATING_MODE_INVALID")
    try:
        return LccTemplateMapping(**kwargs)
    except (TypeError, ValueError) as error:
        raise _parametric_invalid("LCC_OPERATING_MODE_INVALID", str(error), context=context) from error


def parse_parametric_request(data: Mapping[str, Any]) -> ParametricLccRequest:
    request = _parametric_object(data, "parametric_request", "LCC_OPERATING_MODE_INVALID")
    _parametric_keys(request, _PARAMETRIC_TOP_LEVEL_KEYS, "parametric_request", "LCC_OPERATING_MODE_INVALID")
    required = {"topology", "ratings"}
    missing = sorted(required - set(request))
    if missing:
        raise _parametric_invalid(
            "LCC_OPERATING_MODE_INVALID",
            f"parametric_request requires {', '.join(missing)}.",
            context="parametric_request",
        )
    topology = _parametric_text(request["topology"], "topology", "LCC_OPERATING_MODE_INVALID")
    if topology not in _SUPPORTED_TOPOLOGIES:
        raise _parametric_invalid(
            "LCC_OPERATING_MODE_INVALID",
            "topology is not supported.",
            context="topology",
            topology=topology,
        )
    ratings = _parse_parametric_ratings(request["ratings"])
    engineering_overrides = request.get("engineering_overrides", {})
    if not isinstance(engineering_overrides, Mapping):
        raise _parametric_invalid(
            "LCC_OPERATING_MODE_INVALID",
            "engineering_overrides must be an object.",
            context="engineering_overrides",
        )
    operation_modes_value = request.get("operation_modes", ())
    operation_modes = tuple(
        _parametric_text(mode, "operation_modes", "LCC_OPERATING_MODE_INVALID")
        for mode in _sequence(operation_modes_value, "operation_modes")
    )
    for mode in operation_modes:
        if mode not in _SUPPORTED_OPERATION_MODES:
            raise _parametric_invalid(
                "LCC_OPERATING_MODE_INVALID",
                "operation_modes contains an unsupported mode.",
                context="operation_modes",
                mode=mode,
            )
    return_path_assets = tuple(
        _parametric_text(asset, "return_path_assets", "LCC_OPERATING_MODE_INVALID")
        for asset in _sequence(request.get("return_path_assets", ()), "return_path_assets")
    )
    if len(set(return_path_assets)) != len(return_path_assets):
        raise _parametric_invalid(
            "LCC_OPERATING_MODE_INVALID",
            "return_path_assets must contain unique explicit asset identifiers.",
            context="return_path_assets",
        )
    mode_requests_value = request.get("mode_requests", ())
    mode_requests = tuple(
        _parse_parametric_mode_request(mode_request, mode_index, set(operation_modes) or _SUPPORTED_OPERATION_MODES)
        for mode_index, mode_request in enumerate(_sequence(mode_requests_value, "mode_requests"))
    )
    template_mappings_value = request.get("template_mappings", ())
    template_mappings = tuple(
        _parse_parametric_template_mapping(mapping, mapping_index)
        for mapping_index, mapping in enumerate(_sequence(template_mappings_value, "template_mappings"))
    )
    return ParametricLccRequest(
        topology=topology,
        ratings=ratings,
        engineering_overrides={key: _json_value(value, f"engineering_overrides.{key}") for key, value in engineering_overrides.items()},
        operation_modes=operation_modes,
        return_path_assets=return_path_assets,
        mode_requests=mode_requests,
        template_mappings=template_mappings,
    )


def parse_blueprint(data: Mapping[str, Any]) -> LccBlueprint:
    """Parse and validate a version-one JSON blueprint without side effects."""

    blueprint = _object(data, "blueprint")
    _keys(blueprint, _TOP_LEVEL_KEYS, "blueprint")
    required = {"schema_version", "name", "topology", "poles", "terminals", "settings", "components", "nets", "outputs"}
    missing = sorted(required - set(blueprint))
    if missing:
        raise _invalid(f"blueprint requires {', '.join(missing)}.", context="blueprint")
    schema_version = _integer(blueprint["schema_version"], "schema_version", positive=True)
    if schema_version != 1:
        raise _invalid("schema_version must be 1.", schema_version=schema_version)
    name = _text(blueprint["name"], "name")
    topology = _text(blueprint["topology"], "topology")
    poles = _integer(blueprint["poles"], "poles", positive=True)
    terminals = _integer(blueprint["terminals"], "terminals", positive=True)

    settings_value = _object(blueprint["settings"], "settings")
    _keys(settings_value, _SETTINGS_KEYS, "settings")
    settings = {key: _json_value(value, f"settings.{key}") for key, value in settings_value.items()}
    for key in {"time_step_s", "output_step_s", "simulation_duration_s", "frequency_hz"} & set(settings):
        _number(settings[key], f"settings.{key}", positive=True)
    for key in {"compiler_target", "compiler", "pscad_version", "project_type", "simulation_set"} & set(settings):
        _text(settings[key], f"settings.{key}")
    for key in {"output_enabled", "x64"} & set(settings):
        if not isinstance(settings[key], bool):
            raise _invalid(f"settings.{key} must be a boolean.", context=f"settings.{key}")

    components_value = _sequence(blueprint["components"], "components")
    components = tuple(_parse_component(value, index) for index, value in enumerate(components_value))
    component_map: dict[str, LccComponentSpec] = {}
    for component in components:
        if component.logical_id in component_map:
            raise _invalid(
                "component logical IDs must be unique.",
                logical_id=component.logical_id,
            )
        component_map[component.logical_id] = component

    nets_value = _sequence(blueprint["nets"], "nets")
    nets = tuple(_parse_net(value, index, component_map) for index, value in enumerate(nets_value))
    net_ids = [net.logical_id for net in nets]
    if len(set(net_ids)) != len(net_ids):
        raise _invalid("net logical IDs must be unique.", logical_ids=net_ids)

    outputs_value = _sequence(blueprint["outputs"], "outputs")
    outputs = tuple(_parse_output(value, index) for index, value in enumerate(outputs_value))
    output_ids = [output.logical_id for output in outputs]
    if len(set(output_ids)) != len(output_ids):
        raise _invalid("output logical IDs must be unique.", logical_ids=output_ids)

    canvases = _parse_canvases(blueprint.get("canvases", ()))
    measurements = _parse_measurements(blueprint.get("measurements", ()))
    assertions = _parse_assertions(blueprint.get("structural_assertions", ()))
    if "profile" in blueprint and "benchmark_profile" in blueprint:
        raise _invalid(
            "blueprint cannot define both profile and benchmark_profile.",
            context="blueprint",
        )
    profile = blueprint.get("profile", blueprint.get("benchmark_profile"))
    if profile is not None:
        profile = _text(profile, "profile")
    return LccBlueprint(
        schema_version=schema_version,
        name=name,
        topology=topology,
        poles=poles,
        terminals=terminals,
        settings=settings,
        components=components,
        nets=nets,
        outputs=outputs,
        canvases=canvases,
        measurements=measurements,
        structural_assertions=assertions,
        profile=profile,
    )
