"""Independent structural validation for generated LCC projects."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError
from .assets import load_parametric_catalog, validate_parametric_blueprint_asset
from .catalog import LccCatalog, parse_catalog, require_definition, require_port, validate_parameters
from .models import LccBlueprint, LccComponentSpec, LccNetSpec
from .project_graph import GraphComponent, GraphNet, GraphPort, ProjectGraph
from .schema import parse_blueprint


_CODE = "LCC_STRUCTURE_INVALID"
_PROJECT_OPERATION = "validate_lcc_project_graph"
_LIBRARY_OPERATION = "validate_lcc_companion_library"

_REQUIRED_DEFINITION_PORTS: dict[str, tuple[str, ...]] = {
    "cigre_lcc_v1:LCC12PulseBridge": (
        "ACY_A",
        "ACY_B",
        "ACY_C",
        "ACD_A",
        "ACD_B",
        "ACD_C",
        "DC_POS",
        "DC_NEG",
        "GATES",
    ),
    "cigre_lcc_v1:RectifierControl": ("VDC", "IDC", "IORDER", "ENABLE", "GATES", "ALPHA"),
    "cigre_lcc_v1:InverterControl": ("VDC", "IDC", "GAMMA_ORDER", "ENABLE", "GATES", "GAMMA"),
    "cigre_lcc_v1:SignalInterface": (),
    "cigre_lcc_v1:Initialization": (),
}

_EXPECTED_VALVE_GROUPS = {
    **{f"V{index:02d}": "upper" for index in range(1, 7)},
    **{f"V{index:02d}": "lower" for index in range(7, 13)},
}

_CONTROL_CONTRACTS = {
    "cigre_lcc_v1:RectifierControl": {
        "definition": "master:cc_controller",
        "role": "constant_current",
    },
    "cigre_lcc_v1:InverterControl": {
        "definition": "master:cc_controller",
        "role": "constant_extinction_angle",
    },
}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    return str(value)


def _finding(logical_id: str | None, reason: str, expected: Any = None, observed: Any = None) -> dict[str, Any]:
    return {
        "code": _CODE,
        "logical_id": "" if logical_id is None else logical_id,
        "reason": reason,
        "expected": _json_safe(expected),
        "observed": _json_safe(observed),
    }


def _sort_findings(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(errors, key=lambda item: (item["code"], item["logical_id"], item["reason"]))


def _backend_error(message: str, operation: str, errors: list[dict[str, Any]], **details: Any) -> BackendError:
    payload = dict(details)
    payload["errors"] = _sort_findings(errors)
    return BackendError(_CODE, message, "hvdc", operation, payload)


def _as_blueprint(blueprint: LccBlueprint | Mapping[str, Any]) -> LccBlueprint:
    if isinstance(blueprint, LccBlueprint):
        return blueprint
    if isinstance(blueprint, Mapping):
        return parse_blueprint(blueprint)
    raise BackendError(
        _CODE,
        "blueprint must be an LccBlueprint or mapping.",
        "hvdc",
        _PROJECT_OPERATION,
        {"observed_type": type(blueprint).__name__},
    )


def _as_catalog(catalog: LccCatalog | Mapping[str, Any] | None) -> LccCatalog | None:
    if catalog is None or isinstance(catalog, LccCatalog):
        return catalog
    if isinstance(catalog, Mapping):
        return parse_catalog(catalog)
    raise BackendError(
        _CODE,
        "catalog must be an LccCatalog, mapping, or None.",
        "hvdc",
        _PROJECT_OPERATION,
        {"observed_type": type(catalog).__name__},
    )


def _component_map(components: Sequence[GraphComponent]) -> tuple[dict[str, GraphComponent], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    seen: dict[str, GraphComponent] = {}
    counts = Counter(component.logical_id for component in components)
    for logical_id, count in counts.items():
        if count > 1:
            errors.append(_finding(logical_id, "duplicate component logical_id", 1, count))
    for component in components:
        seen.setdefault(component.logical_id, component)
    return seen, errors


def _port_map(component: GraphComponent) -> dict[str, GraphPort]:
    return {port.name: port for port in component.ports}


def _parameter_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _expected_port_contract(component: LccComponentSpec, port_name: str) -> Mapping[str, Any]:
    for contract in component.port_contracts:
        if contract.get("name") == port_name:
            return contract
    return {"name": port_name}


def _compare_catalog_contracts(
    component: LccComponentSpec,
    catalog: LccCatalog | None,
    errors: list[dict[str, Any]],
) -> None:
    if catalog is None:
        return
    try:
        definition = require_definition(catalog, component.definition)
        for port_name in component.ports:
            contract = _expected_port_contract(component, port_name)
            require_port(
                definition,
                port_name,
                kind=contract.get("kind") if isinstance(contract.get("kind"), str) else None,
                dimension=contract.get("dimension") if isinstance(contract.get("dimension"), int) else None,
            )
        validate_parameters(definition, dict(component.parameters))
    except BackendError as error:
        errors.append(_finding(component.logical_id, "catalog contract mismatch", component.to_dict(), error.to_dict()))


def _compare_component(
    expected: LccComponentSpec,
    observed: GraphComponent,
    errors: list[dict[str, Any]],
) -> None:
    logical_id = expected.logical_id
    if observed.definition != expected.definition:
        errors.append(_finding(logical_id, "component definition mismatch", expected.definition, observed.definition))
    if observed.canvas != expected.canvas:
        errors.append(_finding(logical_id, "component canvas mismatch", expected.canvas, observed.canvas))
    if observed.location != expected.location:
        errors.append(_finding(logical_id, "component location mismatch", expected.location, observed.location))
    if observed.orientation != expected.orientation:
        errors.append(_finding(logical_id, "component orientation mismatch", expected.orientation, observed.orientation))

    expected_parameter_names = set(expected.parameters)
    observed_parameter_names = set(observed.parameters)
    if expected_parameter_names != observed_parameter_names:
        errors.append(
            _finding(
                logical_id,
                "component parameter set mismatch",
                sorted(expected_parameter_names),
                sorted(observed_parameter_names),
            )
        )
    for parameter, expected_value in expected.parameters.items():
        observed_value = observed.parameters.get(parameter)
        if observed_value != _parameter_text(expected_value):
            errors.append(_finding(logical_id, "component parameter mismatch", {parameter: expected_value}, {parameter: observed_value}))

    expected_port_names = sorted(expected.ports)
    observed_port_names = sorted(port.name for port in observed.ports)
    if expected_port_names != observed_port_names:
        expected_port_set = set(expected_port_names)
        observed_port_set = set(observed_port_names)
        if expected_port_set != observed_port_set:
            errors.append(
                _finding(
                    logical_id,
                    "component port set mismatch",
                    expected_port_names,
                    observed_port_names,
                )
            )
        else:
            expected_counts = Counter(expected_port_names)
            observed_counts = Counter(observed_port_names)
            for port_name in sorted(expected_port_set):
                expected_count = expected_counts[port_name]
                observed_count = observed_counts[port_name]
                if observed_count > expected_count:
                    errors.append(
                        _finding(
                            f"{logical_id}:{port_name}",
                            "duplicate component port",
                            expected_count,
                            observed_count,
                        )
                    )
                elif observed_count < expected_count:
                    errors.append(
                        _finding(
                            f"{logical_id}:{port_name}",
                            "component port multiplicity mismatch",
                            expected_count,
                            observed_count,
                        )
                    )
    observed_ports = _port_map(observed)
    for port_name in expected.ports:
        observed_port = observed_ports.get(port_name)
        contract = _expected_port_contract(expected, port_name)
        if observed_port is None:
            errors.append(_finding(f"{logical_id}:{port_name}", "missing port", contract, None))
            continue
        if contract.get("kind") is not None and observed_port.kind != contract["kind"]:
            errors.append(_finding(f"{logical_id}:{port_name}", "port kind mismatch", contract.get("kind"), observed_port.kind))
        if contract.get("dimension") is not None and observed_port.dimension != contract["dimension"]:
            errors.append(_finding(f"{logical_id}:{port_name}", "port dimension mismatch", contract.get("dimension"), observed_port.dimension))


def _endpoint(component: str, port: str) -> str:
    return f"{component}:{port}"


def _expected_net_key(net: LccNetSpec) -> tuple[str, tuple[str, ...]]:
    return net.kind, tuple(sorted(_endpoint(endpoint.component, endpoint.port) for endpoint in net.endpoints))


def _graph_net_key(net: GraphNet) -> tuple[str, tuple[str, ...]]:
    return net.kind, tuple(sorted(net.endpoints))


def _net_route_points(net: LccNetSpec) -> tuple[tuple[int, int], ...]:
    return () if net.route is None else tuple(net.route.vertices)


def _observed_route_points(
    graph: ProjectGraph,
    net: GraphNet,
    expected_points: tuple[tuple[int, int], ...],
) -> tuple[tuple[int, int], ...]:
    net_points = set(net.points)
    wire_points = tuple(
        point
        for wire in graph.wires
        if wire.kind == net.kind and net_points.intersection(wire.vertices)
        for point in wire.vertices
    )
    if wire_points:
        return wire_points

    # Synthetic GraphNet-only fixtures may include label coordinates in points.
    label_locations = {
        label.location
        for label in graph.labels
        if label.location is not None and _matches_namespace(net.kind, label.kind)
    }
    return tuple(point for point in net.points if point not in label_locations or point in expected_points)


def _port_kind(endpoint: str, components: Mapping[str, GraphComponent]) -> str | None:
    component_id, _, port_name = endpoint.partition(":")
    component = components.get(component_id)
    if component is None:
        return None
    port = _port_map(component).get(port_name)
    return None if port is None else port.kind


def _matches_namespace(net_kind: str, port_kind: str | None) -> bool:
    if port_kind is None:
        return False
    if net_kind == "electrical":
        return port_kind == "electrical"
    if net_kind == "data":
        return port_kind in {"data", "signal"}
    return False


def _compare_nets(
    blueprint: LccBlueprint,
    graph: ProjectGraph,
    observed_components: Mapping[str, GraphComponent],
    errors: list[dict[str, Any]],
) -> None:
    expected_by_key = {_expected_net_key(net): net for net in blueprint.nets}
    expected_by_endpoints = {key[1]: net for key, net in expected_by_key.items()}
    observed_counts = Counter(_graph_net_key(net) for net in graph.nets)
    for key, count in observed_counts.items():
        if count > 1:
            expected_net = expected_by_key.get(key)
            errors.append(_finding(None if expected_net is None else expected_net.logical_id, "duplicate net", 1, count))

    observed_by_key: dict[tuple[str, tuple[str, ...]], GraphNet] = {}
    for net in graph.nets:
        observed_by_key.setdefault(_graph_net_key(net), net)
    observed_endpoint_sets = {key[1]: net for key, net in observed_by_key.items()}

    for key, expected_net in expected_by_key.items():
        observed_net = observed_by_key.get(key)
        endpoint_key = key[1]
        if observed_net is None:
            wrong_namespace = observed_endpoint_sets.get(endpoint_key)
            if wrong_namespace is not None:
                errors.append(_finding(expected_net.logical_id, "net namespace mismatch", expected_net.kind, wrong_namespace.kind))
            else:
                errors.append(_finding(expected_net.logical_id, "missing net", expected_net.to_dict(), None))
            continue

        expected_points = _net_route_points(expected_net)
        observed_points = _observed_route_points(graph, observed_net, expected_points)
        if expected_points and observed_points != expected_points:
            errors.append(
                _finding(
                    expected_net.logical_id,
                    "net route mismatch",
                    expected_points,
                    observed_points,
                )
            )
        if expected_net.label is not None and expected_net.label not in observed_net.labels:
            errors.append(_finding(expected_net.logical_id, "net label mismatch", expected_net.label, observed_net.labels))

    expected_endpoint_keys = set(expected_by_key)
    for observed_key, observed_net in observed_by_key.items():
        if observed_key not in expected_endpoint_keys:
            logical_id = None
            if observed_key[1] in expected_by_endpoints:
                logical_id = expected_by_endpoints[observed_key[1]].logical_id
                errors.append(_finding(logical_id, "net namespace mismatch", expected_by_endpoints[observed_key[1]].kind, observed_net.kind))
                continue
            errors.append(_finding(logical_id, "unexpected net", None, observed_net.to_dict()))

    connected = {endpoint for net in graph.nets for endpoint in net.endpoints}
    for net in blueprint.nets:
        for endpoint in net.endpoints:
            endpoint_name = _endpoint(endpoint.component, endpoint.port)
            if endpoint_name not in connected:
                errors.append(_finding(endpoint_name, "unconnected required port", net.logical_id, None))

    for net in graph.nets:
        kinds = {endpoint: _port_kind(endpoint, observed_components) for endpoint in net.endpoints}
        if any(not _matches_namespace(net.kind, kind) for kind in kinds.values()):
            errors.append(_finding(None, "net namespace mismatch", net.kind, kinds))


def _compare_labels(blueprint: LccBlueprint, graph: ProjectGraph, errors: list[dict[str, Any]]) -> None:
    expected_labels = sorted({net.label for net in blueprint.nets if net.kind == "data" and net.label})
    data_label_counts = Counter(label.text for label in graph.labels if label.kind == "data")
    for label in expected_labels:
        count = data_label_counts[label]
        if count == 0:
            errors.append(_finding(label, "missing data label", 1, 0))
        elif count > 1:
            errors.append(_finding(label, "duplicate data label", 1, count))


def validate_project_graph(
    graph: ProjectGraph,
    blueprint: LccBlueprint | Mapping[str, Any],
    catalog: LccCatalog | Mapping[str, Any] | None = None,
    *,
    expected_project_name: str | None = None,
    expected_pscad_version: str | None = None,
    raise_on_error: bool = False,
) -> dict[str, Any]:
    """Compare a parsed PSCX graph against the exact blueprint-owned LCC topology."""

    parsed_blueprint = _as_blueprint(blueprint)
    parsed_catalog = _as_catalog(catalog)
    errors: list[dict[str, Any]] = []

    expected_version = expected_pscad_version or parsed_blueprint.settings.get("pscad_version")
    if isinstance(expected_version, str) and graph.pscad_version != expected_version:
        errors.append(
            _finding(
                None,
                "project version mismatch",
                expected_version,
                graph.pscad_version,
            )
        )
    if expected_project_name is not None and graph.project_name != expected_project_name:
        errors.append(
            _finding(
                None,
                "project identity mismatch",
                expected_project_name,
                graph.project_name,
            )
        )

    expected_components = {component.logical_id: component for component in parsed_blueprint.components}
    observed_components, duplicate_errors = _component_map(graph.components)
    errors.extend(duplicate_errors)

    for logical_id, expected in expected_components.items():
        _compare_catalog_contracts(expected, parsed_catalog, errors)
        observed = observed_components.get(logical_id)
        if observed is None:
            errors.append(_finding(logical_id, "missing component", expected.to_dict(), None))
            continue
        _compare_component(expected, observed, errors)

    for logical_id, observed in observed_components.items():
        if logical_id not in expected_components:
            errors.append(_finding(logical_id, "unexpected component", None, observed.to_dict()))

    _compare_nets(parsed_blueprint, graph, observed_components, errors)
    _compare_labels(parsed_blueprint, graph, errors)

    sorted_errors = _sort_findings(errors)
    result = {
        "valid": not sorted_errors,
        "blueprint": parsed_blueprint.name,
        "components": {"expected": len(parsed_blueprint.components), "observed": len(graph.components)},
        "nets": {"expected": len(parsed_blueprint.nets), "observed": len(graph.nets)},
        "errors": sorted_errors,
        "warnings": [],
    }
    if raise_on_error and sorted_errors:
        raise _backend_error("Generated LCC topology does not match the blueprint.", _PROJECT_OPERATION, sorted_errors, blueprint=parsed_blueprint.name)
    return result


def validate_parametric_topology_contract(
    blueprint: Mapping[str, Any],
    audit_roles: Mapping[str, Any] | Any,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate an audited template against one exact logical topology asset."""

    operation = "validate_parametric_lcc_topology"
    catalog_value = load_parametric_catalog() if catalog is None else catalog
    try:
        if not isinstance(blueprint, Mapping) or not isinstance(blueprint.get("name"), str):
            raise BackendError("LCC_BLUEPRINT_INVALID", "Parametric blueprint must be an identified object.", "hvdc", operation)
        validated = validate_parametric_blueprint_asset(dict(blueprint), blueprint["name"], catalog_value)
    except BackendError as error:
        if error.code == "LCC_BLUEPRINT_INVALID":
            raise
        raise BackendError(
            "LCC_BLUEPRINT_INVALID",
            "Parametric blueprint does not match its versioned topology contract.",
            "hvdc",
            operation,
            {"reason": error.code},
        ) from error

    if hasattr(audit_roles, "compatible") and getattr(audit_roles, "compatible") is not True:
        raise BackendError("LCC_PROJECT_INVALID", "The template audit is not compatible.", "hvdc", operation)
    observed = getattr(audit_roles, "roles", audit_roles)
    if not isinstance(observed, Mapping):
        raise BackendError("LCC_PROJECT_INVALID", "Template audit roles must be an object.", "hvdc", operation)
    expected_roles = set(validated["template_roles"])
    if set(observed) != expected_roles:
        raise BackendError(
            "LCC_PROJECT_INVALID",
            "Template audit roles do not exactly match the blueprint.",
            "hvdc",
            operation,
            {"missing": sorted(expected_roles - set(observed)), "unexpected": sorted(set(observed) - expected_roles)},
        )

    component_map = {
        component["template_role"]: component
        for component in validated["components"]
        if component["kind"] == "template_role"
    }
    for role in sorted(expected_roles):
        record = observed[role]
        if not isinstance(record, Mapping):
            raise BackendError("LCC_PROJECT_INVALID", "A template audit role is not an object.", "hvdc", operation, {"role": role})
        evidence = record.get("evidence")
        observed_contract = record.get("validated_contract")
        if observed_contract is None and isinstance(evidence, Mapping):
            observed_contract = evidence.get("validated_contract")
        expected_contract = component_map[role]["contract_identity"]
        expected_discriminator = component_map[role].get("discriminator")
        if observed_contract != expected_contract:
            raise BackendError("LCC_PROJECT_INVALID", "A template audit role has the wrong catalog contract.", "hvdc", operation, {"role": role})
        definition = record.get("definition")
        template_contracts = catalog_value.get("template_role_contracts", {})
        if role == "earth_electrode":
            expected_definition = template_contracts.get("earth_electrode", {}).get("ground_definition")
            definition_matches = definition == expected_definition
        else:
            pole_contracts = template_contracts.get("pole_definitions", {})
            family = "rectifier" if role.startswith("rectifier") else "inverter"
            local_name = pole_contracts.get(family, {}).get("local_name")
            definition_matches = (
                isinstance(definition, str)
                and isinstance(local_name, str)
                and ":" in definition
                and definition.rsplit(":", 1)[1] == local_name
            )
        if not definition_matches:
            raise BackendError("LCC_PROJECT_INVALID", "A template audit role has the wrong exact definition.", "hvdc", operation, {"role": role})
        if expected_discriminator is not None and record.get("discriminator") != expected_discriminator:
            raise BackendError("LCC_PROJECT_INVALID", "A pole discriminator does not match the blueprint role.", "hvdc", operation, {"role": role})

    return {
        "valid": True,
        "blueprint": validated["name"],
        "template_roles": sorted(expected_roles),
        "nets": sorted(item["logical_id"] for item in validated["nets"]),
        "outputs": sorted(item["name"] for item in validated["outputs"]),
    }


