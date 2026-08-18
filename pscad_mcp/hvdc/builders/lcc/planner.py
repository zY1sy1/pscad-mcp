"""Deterministic, side-effect-free expansion of the fixed LCC blueprint."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ....core.path_policy import PathPolicy, WorkspaceNotConfiguredError
from .assets import LccAssetSet, canonical_json
from .catalog import LccCatalog, LccDefinitionSpec, parse_catalog, require_definition, require_port
from .models import (
    LccAcceptanceCheck,
    LccBuildPlan,
    LccComponentSpec,
    LccNetSpec,
    LccPlanOperation,
)
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
    if final_path.exists() or raw_final.exists():
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
    component_map = {component.logical_id: component for component in blueprint.components}
    measurement_ids = {record.get("logical_id") for record in blueprint.measurements if isinstance(record, Mapping)}
    for output in blueprint.outputs:
        if output.measurement is not None and output.measurement not in measurement_ids:
            raise _error(
                "LCC_BLUEPRINT_INVALID",
                f"Output '{output.logical_id}' is not backed by a declared measurement.",
                output=output.logical_id,
                measurement=output.measurement,
            )
    for component in blueprint.components:
        definition = require_definition(catalog, component.definition)
        if component.definition not in inventory_definitions:
            raise _error(
                "LCC_DEFINITION_MISSING",
                f"Definition '{component.definition}' is missing from the live inventory.",
                definition=component.definition,
            )
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
    rectangles = _component_rectangles(blueprint.components, catalog)
    rectangle_items = list(rectangles.items())
    for index, (left_id, left_rect) in enumerate(rectangle_items):
        for right_id, right_rect in rectangle_items[index + 1 :]:
            if _rectangles_overlap(left_rect, right_rect):
                raise _error("LCC_LAYOUT_INVALID", "Blueprint components overlap.", left=left_id, right=right_id)
    for net in blueprint.nets:
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

