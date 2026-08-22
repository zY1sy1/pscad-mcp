"""Deterministic, side-effect-free expansion of the fixed LCC blueprint."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ....core.path_policy import PathPolicy, WorkspaceNotConfiguredError
from .assets import (
    LccAssetSet,
    canonical_json,
    load_parametric_catalog,
    validate_parametric_blueprint_asset,
)
from .catalog import LccCatalog, LccDefinitionSpec, parse_catalog, require_definition, require_port, validate_parameters
from .models import (
    LccAcceptanceCheck,
    LccBuildPlan,
    LccComponentSpec,
    LccNetSpec,
    LccPlanOperation,
)
from .parametric_models import DerivedParameterReport
from .routing import absolute_port, route_intersects_rectangles, validate_orthogonal_route


PHASES = (
    "materialize_library",
    "create_staging",
    "set_settings",
    "place_power",
    "place_control",
    "place_measurement",
    "verify_parameters",
    "connect_electrical",
    "connect_data",
    "create_outputs",
    "save_and_validate",
    "compile",
    "simulate",
    "accept",
    "publish",
)


@dataclass(frozen=True)
class LccPlanRequest:
    project_name: str
    folder: str | None = None
    simulation_duration_s: float | None = None
    blueprint: str = "cigre_lcc_monopole_v1"


def _error(code: str, message: str, **details: Any):
    from ....core.backend.base import BackendError

    return BackendError(code, message, "hvdc", "create_lcc_plan", details)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error("LCC_BLUEPRINT_INVALID", f"{field} must be a non-empty string.", field=field)
    return value.strip()


def _inventory_version(inventory: Any) -> str | None:
    if isinstance(inventory, LccCatalog):
        return inventory.pscad_version
    if isinstance(inventory, Mapping):
        value = inventory.get("pscad_version", inventory.get("version"))
        return value if isinstance(value, str) else None
    return None


def _inventory_definitions(inventory: Any) -> dict[str, set[str]]:
    if isinstance(inventory, LccCatalog):
        return {name: {port.name for port in definition.ports} for name, definition in inventory.definitions.items()}
    values: Any = inventory.get("definitions", {}) if isinstance(inventory, Mapping) else inventory
    definitions: dict[str, set[str]] = {}
    if isinstance(values, Mapping):
        items = values.items()
    elif isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
        items = []
        for item in values:
            if isinstance(item, str):
                items.append((item, {}))
            elif isinstance(item, Mapping):
                name = item.get("scoped_name", item.get("definition", item.get("name")))
                items.append((name, item))
    else:
        items = []
    for name, value in items:
        if not isinstance(name, str):
            continue
        ports_value = value.get("ports", ()) if isinstance(value, Mapping) else value
        ports: set[str] = set()
        if isinstance(ports_value, Mapping):
            ports = {port for port in ports_value if isinstance(port, str)}
        elif isinstance(ports_value, Sequence) and not isinstance(ports_value, (str, bytes, bytearray)):
            for port in ports_value:
                if isinstance(port, str):
                    ports.add(port)
                elif isinstance(port, Mapping) and isinstance(port.get("name"), str):
                    ports.add(port["name"])
        definitions[name] = ports
    return definitions


def _component_rectangles(components: Sequence[LccComponentSpec], catalog: LccCatalog) -> dict[str, tuple[int, int, int, int]]:
    rectangles: dict[str, tuple[int, int, int, int]] = {}
    for component in components:
        definition = require_definition(catalog, component.definition)
        if definition.bounding_box is None:
            continue
        left, top, right, bottom = definition.bounding_box
        x, y = component.location
        rectangles[component.logical_id] = (x + left, y + top, x + right, y + bottom)
    return rectangles


def _rectangles_overlap(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
    return max(left[0], right[0]) < min(left[2], right[2]) and max(left[1], right[1]) < min(left[3], right[3])


def _port_point(component: LccComponentSpec, port_name: str, catalog: LccCatalog) -> tuple[int, int]:
    definition = require_definition(catalog, component.definition)
    port = require_port(definition, port_name)
    return absolute_port(component.location, port.offset, component.orientation)


def _net_route(net: LccNetSpec, component_map: Mapping[str, LccComponentSpec], catalog: LccCatalog) -> tuple[tuple[int, int], ...]:
    points = tuple(_port_point(component_map[endpoint.component], endpoint.port, catalog) for endpoint in net.endpoints)
    if net.route is not None:
        route = validate_orthogonal_route(net.route.vertices)
        if route[0] != points[0] or route[-1] != points[-1]:
            raise _error(
                "LCC_LAYOUT_INVALID",
                f"Net '{net.logical_id}' route does not terminate at its catalog ports.",
                logical_id=net.logical_id,
                expected_start=list(points[0]),
                expected_end=list(points[-1]),
                observed_start=list(route[0]),
                observed_end=list(route[-1]),
            )
        return route
    if len(points) != 2:
        raise _error(
            "LCC_LAYOUT_INVALID",
            f"Net '{net.logical_id}' requires an explicit route for more than two endpoints.",
            logical_id=net.logical_id,
        )
    first, last = points
    if first[0] == last[0] or first[1] == last[1]:
        return validate_orthogonal_route(points)
    return validate_orthogonal_route((first, (last[0], first[1]), last))


def _acceptance_checks(asset_set: LccAssetSet) -> tuple[LccAcceptanceCheck, ...]:
    raw = asset_set.acceptance.get("checks", asset_set.acceptance.get("acceptance_checks", ()))
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise _error("LCC_BLUEPRINT_INVALID", "The acceptance contract checks must be an array.")
    checks: list[LccAcceptanceCheck] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise _error("LCC_BLUEPRINT_INVALID", "Acceptance checks must be objects.", index=index)
        required = item.get("required", True)
        if not isinstance(required, bool):
            raise _error("LCC_BLUEPRINT_INVALID", "Acceptance check required must be boolean.", index=index)
        window_value = item.get("comparison_window")
        window = None
        if window_value is not None:
            if not isinstance(window_value, Sequence) or len(window_value) != 2 or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in window_value):
                raise _error("LCC_BLUEPRINT_INVALID", "Acceptance comparison_window must contain two numbers.", index=index)
            window = (float(window_value[0]), float(window_value[1]))
        checks.append(
            LccAcceptanceCheck(
                name=_text(item.get("name", f"check_{index}"), f"acceptance.checks[{index}].name"),
                kind=_text(item.get("kind", "golden"), f"acceptance.checks[{index}].kind"),
                required=required,
                expected=dict(item.get("expected", {})) if isinstance(item.get("expected", {}), Mapping) else {},
                units=None if item.get("units") is None else _text(item["units"], f"acceptance.checks[{index}].units"),
                comparison_window=window,
                severity=None if item.get("severity") is None else _text(item["severity"], f"acceptance.checks[{index}].severity"),
                rationale=None if item.get("rationale") is None else _text(item["rationale"], f"acceptance.checks[{index}].rationale"),
            )
        )
    return tuple(checks)


def _resolve_paths(request: LccPlanRequest, workspace: str | Path | PathPolicy) -> tuple[Path, Path, str, float]:
    project_name = _text(request.project_name, "project_name")
    if any(separator in project_name for separator in ("/", "\\")) or project_name in {".", ".."}:
        raise _error("LCC_LAYOUT_INVALID", "project_name must be a single project identity.", project_name=project_name)
    filename = project_name if project_name.casefold().endswith(".pscx") else f"{project_name}.pscx"
    if isinstance(workspace, PathPolicy):
        policy = workspace
        if policy.workspace_root is None:
            raise _error("LCC_LAYOUT_INVALID", "A configured workspace is required for LCC planning.")
        workspace_root = policy.workspace_root
    else:
        workspace_root = Path(workspace).expanduser().resolve()
        policy = PathPolicy(workspace_root=str(workspace_root))
    try:
        folder = workspace_root if request.folder is None else policy.resolve(request.folder)
        final_path = policy.resolve_child(str(folder), filename, suffixes={".pscx"})
    except (WorkspaceNotConfiguredError, ValueError, OSError) as error:
        raise _error("LCC_LAYOUT_INVALID", str(error), project_name=project_name) from error
    raw_final = folder / project_name
    raw_target = folder / filename
    if final_path.exists() or raw_final.exists() or raw_target.is_symlink():
        raise _error(
            "LCC_BUILD_CONFLICT",
            "The planned final destination already exists.",
            target_path=str(final_path),
        )
    staging = workspace_root / ".pscad-mcp" / "lcc-builds" / f"{Path(filename).stem}.staging"
    default_duration = request_duration = None
    return final_path, staging, project_name, request_duration


def _duration(request: LccPlanRequest, asset_set: LccAssetSet) -> float:
    default = asset_set.blueprint.settings.get("simulation_duration_s")
    if isinstance(default, bool) or not isinstance(default, (int, float)) or default <= 0:
        raise _error("LCC_BLUEPRINT_INVALID", "The blueprint simulation duration is invalid.")
    value = default if request.simulation_duration_s is None else request.simulation_duration_s
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise _error("LCC_BLUEPRINT_INVALID", "simulation_duration_s must be positive.")
    if value < default:
        raise _error(
            "LCC_BLUEPRINT_INVALID",
            "simulation_duration_s cannot be shorter than the packaged default.",
            requested=value,
            minimum=default,
        )
    return float(value)


def _operation_kind(component: LccComponentSpec) -> str:
    role = (component.role or "").casefold()
    definition = component.definition.casefold()
    if role == "control" or "control" in definition:
        return "place_control"
    if role in {"measurement", "meter"} or "meter" in definition:
        return "place_measurement"
    return "place_power"


def create_parametric_topology_plan(
    blueprint: Mapping[str, Any],
    derived_report: DerivedParameterReport,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map derived values only through declared logical role bindings.

    This adapter is deliberately not an ``LccBuildPlan``: the reviewed PSCAD
    parameter-write bindings do not exist yet, so the result remains a
    deterministic, side-effect-free logical topology plan.
    """

    catalog_value = load_parametric_catalog() if catalog is None else catalog
    if not isinstance(blueprint, Mapping):
        raise _error("LCC_BLUEPRINT_INVALID", "Parametric blueprint must be an object.")
    name = blueprint.get("name")
    if not isinstance(name, str):
        raise _error("LCC_BLUEPRINT_INVALID", "Parametric blueprint identity is missing.")
    validated = validate_parametric_blueprint_asset(dict(blueprint), name, catalog_value)
    if not isinstance(derived_report, DerivedParameterReport) or not derived_report.feasible:
        raise _error("LCC_BLUEPRINT_INVALID", "A feasible DerivedParameterReport is required.")

    topology = validated["parameter_topology"]
    bindings = catalog_value.get("logical_parameter_bindings")
    if not isinstance(bindings, Mapping):
        raise _error("LCC_BLUEPRINT_INVALID", "Logical parameter bindings are missing from the catalog.")
    template_roles = set(validated["template_roles"])
    role_parameters: dict[str, dict[str, Any]] = {
        role: {} for role in validated["template_roles"]
    }
    unresolved: list[dict[str, Any]] = []
    observed_names: set[str] = set()
    for parameter in sorted(derived_report.parameters, key=lambda item: item.name):
        if parameter.name in observed_names:
            raise _error("LCC_BLUEPRINT_INVALID", "Derived parameter identities must be unique.", parameter=parameter.name)
        observed_names.add(parameter.name)
        declaration = bindings.get(parameter.name)
        if not isinstance(declaration, Mapping):
            raise _error("LCC_BLUEPRINT_INVALID", "A derived parameter has no explicit catalog binding.", parameter=parameter.name)
        roles_by_topology = declaration.get("roles_by_topology")
        roles = roles_by_topology.get(topology) if isinstance(roles_by_topology, Mapping) else None
        if (
            not isinstance(roles, list)
            or not roles
            or any(not isinstance(role, str) or role not in template_roles for role in roles)
            or parameter.units != declaration.get("units")
        ):
            raise _error("LCC_BLUEPRINT_INVALID", "A logical parameter binding does not match the topology or units.", parameter=parameter.name, topology=topology)
        logical_parameter = declaration.get("logical_parameter")
        template_parameter = declaration.get("template_parameter")
        for role in roles:
            role_parameters[role][parameter.name] = {
                "value": parameter.value,
                "units": parameter.units,
                "logical_parameter": logical_parameter,
                "template_parameter": template_parameter,
            }
        if declaration.get("binding_status") != "reviewed" or not isinstance(template_parameter, str) or not template_parameter:
            unresolved.append(
                {
                    "parameter": parameter.name,
                    "logical_parameter": logical_parameter,
                    "roles": list(roles),
                    "reason": "template_parameter_binding_unreviewed",
                }
            )

    payload = {
        "schema_version": 1,
        "identity": "lcc_parametric_topology_plan_v1",
        "blueprint": {
            "identity": name,
            "sha256": catalog_value["blueprint_hashes"][name],
            "catalog_identity": catalog_value["identity"],
            "provenance_identity": catalog_value["provenance_identity"],
        },
        "topology": topology,
        "derived_report": derived_report.to_dict(),
        "components": validated["components"],
        "nets": validated["nets"],
        "outputs": validated["outputs"],
        "role_parameters": role_parameters,
        "unresolved_bindings": unresolved,
        "executable": not unresolved,
    }
    return {**payload, "plan_hash": hashlib.sha256(canonical_json(payload)).hexdigest()}