def _name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _attr(element: ET.Element, *names: str) -> str | None:
    wanted = {name.casefold() for name in names}
    for key, value in element.attrib.items():
        if key.casefold() in wanted:
            return value
    return None


def _text(value: str | None) -> str:
    return (value or "").strip()


def _int_attr(element: ET.Element, names: tuple[str, ...], default: int = 1) -> int | None:
    value = _attr(element, *names)
    if value is None or not value.strip():
        return default
    try:
        return int(value.strip())
    except ValueError:
        return None


def _definition_map(root: ET.Element) -> dict[str, tuple[ET.Element, ...]]:
    definitions: dict[str, list[ET.Element]] = {}
    for element in root.iter():
        if _name(element.tag) != "definition":
            continue
        name = _text(_attr(element, "name", "id", "scoped_name"))
        if name:
            definitions.setdefault(name, []).append(element)
    return {name: tuple(elements) for name, elements in definitions.items()}


def _ports(definition: ET.Element) -> dict[str, tuple[ET.Element, ...]]:
    ports: dict[str, list[ET.Element]] = {}
    for element in definition.iter():
        if _name(element.tag) != "port":
            continue
        name = _text(_attr(element, "name", "id"))
        if name:
            ports.setdefault(name, []).append(element)
    return {name: tuple(elements) for name, elements in ports.items()}


