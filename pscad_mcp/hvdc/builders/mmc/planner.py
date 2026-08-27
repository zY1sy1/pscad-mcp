"""Deterministic, side-effect-free expansion of the fixed MMC blueprint."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError
from ....core.path_policy import PathPolicy, WorkspaceNotConfiguredError
from ..common.records import freeze
from ..common.routing import absolute_port, route_intersects_rectangles, validate_orthogonal_route
from ..common.serialization import content_hash
from .catalog import MmcCatalog, MmcDefinitionSpec, parse_catalog, require_definition, require_port, validate_parameters
from .models import MmcAcceptanceCheck, MmcBlueprint, MmcBuildPlan, MmcComponentSpec, MmcNetSpec, MmcPlanOperation


PHASES = (
    "materialize_library",
    "create_staging",
    "set_settings",
    "place_power",
    "place_control",
    "place_arm",
    "create_phase_midpoint",
    "create_dc_terminal",
    "verify_parameters",
    "connect_electrical",
    "connect_data",
    "create_outputs",
    "save_and_validate",
    "compile",
    "startup_simulate",
    "forward_simulate",
    "reversal_simulate",
    "reverse_simulate",
    "accept",
    "publish",
)


@dataclass(frozen=True)
class MmcPlanRequest:
    project_name: str
    folder: str | None = None
    simulation_duration_s: float | None = None
    blueprint: str = "cigre_b4_p2p_avm_v1"


@dataclass(frozen=True)
class MmcAssetSet:
    name: str
    schema_version: int
    pscad_version: str
    companion_library: str
    blueprint: MmcBlueprint
    catalog: dict[str, Any]
    acceptance: dict[str, Any]
    golden: dict[str, Any]
    provenance: str
    hashes: dict[str, str]
    library_bytes: bytes
    files: dict[str, bytes]
    root: Path | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.catalog, MmcCatalog):
            object.__setattr__(self, "catalog", dict(self.catalog))
        object.__setattr__(self, "acceptance", dict(self.acceptance))
        object.__setattr__(self, "golden", dict(self.golden))
        object.__setattr__(self, "hashes", dict(self.hashes))
        object.__setattr__(self, "files", dict(self.files))


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", "create_mmc_plan", details)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error("MMC_BLUEPRINT_INVALID", f"{field} must be a non-empty string.", field=field)
    return value.strip()


def _inventory_version(inventory: Any) -> str | None:
    if isinstance(inventory, MmcCatalog):
        return inventory.pscad_version
    if isinstance(inventory, Mapping):
        value = inventory.get("pscad_version", inventory.get("version"))
        return value if isinstance(value, str) else None
    return None


def _inventory_definitions(inventory: Any) -> dict[str, dict[str, dict[str, Any]]]:
    if isinstance(inventory, MmcCatalog):
        return {
            name: {port.name: {"kind": port.kind, "dimension": port.dimension} for port in definition.ports}
            for name, definition in inventory.definitions.items()
        }
    values: Any = inventory.get("definitions", {}) if isinstance(inventory, Mapping) else inventory
    if not isinstance(values, Mapping):
        return {}
    definitions: dict[str, dict[str, dict[str, Any]]] = {}
    for name, raw in values.items():
        if not isinstance(name, str):
            continue
        ports_value = raw.get("ports", ()) if isinstance(raw, Mapping) else raw
        ports: dict[str, dict[str, Any]] = {}
        if isinstance(ports_value, Mapping):
            for port_name, port_value in ports_value.items():
                if isinstance(port_name, str):
                    ports[port_name] = dict(port_value) if isinstance(port_value, Mapping) else {}
        elif isinstance(ports_value, Sequence) and not isinstance(ports_value, (str, bytes, bytearray)):
            for port_value in ports_value:
                if isinstance(port_value, str):
                    ports[port_value] = {}
                elif isinstance(port_value, Mapping) and isinstance(port_value.get("name"), str):
                    ports[port_value["name"]] = dict(port_value)
        definitions[name] = ports
    return definitions


def _resolve_paths(request: MmcPlanRequest, workspace: str | Path | PathPolicy) -> tuple[Path, Path, str, float | None]:
    project_name = _text(request.project_name, "project_name")
    if any(separator in project_name for separator in ("/", "\\")) or project_name in {".", ".."}:
        raise _error("MMC_LAYOUT_INVALID", "project_name must be a single project identity.", project_name=project_name)
    filename = project_name if project_name.casefold().endswith(".pscx") else f"{project_name}.pscx"
    if isinstance(workspace, PathPolicy):
        policy = workspace
        if policy.workspace_root is None:
            raise _error("MMC_LAYOUT_INVALID", "A configured workspace is required for MMC planning.")
        workspace_root = Path(policy.workspace_root).expanduser().resolve()
    else:
        workspace_root = Path(workspace).expanduser().resolve()
        policy = PathPolicy(workspace_root=str(workspace_root))
    try:
        folder = workspace_root if request.folder is None else policy.resolve(request.folder)
        final_path = policy.resolve_child(str(folder), filename, suffixes={".pscx"})
    except (WorkspaceNotConfiguredError, ValueError, OSError) as error:
        raise _error("MMC_LAYOUT_INVALID", str(error), project_name=project_name) from error
    raw_final = folder / project_name
    raw_target = folder / filename
    if final_path.exists() or raw_final.exists() or raw_target.is_symlink():
        raise _error("MMC_BUILD_CONFLICT", "The planned final destination already exists.", target_path=str(final_path))
    staging = workspace_root / ".pscad-mcp" / "mmc-builds" / f"{Path(filename).stem}.staging"
    return final_path, staging, project_name, request.simulation_duration_s


def _duration(request: MmcPlanRequest, blueprint: MmcBlueprint) -> float:
    default = blueprint.settings.get("simulation_duration_s")
    if isinstance(default, bool) or not isinstance(default, (int, float)) or default <= 0:
        raise _error("MMC_BLUEPRINT_INVALID", "The blueprint simulation duration is invalid.")
    value = default if request.simulation_duration_s is None else request.simulation_duration_s
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise _error("MMC_BLUEPRINT_INVALID", "simulation_duration_s must be positive.")
    if value < default:
        raise _error("MMC_BLUEPRINT_INVALID", "simulation_duration_s cannot be shorter than the packaged default.", requested=value, minimum=default)
    return float(value)


def _catalog_rectangles(components: Sequence[MmcComponentSpec], catalog: MmcCatalog) -> dict[str, tuple[int, int, int, int]]:
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


def _endpoint(value: str, context: str) -> tuple[str, str]:
    if not isinstance(value, str) or ":" not in value:
        raise _error("MMC_BLUEPRINT_INVALID", f"{context} must be component:port.", endpoint=value)
    component, port = value.split(":", 1)
    return _text(component, f"{context}.component"), _text(port, f"{context}.port")


def _net_route(net: MmcNetSpec, components: Mapping[str, MmcComponentSpec], catalog: MmcCatalog) -> tuple[tuple[int, int], ...]:
    endpoints = [_endpoint(endpoint, f"nets.{net.logical_id}.endpoints[{index}]") for index, endpoint in enumerate(net.endpoints)]
    points: list[tuple[int, int]] = []
    for component_id, port_name in endpoints:
        component = components.get(component_id)
        if component is None:
            raise _error("MMC_BLUEPRINT_INVALID", "net references an unknown component.", net=net.logical_id, component=component_id)
        definition = require_definition(catalog, component.definition)
        port = require_port(definition, port_name)
        if port_name not in component.ports:
            raise _error("MMC_PORT_MISMATCH", "net references an undeclared component port.", net=net.logical_id, component=component_id, port=port_name)
        points.append(absolute_port(component.location, port.offset, component.orientation))
    if net.route:
        try:
            route = validate_orthogonal_route(net.route)
        except BackendError as error:
            raise _error("MMC_LAYOUT_INVALID", str(error), net=net.logical_id) from error
        if route[0] != points[0] or route[-1] != points[-1]:
            raise _error("MMC_LAYOUT_INVALID", "net route endpoints do not match catalog ports.", net=net.logical_id, expected_start=list(points[0]), expected_end=list(points[-1]), observed_start=list(route[0]), observed_end=list(route[-1]))
        return route
    if len(points) < 2:
        raise _error("MMC_LAYOUT_INVALID", "net requires at least two endpoints.", net=net.logical_id)
    route: list[tuple[int, int]] = [points[0]]
    for point in points[1:]:
        previous = route[-1]
        if previous[0] != point[0] and previous[1] != point[1]:
            route.append((point[0], previous[1]))
        route.append(point)
    route = [point for index, point in enumerate(route) if index == 0 or point != route[index - 1]]
    try:
        return validate_orthogonal_route(route)
    except BackendError as error:
        raise _error("MMC_LAYOUT_INVALID", str(error), net=net.logical_id) from error


def _check_structure(blueprint: MmcBlueprint, components: Mapping[str, MmcComponentSpec], catalog: MmcCatalog) -> None:
    arms = [component for component in components.values() if component.definition.endswith(":MMCAverageArm")]
    if len(arms) != 12 or len({component.logical_id for component in arms}) != 12:
        raise _error("MMC_STRUCTURE_INVALID", "fixed MMC plan requires exactly twelve unique visible average arms.", observed=len(arms))
    expected_arm_ids = {arm.logical_id for station in blueprint.stations for arm in station.arms}
    if {component.logical_id for component in arms} != expected_arm_ids:
        raise _error("MMC_STRUCTURE_INVALID", "visible arm components do not match station arm contracts.")
    if not any("positive_bus" in component.logical_id for component in components.values()) or not any("negative_bus" in component.logical_id for component in components.values()):
        raise _error("MMC_STRUCTURE_INVALID", "positive and negative DC buses are required.")
    net_ids = {net.logical_id for net in blueprint.nets}
    if not {"dc_positive_conductor", "dc_negative_conductor"} <= net_ids:
        raise _error("MMC_STRUCTURE_INVALID", "positive and negative DC conductor paths are required.")
    rectangles = _catalog_rectangles(tuple(components.values()), catalog)
    rectangle_items = list(rectangles.items())
    for index, (left_id, left_rect) in enumerate(rectangle_items):
        for right_id, right_rect in rectangle_items[index + 1 :]:
            if _rectangles_overlap(left_rect, right_rect):
                raise _error("MMC_LAYOUT_INVALID", "blueprint components overlap.", left=left_id, right=right_id)


def _check_net_semantics(net: MmcNetSpec) -> None:
    lowered = " ".join((net.logical_id, *net.endpoints)).casefold()
    if net.kind == "electrical" and "ground" in lowered:
        raise _error("MMC_STRUCTURE_INVALID", "ground must not be a normal electrical return conductor.", net=net.logical_id)
    has_ac = any(token in lowered for token in (".ac", ":ac", "transformer"))
    has_dc = any(token in lowered for token in ("dc_", "dc:", "positive_bus", "negative_bus", "_line"))
    if net.kind == "electrical" and has_ac and has_dc:
        raise _error("MMC_STRUCTURE_INVALID", "AC and DC endpoints must not share an electrical net.", net=net.logical_id)
    if "positive" in lowered and "negative" in lowered:
        raise _error("MMC_STRUCTURE_INVALID", "positive and negative poles must not be crossed.", net=net.logical_id)


def _normalize_inventory_contract(component: MmcComponentSpec, definition: MmcDefinitionSpec, inventory_ports: Mapping[str, dict[str, Any]]) -> None:
    for port_name in component.ports:
        port = require_port(definition, port_name)
        live = inventory_ports.get(port_name)
        if live is None:
            raise _error("MMC_PORT_MISMATCH", "port is missing from live inventory.", definition=component.definition, port=port_name)
        if isinstance(live.get("kind"), str) and live["kind"] != port.kind:
            raise _error("MMC_PORT_MISMATCH", "live port kind does not match catalog.", definition=component.definition, port=port_name)
        if live.get("dimension") is not None and live["dimension"] != port.dimension:
            raise _error("MMC_PORT_MISMATCH", "live port dimension does not match catalog.", definition=component.definition, port=port_name)


def _acceptance_checks(blueprint: MmcBlueprint, asset_set: MmcAssetSet) -> tuple[MmcAcceptanceCheck, ...]:
    if blueprint.acceptance_checks:
        return blueprint.acceptance_checks
    raw = asset_set.acceptance.get("checks", asset_set.acceptance.get("windows", ()))
    checks: list[MmcAcceptanceCheck] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise _error("MMC_BLUEPRINT_INVALID", "acceptance windows must be objects.", index=index)
        window = item.get("comparison_window", (0.0, 1.0))
        checks.append(MmcAcceptanceCheck(name=_text(item.get("name", f"check_{index}"), "acceptance.name"), kind=_text(item.get("kind", "window"), "acceptance.kind"), required=bool(item.get("required", True)), expected=dict(item.get("expected", {})), units=_text(item.get("units", "1"), "acceptance.units"), comparison_window=(float(window[0]), float(window[1]))))
    return tuple(checks)


def _operation_kind(component: MmcComponentSpec) -> str:
    if component.definition.endswith(":MMCAverageArm"):
        return "place_arm"
    if "Control" in component.definition or "control" in (component.role or "").casefold() or "Energy" in component.definition or "Initialization" in component.definition:
        return "place_control"
    return "place_power"


def create_plan(request: MmcPlanRequest, asset_set: MmcAssetSet, inventory: Any, workspace: str | Path | PathPolicy) -> MmcBuildPlan:
    """Expand a verified fixed blueprint without changing workspace or PSCAD."""

    if not isinstance(request, MmcPlanRequest):
        raise _error("MMC_BLUEPRINT_INVALID", "request must be an MmcPlanRequest.")
    if request.blueprint != asset_set.name:
        raise _error("MMC_BLUEPRINT_NOT_FOUND", f"Blueprint '{request.blueprint}' is not the loaded asset set.", blueprint=request.blueprint)
    if asset_set.pscad_version != "4.6.2":
        raise _error("MMC_VERSION_UNSUPPORTED", "MMC Stage A requires PSCAD 4.6.2.", observed_version=asset_set.pscad_version)
    version = _inventory_version(inventory)
    if version != "4.6.2":
        raise _error("MMC_VERSION_UNSUPPORTED", "planner requires PSCAD 4.6.2 inventory metadata.", observed_version=version, required_version="4.6.2")
    blueprint = asset_set.blueprint
    if blueprint.profile != "cigre_b4_p2p_avm_v1":
        raise _error("MMC_MODEL_UNSUPPORTED", "only the fixed Stage A MMC profile is supported.", profile=blueprint.profile)
    duration = _duration(request, blueprint)
    final_path, staging_path, project_name, _ = _resolve_paths(request, workspace)
    catalog = asset_set.catalog if isinstance(asset_set.catalog, MmcCatalog) else parse_catalog(asset_set.catalog)
    inventory_definitions = _inventory_definitions(inventory)
    normalized_components: list[MmcComponentSpec] = []
    for component in blueprint.components:
        definition = require_definition(catalog, component.definition)
        live_ports = inventory_definitions.get(component.definition)
        if live_ports is None:
            raise _error("MMC_DEFINITION_MISSING", "definition is missing from live inventory.", definition=component.definition)
        normalized_parameters = validate_parameters(definition, dict(component.parameters))
        _normalize_inventory_contract(component, definition, live_ports)
        normalized_components.append(replace(component, parameters=normalized_parameters))
    normalized_blueprint = replace(blueprint, components=tuple(normalized_components), settings={**dict(blueprint.settings), "simulation_duration_s": duration})
    component_map = {component.logical_id: component for component in normalized_blueprint.components}
    _check_structure(normalized_blueprint, component_map, catalog)
    for net in normalized_blueprint.nets:
        _check_net_semantics(net)
        route = _net_route(net, component_map, catalog)
        rectangles = _catalog_rectangles(tuple(component_map.values()), catalog)
        try:
            route_intersects_rectangles(route, [rect for logical_id, rect in rectangles.items() if logical_id not in {_endpoint(endpoint, "net endpoint")[0] for endpoint in net.endpoints}])
        except BackendError as error:
            raise _error("MMC_LAYOUT_INVALID", str(error), net=net.logical_id) from error
    checks = _acceptance_checks(normalized_blueprint, asset_set)
    counters: defaultdict[str, int] = defaultdict(int)
    operations: list[MmcPlanOperation] = []

    def add(phase: str, kind: str, target: str, arguments: Mapping[str, Any] | None = None) -> None:
        index = counters[phase]
        counters[phase] += 1
        operations.append(MmcPlanOperation(sequence=len(operations) + 1, kind=kind, target=target, arguments=dict(arguments or {}), operation_id=f"{phase}:{target}:{index:03d}", phase=phase))

    library_hash = asset_set.hashes.get(asset_set.companion_library)
    if library_hash is None:
        raise _error("MMC_ASSET_MISMATCH", "companion library is not covered by the asset manifest.", library=asset_set.companion_library)
    add("materialize_library", "materialize_library", asset_set.companion_library, {"sha256": library_hash})
    add("create_staging", "create_staging", project_name, {"target_path": str(final_path), "staging_path": str(staging_path)})
    add("set_settings", "set_project_settings", project_name, {"settings": dict(normalized_blueprint.settings)})
    for component in normalized_blueprint.components:
        add(_operation_kind(component), "place_component", component.logical_id, {"definition": component.definition, "location": list(component.location), "orientation": component.orientation, "parameters": dict(component.parameters), "ports": list(component.ports)})
    for station in normalized_blueprint.stations:
        for phase in ("A", "B", "C"):
            add("create_phase_midpoint", "create_phase_midpoint", f"{station.logical_id}.{phase}.midpoint", {"station": station.logical_id, "phase": phase})
    for polarity in ("positive", "negative"):
        add("create_dc_terminal", "create_dc_terminal", polarity, {"pole": polarity})
    for component in normalized_blueprint.components:
        add("verify_parameters", "verify_parameters", component.logical_id, {"parameters": dict(component.parameters)})
    for net in normalized_blueprint.nets:
        route = _net_route(net, component_map, catalog)
        phase = "connect_electrical" if net.kind == "electrical" else "connect_data"
        add(phase, "connect_net", net.logical_id, {"kind": net.kind, "endpoints": list(net.endpoints), "vertices": [list(point) for point in route], "label": net.label})
    for output in normalized_blueprint.outputs:
        if output.measurement is not None and (":" not in output.measurement or output.measurement.split(":", 1)[0] not in component_map):
            raise _error("MMC_BLUEPRINT_INVALID", "output is not backed by a declared measurement endpoint.", output=output.logical_id, measurement=output.measurement)
        add("create_outputs", "create_output", output.logical_id, output.to_dict())
    add("save_and_validate", "save_and_validate", project_name)
    add("compile", "compile", project_name)
    for phase in ("startup", "forward", "reversal", "reverse"):
        add(f"{phase}_simulate", "simulate_phase", phase, {"duration_s": duration, "state": f"{phase}_simulated"})
    add("accept", "accept", project_name, {"required_checks": [check.name for check in checks]})
    add("publish", "publish", project_name, {"target_path": str(final_path)})
    payload = {
        "request": {"project_name": project_name, "folder": str(final_path.parent), "simulation_duration_s": duration, "blueprint": request.blueprint},
        "target_path": str(final_path), "staging_path": str(staging_path), "pscad_version": asset_set.pscad_version,
        "asset_hashes": dict(asset_set.hashes), "catalog_identity": catalog.identity, "project_settings": dict(normalized_blueprint.settings),
        "operations": [operation.to_dict() for operation in operations], "acceptance_contract": [check.to_dict() for check in checks],
    }
    return MmcBuildPlan(blueprint=normalized_blueprint, operations=tuple(operations), plan_hash=content_hash(payload), acceptance_checks=checks, target_path=str(final_path), staging_path=str(staging_path), asset_hashes=dict(asset_set.hashes), pscad_version=asset_set.pscad_version, catalog_identity=catalog.identity, metadata=payload["request"])


def create_parametric_avm_plan(
    engine_plan: Any,
    asset_set: MmcAssetSet,
    inventory: Any,
    workspace: str | Path | PathPolicy,
    *,
    candidate_id: str | None = None,
) -> MmcBuildPlan:
    """Bind a parameterized AVM child plan to the verified Stage A planner."""

    from .engines.avm import materialize_parametric_blueprint
    from .parametric_models import MmcEnginePlan

    if not isinstance(engine_plan, MmcEnginePlan) or engine_plan.engine != "average_value":
        raise _error(
            "MMC_PLAN_INVALID",
            "The parametric AVM planner requires an average_value child plan.",
        )
    if dict(engine_plan.asset_hashes) != dict(asset_set.hashes):
        raise _error(
            "MMC_ASSET_MISMATCH",
            "The AVM asset hashes differ from the immutable child plan.",
            expected=dict(engine_plan.asset_hashes),
            observed=dict(asset_set.hashes),
        )
    blueprint = materialize_parametric_blueprint(
        engine_plan, asset_set=asset_set, candidate_id=candidate_id
    )
    parameterized_assets = replace(asset_set, blueprint=blueprint)
    fixed = create_plan(
        MmcPlanRequest(project_name=engine_plan.target_name),
        parameterized_assets,
        inventory,
        workspace,
    )
    if Path(fixed.target_path or "").resolve() != Path(engine_plan.target_path).resolve():
        raise _error(
            "MMC_PLAN_STALE",
            "The Stage A AVM target differs from the immutable child target.",
            child_target=engine_plan.target_path,
            stage_a_target=fixed.target_path,
        )
    selected_id = candidate_id or engine_plan.candidates[0].candidate_id
    metadata = {
        **dict(fixed.metadata),
        "parametric_engine_plan_hash": engine_plan.plan_hash,
        "parametric_candidate_id": selected_id,
        "intrinsic_dc_fault_blocking": False,
    }
    bound_hash = content_hash(
        {
            "stage_a_plan_hash": fixed.plan_hash,
            "parametric_engine_plan_hash": engine_plan.plan_hash,
            "parametric_candidate_id": selected_id,
        }
    )
    return replace(fixed, plan_hash=bound_hash, metadata=metadata)


__all__ = [
    "MmcAssetSet",
    "MmcPlanRequest",
    "PHASES",
    "create_parametric_avm_plan",
    "create_plan",
]
