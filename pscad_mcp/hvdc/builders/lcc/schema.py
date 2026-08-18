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