def _check_definition_ports(definition_name: str, definition: ET.Element | None, errors: list[dict[str, Any]]) -> None:
    required = _REQUIRED_DEFINITION_PORTS[definition_name]
    if definition is None:
        errors.append(_finding(definition_name, "missing companion definition", required, None))
        return
    observed_ports = _ports(definition)
    observed_names = tuple(sorted(observed_ports))
    if tuple(sorted(required)) != observed_names:
        errors.append(_finding(definition_name, "external port mismatch", sorted(required), observed_names))
    for port_name, records in sorted(observed_ports.items()):
        if len(records) > 1:
            errors.append(_finding(f"{definition_name}:{port_name}", "duplicate external port", 1, len(records)))
    for gate in observed_ports.get("GATES", ()):
        if _int_attr(gate, ("dimension", "dim")) != 12:
            errors.append(
                _finding(
                    f"{definition_name}:GATES",
                    "external gate dimension mismatch",
                    12,
                    _attr(gate, "dimension", "dim"),
                )
            )


def _bridge_group_count(definition: ET.Element) -> int:
    count = 0
    for element in definition.iter():
        tag = _name(element.tag)
        role = " ".join(_text(_attr(element, name)).casefold() for name in ("type", "role", "class", "classid"))
        if tag in {"six_pulse_group", "sixpulsegroup"} or ("six" in role and "pulse" in role):
            count += 1
    return count