def create_plan(
    request: LccPlanRequest,
    asset_set: LccAssetSet,
    inventory: Any,
    workspace: str | Path | PathPolicy,
) -> LccBuildPlan:
    """Expand a verified blueprint without creating files or touching PSCAD."""

    if not isinstance(request, LccPlanRequest):
        raise _error("LCC_BLUEPRINT_INVALID", "request must be an LccPlanRequest.")
    if request.blueprint != asset_set.name:
        raise _error(
            "LCC_BLUEPRINT_NOT_FOUND",
            f"Blueprint '{request.blueprint}' is not the loaded asset set.",
            blueprint=request.blueprint,
        )
    blueprint = asset_set.blueprint
    if blueprint.poles != 1:
        raise _error(
            "LCC_BLUEPRINT_UNSUPPORTED",
            "Version one supports only a single pole.",
            poles=blueprint.poles,
        )
    version = _inventory_version(inventory)
    if version != asset_set.pscad_version or version != "4.6.2":
        raise _error(
            "LCC_VERSION_UNSUPPORTED",
            "The planner requires PSCAD 4.6.2 inventory metadata.",
            observed_version=version,
            required_version="4.6.2",
        )
    duration = _duration(request, asset_set)
    final_path, staging_path, project_name, _ = _resolve_paths(request, workspace)
    catalog = parse_catalog(asset_set.catalog)
    if catalog.pscad_version != asset_set.pscad_version:
        raise _error(
            "LCC_VERSION_UNSUPPORTED",
            "The catalog version does not match the asset set.",
            catalog_version=catalog.pscad_version,
            asset_version=asset_set.pscad_version,
        )
    inventory_definitions = _inventory_definitions(inventory)
    normalized_components: list[LccComponentSpec] = []
    component_map = {component.logical_id: component for component in blueprint.components}
    measurement_map = {
        record.get("logical_id"): record
        for record in blueprint.measurements
        if isinstance(record, Mapping) and isinstance(record.get("logical_id"), str)
    }
    measurement_endpoints: dict[tuple[str, str], list[str]] = {}
    for measurement in blueprint.measurements:
        if not isinstance(measurement, Mapping):
            continue
        component_id = measurement.get("component")
        port_name = measurement.get("port")
        logical_id = measurement.get("logical_id")
        if all(isinstance(value, str) for value in (component_id, port_name, logical_id)):
            measurement_endpoints.setdefault((component_id, port_name), []).append(logical_id)
    for endpoint, logical_ids in sorted(measurement_endpoints.items()):
        if len(logical_ids) > 1:
            raise _error(
                "LCC_BLUEPRINT_INVALID",
                "Multiple measurements cannot share one component port without an explicit derived-signal contract.",
                endpoint=list(endpoint),
                measurements=sorted(logical_ids),
            )
    output_paths = [output.path for output in blueprint.outputs]
    if len(output_paths) != len(set(output_paths)):
        raise _error(
            "LCC_BLUEPRINT_INVALID",
            "Output selectors must be unique.",
            paths=output_paths,
        )
    for output in blueprint.outputs:
        if output.measurement is None or output.measurement not in measurement_map:
            raise _error(
                "LCC_BLUEPRINT_INVALID",
                f"Output '{output.logical_id}' is not backed by a declared measurement.",
                output=output.logical_id,
                measurement=output.measurement,
            )
        measurement = measurement_map[output.measurement]
        component_id = measurement.get("component")
        port_name = measurement.get("port")
        component = component_map.get(component_id) if isinstance(component_id, str) else None
        if component is None or not isinstance(port_name, str) or port_name not in component.ports:
            raise _error(
                "LCC_BLUEPRINT_INVALID",
                f"Output '{output.logical_id}' has an invalid measurement endpoint.",
                output=output.logical_id,
                measurement=output.measurement,
                component=component_id,
                port=port_name,
            )
        channels = measurement.get("channels", ())
        if output.path not in channels:
            raise _error(
                "LCC_BLUEPRINT_INVALID",
                f"Output '{output.logical_id}' is not declared by its measurement channel list.",
                output=output.logical_id,
                measurement=output.measurement,
                path=output.path,
            )
        port_contract = require_port(require_definition(catalog, component.definition), port_name)
        measurement_kind = measurement.get("kind")
        if measurement_kind == "electrical" and port_contract.kind != "electrical":
            raise _error(
                "LCC_PORT_MISMATCH",
                "Electrical measurements must bind to electrical ports.",
                output=output.logical_id,
                component=component_id,
                port=port_name,
            )
        if measurement_kind == "data" and port_contract.kind not in {"data", "signal"}:
            raise _error(
                "LCC_PORT_MISMATCH",
                "Data measurements must bind to data ports.",
                output=output.logical_id,
                component=component_id,
                port=port_name,
            )
    for component in blueprint.components:
        definition = require_definition(catalog, component.definition)
        if component.definition not in inventory_definitions:
            raise _error(
                "LCC_DEFINITION_MISSING",
                f"Definition '{component.definition}' is missing from the live inventory.",
                definition=component.definition,
            )
        normalized_parameters = validate_parameters(definition, dict(component.parameters))
        normalized_components.append(replace(component, parameters=normalized_parameters))
        for port_name in component.ports:
            port = require_port(definition, port_name)
            live_ports = inventory_definitions[component.definition]
            if port_name not in live_ports:
                raise _error(
                    "LCC_PORT_MISMATCH",
                    f"Port '{port_name}' is missing from the live definition inventory.",
                    definition=component.definition,
                    port=port_name,
                )
            contract = next((item for item in component.port_contracts if item.get("name") == port_name), {})
            if contract.get("kind") is not None and contract["kind"] != port.kind:
                raise _error("LCC_PORT_MISMATCH", "Blueprint port kind does not match catalog.", definition=component.definition, port=port_name)
            if contract.get("dimension") is not None and contract["dimension"] != port.dimension:
                raise _error("LCC_PORT_MISMATCH", "Blueprint port dimension does not match catalog.", definition=component.definition, port=port_name)
    blueprint = replace(blueprint, components=tuple(normalized_components))
    component_map = {component.logical_id: component for component in blueprint.components}
    rectangles = _component_rectangles(blueprint.components, catalog)
    rectangle_items = list(rectangles.items())
    for index, (left_id, left_rect) in enumerate(rectangle_items):
        for right_id, right_rect in rectangle_items[index + 1 :]:
            if _rectangles_overlap(left_rect, right_rect):
                raise _error("LCC_LAYOUT_INVALID", "Blueprint components overlap.", left=left_id, right=right_id)
    for net in blueprint.nets:
        if net.route is not None and net.route.policy not in {None, "orthogonal"}:
            raise _error(
                "LCC_LAYOUT_INVALID",
                "The requested route policy is not implemented by the deterministic planner.",
                net=net.logical_id,
                policy=net.route.policy,
                supported_policies=["orthogonal"],
            )
        route = _net_route(net, component_map, catalog)
        expected_kind = "electrical" if net.kind == "electrical" else "data"
        for endpoint in net.endpoints:
            component = component_map[endpoint.component]
            definition = require_definition(catalog, component.definition)
            port = require_port(definition, endpoint.port)
            if endpoint.kind is not None and endpoint.kind != port.kind:
                raise _error("LCC_PORT_MISMATCH", "Endpoint kind does not match catalog port.", net=net.logical_id, endpoint=f"{endpoint.component}:{endpoint.port}")
            if (expected_kind == "electrical" and port.kind != "electrical") or (expected_kind == "data" and port.kind not in {"data", "signal"}):
                raise _error("LCC_PORT_MISMATCH", "Net kind does not match catalog port.", net=net.logical_id, endpoint=f"{endpoint.component}:{endpoint.port}")
        excluded = {endpoint.component for endpoint in net.endpoints}
        route_intersects_rectangles(route, [rect for logical_id, rect in rectangle_items if logical_id not in excluded])

    settings = dict(blueprint.settings)
    settings["simulation_duration_s"] = duration
    checks = _acceptance_checks(asset_set)
    counters: defaultdict[str, int] = defaultdict(int)
    operations: list[LccPlanOperation] = []

    def add(phase: str, kind: str, target: str, arguments: Mapping[str, Any] | None = None) -> None:
        index = counters[phase]
        counters[phase] += 1
        operation_id = f"{phase}:{target}:{index:03d}"
        operations.append(
            LccPlanOperation(
                sequence=len(operations) + 1,
                kind=kind,
                target=target,
                arguments=dict(arguments or {}),
                operation_id=operation_id,
                phase=phase,
            )
        )

    add("materialize_library", "materialize_library", asset_set.companion_library, {"sha256": asset_set.hashes[asset_set.companion_library]})
    add("create_staging", "create_staging", project_name, {"target_path": str(final_path), "staging_path": str(staging_path)})
    add("set_settings", "set_project_settings", project_name, {"settings": settings})
    for component in blueprint.components:
        phase = _operation_kind(component)
        add(
            phase,
            "place_component",
            component.logical_id,
            {
                "definition": component.definition,
                "canvas": component.canvas,
                "location": list(component.location),
                "orientation": component.orientation,
                "parameters": dict(component.parameters),
                "ports": list(component.ports),
            },
        )
    for component in blueprint.components:
        add("verify_parameters", "verify_parameters", component.logical_id, {"parameters": dict(component.parameters)})
    for net in blueprint.nets:
        route = _net_route(net, component_map, catalog)
        phase = "connect_electrical" if net.kind == "electrical" else "connect_data"
        add(
            phase,
            "connect_net",
            net.logical_id,
            {
                "kind": net.kind,
                "endpoints": [f"{endpoint.component}:{endpoint.port}" for endpoint in net.endpoints],
                "vertices": [list(point) for point in route],
                "label": net.label,
            },
        )
    for output in blueprint.outputs:
        add("create_outputs", "create_output", output.logical_id, output.to_dict())
    add("save_and_validate", "save_and_validate", project_name, {})
    add("compile", "compile", project_name, {})
    add("simulate", "simulate", project_name, {"duration_s": duration})
    add("accept", "accept", project_name, {"required_checks": [check.name for check in checks]})
    add("publish", "publish", project_name, {"target_path": str(final_path)})
    payload = {
        "request": {
            "project_name": project_name,
            "folder": str(final_path.parent),
            "simulation_duration_s": duration,
            "blueprint": request.blueprint,
        },
        "target_path": str(final_path),
        "staging_path": str(staging_path),
        "pscad_version": asset_set.pscad_version,
        "asset_hashes": dict(asset_set.hashes),
        "catalog_identity": catalog.identity,
        "project_settings": settings,
        "operations": [operation.to_dict() for operation in operations],
        "acceptance_contract": [check.to_dict() for check in checks],
    }
    plan_hash = hashlib.sha256(canonical_json(payload)).hexdigest()
    return LccBuildPlan(
        blueprint=blueprint,
        operations=tuple(operations),
        plan_hash=plan_hash,
        acceptance_checks=checks,
        target_path=str(final_path),
        staging_path=str(staging_path),
        asset_hashes=dict(asset_set.hashes),
        pscad_version=asset_set.pscad_version,
        catalog_identity=catalog.identity,
        metadata=payload["request"],
    )
