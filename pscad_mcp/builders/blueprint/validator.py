"""Independent persisted-graph, source, message, and output validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping
import xml.etree.ElementTree as ET

from ...core.backend.base import BackendError
from .acceptance import evaluate_acceptance
from .assets import hash_tree, manifest_hash
from .journal import write_json_atomic
from .models import BlueprintPlan
from .output import discover_output_dataset


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "blueprint", "validate_pscad_project_build", details)


def _integer(value: str | None, field: str) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise _error("BLUEPRINT_PROJECT_INVALID", f"Persisted component {field} is not an integer.") from error


def _xml_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _xml_attr(element: ET.Element, *names: str) -> str | None:
    wanted = {name.casefold() for name in names}
    return next((value for key, value in element.attrib.items() if key.casefold() in wanted), None)


def _component_parameters(element: ET.Element) -> dict[str, str]:
    parameters: dict[str, str] = {}
    for child in element.iter():
        if child is element or _xml_name(child.tag) not in {"param", "parameter"}:
            continue
        name = _xml_attr(child, "name", "key")
        if name:
            value = _xml_attr(child, "value")
            parameters[name] = (value if value is not None else child.text or "").strip()
    return parameters


def _main_scope(root: ET.Element) -> ET.Element:
    candidates = [
        element
        for element in root.iter()
        if _xml_name(element.tag) in {"definition", "canvas", "schematic"}
        and (_xml_attr(element, "name", "id") or "").casefold() == "main"
    ]
    if not candidates:
        raise _error("BLUEPRINT_PROJECT_INVALID", "Persisted PSCX has no Main definition.")
    definition = candidates[0]
    schematic = next(
        (element for element in definition.iter() if element is not definition and _xml_name(element.tag) in {"schematic", "canvas"}),
        None,
    )
    return schematic if schematic is not None else definition


def inspect_project_file(path: str | Path) -> dict[str, Any]:
    project_path = Path(path).expanduser().resolve()
    if not project_path.is_file() or project_path.is_symlink() or project_path.suffix.casefold() != ".pscx":
        raise _error("BLUEPRINT_PROJECT_INVALID", "Persisted project must be a regular PSCX file.", path=str(project_path))
    try:
        root = ET.parse(project_path).getroot()
    except (OSError, ET.ParseError) as error:
        raise _error("BLUEPRINT_PROJECT_INVALID", "Persisted PSCX could not be parsed.", path=str(project_path)) from error
    scope = _main_scope(root)
    component_elements = [
        element
        for element in scope.iter()
        if _xml_name(element.tag) == "component"
        or (
            _xml_name(element.tag) == "user"
            and (_xml_attr(element, "classid", "class") or "").casefold() in {"usercmp", "component"}
        )
    ]
    components: list[dict[str, Any]] = []
    for component in component_elements:
        parameters = _component_parameters(component)
        ports = []
        for port in component.iter():
            if _xml_name(port.tag) != "port":
                continue
            dimension = _xml_attr(port, "dimension", "dim")
            ports.append(
                {
                    "name": _xml_attr(port, "name", "id"),
                    "x": _integer(_xml_attr(port, "x", "left"), "port x"),
                    "y": _integer(_xml_attr(port, "y", "top"), "port y"),
                    "kind": _xml_attr(port, "kind", "type", "model"),
                    "dimension": _integer(dimension, "port dimension") if dimension is not None else None,
                }
            )
        component_id = _integer(_xml_attr(component, "id"), "id")
        logical_id = (
            _xml_attr(component, "logical_id", "logical", "name")
            or parameters.get("LogicalId")
            or parameters.get("LOGICAL_ID")
            or str(component_id)
        )
        components.append(
            {
                "id": component_id,
                "logical_id": logical_id,
                "definition": _xml_attr(component, "definition", "defn", "type"),
                "canvas": "Main",
                "location": [
                    _integer(_xml_attr(component, "x", "left"), "x"),
                    _integer(_xml_attr(component, "y", "top"), "y"),
                ],
                "orientation": _integer(_xml_attr(component, "orientation", "orient", "rotation", "angle") or "0", "orientation"),
                "parameters": parameters,
                "ports": ports,
            }
        )
    components.sort(key=lambda item: item["id"])
    wires: list[dict[str, Any]] = []
    for wire in scope.iter():
        if _xml_name(wire.tag) != "wire":
            continue
        origin_x = _integer(_xml_attr(wire, "x", "left") or "0", "wire x")
        origin_y = _integer(_xml_attr(wire, "y", "top") or "0", "wire y")
        vertices = [
            [
                _integer(_xml_attr(vertex, "x", "left"), "wire vertex x") + origin_x,
                _integer(_xml_attr(vertex, "y", "top"), "wire vertex y") + origin_y,
            ]
            for vertex in wire.iter()
            if vertex is not wire and _xml_name(vertex.tag) in {"vertex", "point", "node"}
        ]
        if len(vertices) >= 2:
            wire_id = _xml_attr(wire, "id")
            try:
                normalized_wire_id: int | str | None = int(wire_id) if wire_id is not None else None
            except ValueError:
                normalized_wire_id = wire_id
            wires.append(
                {
                    "id": normalized_wire_id,
                    "canvas": "Main",
                    "vertices": vertices,
                }
            )
    settings: dict[str, str] = {}
    for container in root.iter():
        if _xml_name(container.tag) == "paramlist" and (_xml_attr(container, "name") or "").casefold() == "settings":
            settings.update(_component_parameters(container))
        elif _xml_name(container.tag) == "project_settings":
            for setting in container:
                name = _xml_attr(setting, "name", "key")
                if name:
                    settings[name] = (_xml_attr(setting, "value") or setting.text or "").strip()
    connections = [
        {
            "from": {"logical_id": _xml_attr(item, "from_logical"), "port": _xml_attr(item, "from_port")},
            "to": {"logical_id": _xml_attr(item, "to_logical"), "port": _xml_attr(item, "to_port")},
            "canvas": _xml_attr(item, "canvas") or "Main",
        }
        for item in scope.iter()
        if _xml_name(item.tag) == "port_connection"
    ]
    identifiers = [component["logical_id"] for component in components]
    if len(set(identifiers)) != len(identifiers):
        raise _error("BLUEPRINT_PROJECT_INVALID", "Persisted logical component IDs are not unique.")
    return {
        "project_name": _xml_attr(root, "name", "project_name") or project_path.stem,
        "pscad_version": _xml_attr(root, "version", "pscad_version"),
        "components": components,
        "wires": wires,
        "connections": connections,
        "project_settings": settings,
    }


def _project_path(plan: BlueprintPlan, staging: Path) -> Path:
    source_root = Path(plan.source_path).resolve()
    try:
        relative = Path(plan.source_entry_point).resolve().relative_to(source_root)
    except ValueError as error:
        raise _error("BLUEPRINT_PROJECT_INVALID", "Planned source entry point escapes its package.") from error
    candidate = (staging / relative.parent / f"{plan.target_name}.pscx").resolve()
    if staging not in candidate.parents or not candidate.is_file() or candidate.is_symlink():
        raise _error(
            "BLUEPRINT_PROJECT_INVALID",
            "The planned renamed PSCX entry point is missing or unsafe.",
            path=str(candidate),
        )
    return candidate


def _component_index(
    graph: Mapping[str, Any],
    runtime_bindings: Mapping[str, int],
) -> dict[str, Mapping[str, Any]]:
    components = graph.get("components")
    if not isinstance(components, list):
        raise _error("BLUEPRINT_PROJECT_INVALID", "Project inspection did not return a component array.")
    result: dict[str, Mapping[str, Any]] = {}
    for component in components:
        if not isinstance(component, Mapping) or not isinstance(component.get("logical_id"), str):
            raise _error("BLUEPRINT_PROJECT_INVALID", "Project inspection returned an invalid component.")
        logical_id = component["logical_id"]
        if logical_id in result:
            raise _error("BLUEPRINT_PROJECT_INVALID", "Project inspection returned duplicate logical IDs.", logical_id=logical_id)
        result[logical_id] = component
    by_id = {component.get("id"): component for component in components if isinstance(component, Mapping)}
    for logical_id, component_id in runtime_bindings.items():
        component = by_id.get(component_id)
        if component is None:
            raise _error(
                "BLUEPRINT_PROJECT_INVALID",
                "A runtime logical binding is absent from persisted PSCX evidence.",
                logical_id=logical_id,
                component_id=component_id,
            )
        existing = result.get(logical_id)
        if existing is not None and existing is not component:
            raise _error("BLUEPRINT_PROJECT_INVALID", "A runtime logical binding is ambiguous.", logical_id=logical_id)
        result[logical_id] = component
    return result


def _runtime_evidence(staging: Path) -> tuple[dict[str, int], dict[str, Mapping[str, Any]]]:
    path = staging / "evidence" / "runtime-bindings.json"
    if not path.exists():
        return {}, {}
    if not path.is_file() or path.is_symlink():
        raise _error("BLUEPRINT_PROJECT_INVALID", "Runtime binding evidence is unsafe.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _error("BLUEPRINT_PROJECT_INVALID", "Runtime binding evidence is unreadable.") from error
    bindings = value.get("component_bindings") if isinstance(value, Mapping) else None
    if not isinstance(bindings, Mapping) or any(
        not isinstance(key, str) or not isinstance(item, int) or isinstance(item, bool)
        for key, item in bindings.items()
    ):
        raise _error("BLUEPRINT_PROJECT_INVALID", "Runtime binding evidence is invalid.")
    readbacks = value.get("operation_readbacks", {}) if isinstance(value, Mapping) else None
    if not isinstance(readbacks, Mapping) or any(
        not isinstance(key, str) or not isinstance(item, Mapping)
        for key, item in readbacks.items()
    ):
        raise _error("BLUEPRINT_PROJECT_INVALID", "Runtime operation read-back evidence is invalid.")
    return dict(bindings), {str(key): dict(item) for key, item in readbacks.items()}


def _structure_checks(plan: BlueprintPlan, components: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for requirement in plan.blueprint.acceptance["required_structure"]:
        logical_id = requirement.get("logical_id")
        observed = components.get(logical_id)
        expected_definition = requirement.get("definition")
        expected_canvas = requirement.get("canvas")
        passed = bool(
            observed is not None
            and (expected_definition is None or observed.get("definition") == expected_definition)
            and (expected_canvas is None or observed.get("canvas") == expected_canvas)
        )
        checks.append(
            {
                "logical_id": logical_id,
                "expected_definition": expected_definition,
                "observed_definition": observed.get("definition") if observed else None,
                "expected_canvas": expected_canvas,
                "observed_canvas": observed.get("canvas") if observed else None,
                "passed": passed,
            }
        )
    return checks


def _parameter_checks(plan: BlueprintPlan, components: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for requirement in plan.blueprint.acceptance["required_parameters"]:
        logical_id = requirement.get("logical_id")
        name = requirement.get("name")
        expected = requirement.get("value")
        component = components.get(logical_id)
        parameters = component.get("parameters") if component is not None else None
        observed = parameters.get(name) if isinstance(parameters, Mapping) else None
        passed = observed == expected or (observed is not None and str(observed) == str(expected))
        checks.append({"logical_id": logical_id, "name": name, "expected": expected, "observed": observed, "passed": passed})
    return checks


def _equivalent(expected: Any, observed: Any) -> bool:
    return expected == observed or (observed is not None and str(expected) == str(observed))


def _operation_checks(
    plan: BlueprintPlan,
    graph: Mapping[str, Any],
    components: Mapping[str, Mapping[str, Any]],
    dataset: Mapping[str, Any] | None,
    operation_readbacks: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    wires = graph.get("wires") if isinstance(graph.get("wires"), list) else []
    connections = graph.get("connections") if isinstance(graph.get("connections"), list) else []
    settings = graph.get("project_settings") if isinstance(graph.get("project_settings"), Mapping) else {}
    channels = dataset.get("channels") if isinstance(dataset, Mapping) and isinstance(dataset.get("channels"), Mapping) else {}
    checks: list[dict[str, Any]] = []
    for operation_index, operation in enumerate(plan.operations):
        arguments = operation.arguments
        expected: Any = None
        observed: Any = None
        passed = False
        logical_id = arguments.get("logical_id") if operation.kind in {"clone_component", "create_component"} else operation.target
        component = components.get(logical_id) if isinstance(logical_id, str) else None
        later_operations = plan.operations[operation_index + 1 :]
        location_superseded = any(
            later.kind == "set_component_location" and later.target == logical_id
            for later in later_operations
        )
        if operation.kind in {"clone_component", "create_component"}:
            expected = {
                "logical_id": logical_id,
                "definition": arguments.get("expected_definition", arguments.get("definition")),
                "location": list(arguments["location"]),
            }
            if operation.kind == "create_component":
                expected["orientation"] = int(arguments.get("orientation", 0))
                expected["parameters"] = dict(arguments.get("parameters", {}))
            observed = component
            passed = bool(
                component is not None
                and (expected["definition"] is None or component.get("definition") == expected["definition"])
                and (location_superseded or component.get("location") == expected["location"])
                and ("orientation" not in expected or component.get("orientation") == expected["orientation"])
                and (
                    "parameters" not in expected
                    or all(_equivalent(value, component.get("parameters", {}).get(name)) for name, value in expected["parameters"].items())
                )
            )
        elif operation.kind == "set_component_location":
            expected = list(arguments["location"])
            observed = component.get("location") if component else None
            passed = observed == expected
        elif operation.kind == "rotate_component":
            expected = int(arguments["expected_orientation"])
            observed = component.get("orientation") if component else None
            passed = observed == expected
        elif operation.kind == "set_component_parameters":
            expected = dict(arguments["parameters"])
            observed = component.get("parameters") if component else None
            passed = isinstance(observed, Mapping) and all(_equivalent(value, observed.get(name)) for name, value in expected.items())
        elif operation.kind == "create_wire":
            expected = {"canvas": arguments.get("canvas", "Main"), "vertices": [list(item) for item in arguments["vertices"]]}
            observed = next(
                (
                    wire
                    for wire in wires
                    if wire.get("canvas") == expected["canvas"] and wire.get("vertices") == expected["vertices"]
                ),
                None,
            )
            passed = observed is not None
        elif operation.kind == "connect_ports":
            expected = {
                "from": dict(arguments["from"]),
                "to": dict(arguments["to"]),
                "canvas": arguments.get("canvas", "Main"),
            }
            readback = operation_readbacks.get(operation.operation_id)
            first_component = components.get(expected["from"]["logical_id"])
            second_component = components.get(expected["to"]["logical_id"])
            first = readback.get("from") if isinstance(readback, Mapping) else None
            second = readback.get("to") if isinstance(readback, Mapping) else None
            first_ports = first_component.get("ports") if isinstance(first_component, Mapping) else None
            second_ports = second_component.get("ports") if isinstance(second_component, Mapping) else None
            first_port = next(
                (port for port in first_ports if isinstance(port, Mapping) and port.get("name") == expected["from"]["port"]),
                None,
            ) if isinstance(first_ports, list) else None
            second_port = next(
                (port for port in second_ports if isinstance(port, Mapping) and port.get("name") == expected["to"]["port"]),
                None,
            ) if isinstance(second_ports, list) else None
            if (
                isinstance(first_component, Mapping)
                and isinstance(second_component, Mapping)
                and isinstance(first, Mapping)
                and isinstance(second, Mapping)
                and isinstance(first_port, Mapping)
                and isinstance(second_port, Mapping)
                and first.get("component_id") == first_component.get("id")
                and second.get("component_id") == second_component.get("id")
                and first.get("port") == expected["from"]["port"]
                and second.get("port") == expected["to"]["port"]
                and all(
                    isinstance(endpoint.get(axis), int) and not isinstance(endpoint.get(axis), bool)
                    for endpoint in (first, second, first_port, second_port)
                    for axis in ("x", "y")
                )
                and all(first.get(axis) == first_port.get(axis) for axis in ("x", "y"))
                and all(second.get(axis) == second_port.get(axis) for axis in ("x", "y"))
            ):
                endpoints = [[first["x"], first["y"]], [second["x"], second["y"]]]
                reverse_endpoints = list(reversed(endpoints))
                wire_id = readback.get("wire_id")
                observed = next(
                    (
                        wire
                        for wire in wires
                        if wire.get("canvas") == expected["canvas"]
                        and wire.get("vertices") in (endpoints, reverse_endpoints)
                        and (wire_id is None or wire.get("id") == wire_id)
                    ),
                    None,
                )
            passed = observed is not None
        elif operation.kind == "set_project_settings":
            expected = dict(arguments["settings"])
            observed = dict(settings)
            passed = all(_equivalent(value, settings.get(name)) for name, value in expected.items())
        else:
            expected = {"path": arguments["path"], "units": arguments["units"], "call_id": arguments.get("call_id")}
            observed = channels.get(arguments["path"])
            passed = bool(
                isinstance(observed, Mapping)
                and observed.get("units") == arguments["units"]
                and (arguments.get("call_id") is None or observed.get("call_id") == arguments["call_id"])
            )
        checks.append(
            {
                "operation_id": operation.operation_id,
                "kind": operation.kind,
                "target": operation.target,
                "expected": expected,
                "observed": observed,
                "superseded_fields": ["location"] if location_superseded else [],
                "passed": passed,
            }
        )
    return checks


def _message_checks(plan: BlueprintPlan, messages: list[Mapping[str, Any]]) -> tuple[bool, list[dict[str, Any]]]:
    tokens = [str(item).casefold() for item in plan.blueprint.acceptance["blocking_messages"]]
    blocking = []
    for message in messages:
        severity = str(message.get("severity", "")).casefold()
        text = str(message.get("text", ""))
        if any(token == severity or token in text.casefold() for token in tokens):
            blocking.append({"severity": message.get("severity"), "text": text})
    return not blocking, blocking


def validate_staging(
    plan: BlueprintPlan,
    staging_path: str | Path,
    *,
    inspector: Callable[[Path], Mapping[str, Any]] = inspect_project_file,
    dataset: Mapping[str, Any] | None = None,
    messages: list[Mapping[str, Any]] | None = None,
    trusted_source_classes: set[str] | frozenset[str] | None = None,
    executor_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    del executor_result
    staging = Path(staging_path).expanduser().resolve()
    if not staging.is_dir() or staging.is_symlink():
        raise _error("BLUEPRINT_STAGING_INVALID", "Validation target must be a regular staging directory.", path=str(staging))
    project = _project_path(plan, staging)
    graph = inspector(project)
    project_identity_acceptance = graph.get("project_name") == plan.target_name
    runtime_bindings, operation_readbacks = _runtime_evidence(staging)
    components = _component_index(graph, runtime_bindings)
    structure_checks = _structure_checks(plan, components)
    parameter_checks = _parameter_checks(plan, components)
    structure_acceptance = all(check["passed"] for check in structure_checks)
    parameters_acceptance = all(check["passed"] for check in parameter_checks)
    message_evidence_available = messages is not None
    observed_messages = list(messages or [])
    messages_acceptance, blocking_messages = _message_checks(plan, observed_messages)
    messages_acceptance = bool(message_evidence_available and messages_acceptance)
    try:
        current_source = hash_tree(plan.source_path)
        source_integrity = current_source == dict(plan.source_manifest) and manifest_hash(current_source) == plan.source_package_hash
    except BackendError:
        source_integrity = False
    output_error: dict[str, Any] | None = None
    if dataset is None:
        try:
            dataset = discover_output_dataset(staging, expected_metadata=project.with_suffix(".inf"))
        except BackendError as error:
            output_error = error.to_dict()
            dataset = {"channels": {}}
    operation_checks = _operation_checks(plan, graph, components, dataset, operation_readbacks)
    operation_acceptance = all(check["passed"] for check in operation_checks)
    acceptance = evaluate_acceptance(
        plan.blueprint.acceptance,
        dataset,
        structure_acceptance=structure_acceptance,
        parameters_acceptance=parameters_acceptance,
        messages_acceptance=messages_acceptance,
        trusted_source_classes=trusted_source_classes,
    )
    run_through_acceptance = bool(project_identity_acceptance and source_integrity and operation_acceptance and acceptance["run_through_acceptance"])
    physical_acceptance = bool(project_identity_acceptance and source_integrity and operation_acceptance and acceptance["physical_acceptance"])
    report = {
        "plan_hash": plan.plan_hash,
        "source_integrity": source_integrity,
        "project_identity_acceptance": project_identity_acceptance,
        "structure_acceptance": acceptance["structure_acceptance"],
        "parameters_acceptance": acceptance["parameters_acceptance"],
        "operation_acceptance": operation_acceptance,
        "message_evidence_available": message_evidence_available,
        "messages_acceptance": acceptance["messages_acceptance"],
        "output_acceptance": acceptance["output_acceptance"],
        "run_through_acceptance": run_through_acceptance,
        "physical_acceptance": physical_acceptance,
        "valid": run_through_acceptance,
        "structure_checks": structure_checks,
        "parameter_checks": parameter_checks,
        "operation_checks": operation_checks,
        "blocking_messages": blocking_messages,
        "output_checks": acceptance["outputs"],
        "rules": acceptance["rules"],
        "output_error": output_error,
        "evidence": {"project": project.relative_to(staging).as_posix()},
    }
    return report


def write_validation_report(staging_path: str | Path, report: Mapping[str, Any]) -> Path:
    staging = Path(staging_path).expanduser().resolve()
    if not staging.is_dir() or staging.is_symlink():
        raise _error("BLUEPRINT_STAGING_INVALID", "Validation report target must be a staging directory.")
    destination = staging / "evidence" / "validation-report.json"
    return write_json_atomic(destination, report)