def _bridge_valve_count(definition: ET.Element) -> int:
    count = 0
    for element in definition.iter():
        tag = _name(element.tag)
        role = " ".join(_text(_attr(element, name)).casefold() for name in ("type", "role", "class", "classid", "definition", "defn"))
        if tag == "valve" or "valve" in role:
            count += 1
    return count


def _bridge_valves(definition: ET.Element) -> tuple[ET.Element, ...]:
    return tuple(element for element in definition.iter() if _name(element.tag) == "valve")


def _check_bridge_valves(definition: ET.Element, errors: list[dict[str, Any]]) -> None:
    logical_id = "cigre_lcc_v1:LCC12PulseBridge"
    valves = _bridge_valves(definition)
    observed_ids = [_text(_attr(valve, "id", "name")) for valve in valves]
    expected_ids = list(_EXPECTED_VALVE_GROUPS)
    if sorted(observed_ids) != sorted(expected_ids):
        errors.append(_finding(logical_id, "bridge valve identity mismatch", expected_ids, sorted(observed_ids)))

    group_counts: Counter[str] = Counter()
    for valve in valves:
        valve_id = _text(_attr(valve, "id", "name"))
        expected_group = _EXPECTED_VALVE_GROUPS.get(valve_id)
        observed_group = _text(_attr(valve, "group", "group_name"))
        group_counts[observed_group] += 1
        if expected_group is not None and observed_group != expected_group:
            errors.append(_finding(f"{logical_id}:{valve_id}", "bridge valve group mismatch", expected_group, observed_group))
        observed_definition = _text(_attr(valve, "definition", "scoped_name", "master"))
        if observed_definition != "master:thyristor_valve":
            errors.append(
                _finding(
                    f"{logical_id}:{valve_id}",
                    "bridge valve definition mismatch",
                    "master:thyristor_valve",
                    observed_definition,
                )
            )
    expected_counts = Counter({"upper": 6, "lower": 6})
    if group_counts != expected_counts:
        errors.append(_finding(logical_id, "bridge valve group count mismatch", dict(expected_counts), dict(group_counts)))


def _check_bridge_groups(definition: ET.Element, errors: list[dict[str, Any]]) -> None:
    logical_id = "cigre_lcc_v1:LCC12PulseBridge"
    groups = tuple(
        element
        for element in definition.iter()
        if _name(element.tag) in {"six_pulse_group", "sixpulsegroup"}
    )
    observed = Counter(_text(_attr(group, "name", "id")) for group in groups)
    expected = Counter({"upper": 1, "lower": 1})
    if observed != expected:
        errors.append(_finding(logical_id, "bridge six-pulse group identity mismatch", dict(expected), dict(observed)))


def _check_control_contract(
    definition_name: str,
    definition: ET.Element | None,
    errors: list[dict[str, Any]],
) -> None:
    if definition is None:
        return
    expected = _CONTROL_CONTRACTS[definition_name]
    blocks = tuple(element for element in definition.iter() if _name(element.tag) == "control_block")
    if len(blocks) != 1:
        errors.append(_finding(definition_name, "control block count mismatch", 1, len(blocks)))
        return
    observed = {
        "definition": _text(_attr(blocks[0], "definition", "scoped_name", "master")),
        "role": _text(_attr(blocks[0], "role", "control_role")),
    }
    if observed != expected:
        errors.append(_finding(definition_name, "control block contract mismatch", expected, observed))


def _has_common_dc_series_path(definition: ET.Element) -> bool:
    for element in definition.iter():
        tag = _name(element.tag)
        role = " ".join(_text(_attr(element, name)).casefold() for name in ("type", "role", "name", "class", "classid"))
        common = _text(_attr(element, "common")).casefold()
        if ("dc_series_path" in tag or ("dc" in role and "series" in role)) and common in {"true", "1", "yes"}:
            return True
    return False


def _gate_interface_dimension(definition: ET.Element) -> int | None:
    for element in definition.iter():
        tag = _name(element.tag)
        role = " ".join(_text(_attr(element, name)).casefold() for name in ("type", "role", "name", "class", "classid"))
        if tag == "gate_interface" or ("gate" in role and "interface" in role):
            return _int_attr(element, ("dimension", "dim"), default=1)
    return None


def _ac_groups_separated(definition: ET.Element) -> bool:
    ports = _ports(definition)
    y_groups = {
        _text(_attr(port, "group")).casefold()
        for name in ("ACY_A", "ACY_B", "ACY_C")
        for port in ports.get(name, ())
    }
    d_groups = {
        _text(_attr(port, "group")).casefold()
        for name in ("ACD_A", "ACD_B", "ACD_C")
        for port in ports.get(name, ())
    }
    if not y_groups or not d_groups:
        return False
    return y_groups.isdisjoint(d_groups)


def _check_bridge_internal(definition: ET.Element | None, errors: list[dict[str, Any]]) -> None:
    logical_id = "cigre_lcc_v1:LCC12PulseBridge"
    if definition is None:
        return
    group_count = _bridge_group_count(definition)
    if group_count != 2:
        errors.append(_finding(logical_id, "bridge six-pulse group count mismatch", 2, group_count))
    valve_count = _bridge_valve_count(definition)
    if valve_count != 12:
        errors.append(_finding(logical_id, "bridge valve count mismatch", 12, valve_count))
    _check_bridge_groups(definition, errors)
    _check_bridge_valves(definition, errors)
    if not _ac_groups_separated(definition):
        errors.append(_finding(logical_id, "bridge AC port groups are not separated", ("ACY", "ACD"), None))
    if not _has_common_dc_series_path(definition):
        errors.append(_finding(logical_id, "bridge DC series path missing", "common", None))
    gate_dimension = _gate_interface_dimension(definition)
    if gate_dimension != 12:
        errors.append(_finding(logical_id, "bridge gate interface dimension mismatch", 12, gate_dimension))


def validate_companion_library(
    path: str | Path,
    *,
    raise_on_error: bool = False,
) -> dict[str, Any]:
    """Validate the synthetic CIGRE LCC companion-library structure."""

    library_path = Path(path).expanduser().resolve()
    errors: list[dict[str, Any]] = []
    try:
        root = ET.parse(library_path).getroot()
    except (OSError, ET.ParseError) as error:
        errors.append(_finding(str(library_path), "companion library parse failure", None, str(error)))
        sorted_errors = _sort_findings(errors)
        if raise_on_error:
            raise _backend_error("Unable to validate LCC companion library.", _LIBRARY_OPERATION, sorted_errors, path=str(library_path)) from error
        return {"valid": False, "errors": sorted_errors, "warnings": []}

    definitions = _definition_map(root)
    expected_definition_names = set(_REQUIRED_DEFINITION_PORTS)
    observed_custom_definition_names = {
        name for name in definitions if name.startswith("cigre_lcc_v1:")
    }
    for definition_name, records in sorted(definitions.items()):
        if definition_name.startswith("cigre_lcc_v1:") and len(records) > 1:
            errors.append(_finding(definition_name, "duplicate companion definition", 1, len(records)))
    for definition_name in sorted(observed_custom_definition_names - expected_definition_names):
        errors.append(
            _finding(
                definition_name,
                "unexpected companion definition",
                sorted(expected_definition_names),
                sorted(observed_custom_definition_names),
            )
        )
    for definition_name in _REQUIRED_DEFINITION_PORTS:
        records = definitions.get(definition_name, ())
        if not records:
            _check_definition_ports(definition_name, None, errors)
        else:
            for definition in records:
                _check_definition_ports(definition_name, definition, errors)
    bridge_records = definitions.get("cigre_lcc_v1:LCC12PulseBridge", ())
    for definition in bridge_records:
        _check_bridge_internal(definition, errors)
    for definition_name in _CONTROL_CONTRACTS:
        records = definitions.get(definition_name, ())
        for definition in records:
            _check_control_contract(definition_name, definition, errors)

    sorted_errors = _sort_findings(errors)
    result = {"valid": not sorted_errors, "errors": sorted_errors, "warnings": []}
    if raise_on_error and sorted_errors:
        raise _backend_error("LCC companion library does not match the required structure.", _LIBRARY_OPERATION, sorted_errors, path=str(library_path))
    return result


__all__ = ["validate_project_graph", "validate_companion_library", "validate_parametric_topology_contract"]
