"""Deterministic, side-effect-free expansion of the fixed LCC blueprint."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from pathlib import Path
from typing import Any

from ....core.master_bindings import AuditedMasterRegistry
from ....core.path_policy import PathPolicy, WorkspaceNotConfiguredError
from .assets import (
    LccAssetSet,
    canonical_json,
    load_parametric_catalog,
    validate_parametric_blueprint_asset,
)
from .catalog import (
    LccCatalog,
    parse_catalog,
    require_definition,
    require_port,
    validate_parameters,
)
from .fault_event import inspect_fixed_lcc_fault_capability
from .models import (
    LccAcceptanceCheck,
    LccBuildPlan,
    LccComponentSpec,
    LccNetSpec,
    LccPlanOperation,
)
from .parametric_models import DerivedParameterReport
from .routing import (
    absolute_port,
    route_intersects_rectangles,
    validate_orthogonal_route,
)

FULL_ACCEPTANCE_PROFILE = "full_acceptance"
WP1B_SMOKE_PROFILE = "wp1b_smoke"
WP1C_DYNAMIC_PROFILE = "wp1c_dynamic"
VERIFICATION_PROFILES = {
    FULL_ACCEPTANCE_PROFILE,
    WP1B_SMOKE_PROFILE,
    WP1C_DYNAMIC_PROFILE,
}


def _dynamic_schedule_events(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes, bytearray)) or not events:
        raise _error(
            "LCC_DYNAMIC_EVENT_UNAVAILABLE",
            "A dynamic profile requires at least one fault event declaration.",
        )
    scheduled: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            raise _error(
                "LCC_DYNAMIC_EVENT_UNAVAILABLE",
                "Dynamic event declarations must be objects.",
                index=index,
            )
        components = event.get("control_components")
        parameter = event.get("control_parameter")
        if not isinstance(components, Sequence) or isinstance(components, (str, bytes, bytearray)) or not components or any(not isinstance(item, str) or not item.strip() for item in components) or not isinstance(parameter, str) or not parameter.strip():
            raise _error(
                "LCC_DYNAMIC_EVENT_UNAVAILABLE",
                "Dynamic event declarations require an exact control component and parameter.",
                index=index,
            )
        normalized_components = [item.strip() for item in components]
        if len(set(normalized_components)) != len(normalized_components):
            raise _error(
                "LCC_DYNAMIC_EVENT_UNAVAILABLE",
                "Dynamic event control targets must be unique.",
                index=index,
            )
        time_s = event.get("time_s")
        duration_s = event.get("duration_s")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in (time_s, duration_s)) or float(time_s) < 0 or float(duration_s) <= 0:
            raise _error(
                "LCC_DYNAMIC_EVENT_UNAVAILABLE",
                "Dynamic event timing must be finite, non-negative, and positive in duration.",
                index=index,
            )
        event_prefix = str(event.get("kind", "fault"))
        if len(events) > 1:
            event_prefix = f"{event_prefix}:{index}"
        for phase_index, component in enumerate(normalized_components):
            target = f"{component}.{parameter.strip()}"
            phase_suffix = "" if len(components) == 1 else f":phase-{phase_index}"
            scheduled.extend(
                [
                    {
                        "event_id": f"{event_prefix}:on{phase_suffix}",
                        "time_s": float(time_s),
                        "target": target,
                        "value": event.get("apply_value"),
                    },
                    {
                        "event_id": f"{event_prefix}:off{phase_suffix}",
                        "time_s": float(time_s) + float(duration_s),
                        "target": target,
                        "value": event.get("clear_value"),
                    },
                ]
            )
    scheduled.sort(key=lambda item: (item["time_s"], item["event_id"]))
    if any(
        right["time_s"] < left["time_s"]
        for left, right in pairwise(scheduled)
    ):
        raise _error(
            "LCC_DYNAMIC_EVENT_UNAVAILABLE",
            "Dynamic event times must be non-decreasing after expansion.",
        )
    event_ids = [item["event_id"] for item in scheduled]
    target_slots = [(item["time_s"], item["target"]) for item in scheduled]
    if len(event_ids) != len(set(event_ids)) or len(target_slots) != len(set(target_slots)):
        raise _error(
            "LCC_DYNAMIC_EVENT_UNAVAILABLE",
            "Expanded dynamic events contain duplicate identifiers or target-time conflicts.",
        )
    return scheduled

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
    "verify_dynamic_control",
    "register_dynamic_events",
    "simulate",
    "smoke_validate",
    "dynamic_accept",
    "accept",
    "publish",
)


@dataclass(frozen=True)
class LccPlanRequest:
    project_name: str
    folder: str | None = None
    simulation_duration_s: float | None = None
    blueprint: str = "cigre_lcc_monopole_v1"
    verification_profile: str = FULL_ACCEPTANCE_PROFILE


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


def _audited_master_registry(
    asset_set: LccAssetSet,
    inventory: Any,
) -> AuditedMasterRegistry | None:
    registry = asset_set.master_bindings
    if registry is None:
        return None
    if not isinstance(inventory, Mapping):
        raise _error(
            "MASTER_BINDING_MISSING",
            "A live Master inventory is required for the packaged binding registry.",
        )
    observed_registry_hash = inventory.get("master_binding_registry_sha256")
    if not isinstance(observed_registry_hash, str):
        raise _error(
            "MASTER_BINDING_MISSING",
            "The live inventory does not contain a Master binding registry hash.",
        )
    if observed_registry_hash != registry.sha256:
        raise _error(
            "MASTER_SOURCE_CHANGED",
            "The live inventory was audited with a different Master binding registry.",
            expected_registry_sha256=registry.sha256,
            observed_registry_sha256=observed_registry_hash,
        )
    master_sha256 = inventory.get("master_sha256")
    if (
        not isinstance(master_sha256, str)
        or len(master_sha256) != 64
        or any(character not in "0123456789abcdef" for character in master_sha256)
    ):
        raise _error(
            "MASTER_BINDING_MISSING",
            "The live inventory does not contain a valid Master source hash.",
            observed_master_sha256=master_sha256,
        )
    definitions_value = inventory.get("definitions")
    if not isinstance(definitions_value, Mapping):
        raise _error(
            "MASTER_BINDING_MISSING",
            "The live inventory does not contain Master definition evidence.",
        )
    definitions: dict[str, Mapping[str, Any]] = {}
    for binding in registry.bindings:
        evidence = definitions_value.get(binding.logical_name)
        if not isinstance(evidence, Mapping):
            raise _error(
                "MASTER_BINDING_MISSING",
                "A registry binding is missing from the live inventory.",
                logical_name=binding.logical_name,
            )
        if (
            evidence.get("verification_state") != "verified"
            or evidence.get("physical_definition")
            != binding.physical_definition
            or not isinstance(evidence.get("selected_ports"), Mapping)
        ):
            raise _error(
                "MASTER_BINDING_MISSING",
                "A live Master definition lacks verified physical evidence.",
                logical_name=binding.logical_name,
                expected_physical_definition=binding.physical_definition,
                observed_physical_definition=evidence.get("physical_definition"),
                verification_state=evidence.get("verification_state"),
            )
        definitions[binding.logical_name] = evidence
    return AuditedMasterRegistry(
        registry=registry,
        master_path=str(inventory.get("master_path", "")),
        master_sha256=master_sha256,
        definitions=definitions,
    )


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


def _wp1b_connection_labels(blueprint) -> dict[str, str | None]:
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(endpoint: tuple[str, str]) -> tuple[str, str]:
        parent.setdefault(endpoint, endpoint)
        if parent[endpoint] != endpoint:
            parent[endpoint] = find(parent[endpoint])
        return parent[endpoint]

    def union(left: tuple[str, str], right: tuple[str, str]) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for net in blueprint.nets:
        if net.logical_id.startswith("inverter_fault_"):
            continue
        endpoints = [
            (net.kind, f"{endpoint.component}:{endpoint.port}")
            for endpoint in net.endpoints
        ]
        for endpoint in endpoints[1:]:
            union(endpoints[0], endpoint)

    groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for net in blueprint.nets:
        if net.logical_id.startswith("inverter_fault_"):
            continue
        endpoint = net.endpoints[0]
        root = find((net.kind, f"{endpoint.component}:{endpoint.port}"))
        groups[root].append(net)

    components = {
        component.logical_id: component for component in blueprint.components
    }
    result = {}
    for nets in groups.values():
        endpoint_names = sorted(
            {
                f"{endpoint.component}:{endpoint.port}"
                for net in nets
                for endpoint in net.endpoints
            }
        )
        imported_names = {
            str(components[endpoint.component].parameters.get("Name"))
            for net in nets
            for endpoint in net.endpoints
            if components[endpoint.component].definition
            == "master:main_signal_import"
            and isinstance(
                components[endpoint.component].parameters.get("Name"),
                str,
            )
        }
        has_ground = any(
            components[endpoint.component].definition == "master:ground"
            for net in nets
            for endpoint in net.endpoints
        )
        if len(imported_names) > 1:
            raise _error(
                "LCC_BLUEPRINT_INVALID",
                "One WP1B connection group references multiple imported names.",
                imported_names=sorted(imported_names),
            )
        label = None if has_ground else (
            next(iter(imported_names))
            if len(imported_names) == 1
            else "WP1B_"
            + hashlib.sha256("\0".join(endpoint_names).encode("utf-8")).hexdigest()[
                :16
            ].upper()
        )
        for net in nets:
            result[net.logical_id] = label
    return result


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
    staging_identity = Path(filename).stem
    final_filename = (
        f"{staging_identity}_PUBLISHED.pscx"
        if request.verification_profile == WP1B_SMOKE_PROFILE
        else filename
    )
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
        final_path = policy.resolve_child(
            str(folder),
            final_filename,
            suffixes={".pscx"},
        )
    except (WorkspaceNotConfiguredError, ValueError, OSError) as error:
        raise _error("LCC_LAYOUT_INVALID", str(error), project_name=project_name) from error
    raw_final = folder / project_name
    raw_target = folder / final_filename
    if final_path.exists() or raw_final.exists() or raw_target.is_symlink():
        raise _error(
            "LCC_BUILD_CONFLICT",
            "The planned final destination already exists.",
            target_path=str(final_path),
        )
    staging = (
        folder
        / ".pscad-mcp"
        / "lcc-builds"
        / f"{staging_identity}.staging"
    )
    request_duration = None
    return final_path, staging, project_name, request_duration


def _duration(request: LccPlanRequest, asset_set: LccAssetSet) -> float:
    if request.verification_profile == WP1B_SMOKE_PROFILE:
        expected = asset_set.smoke.get("duration_s")
        if (
            isinstance(expected, bool)
            or not isinstance(expected, (int, float))
            or expected <= 0
        ):
            raise _error(
                "LCC_BLUEPRINT_INVALID",
                "The packaged smoke duration is invalid.",
            )
        value = (
            float(expected)
            if request.simulation_duration_s is None
            else request.simulation_duration_s
        )
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or abs(float(value) - float(expected)) > 1e-12
        ):
            raise _error(
                "LCC_BLUEPRINT_INVALID",
                "WP1B smoke duration must match the packaged contract.",
                requested=value,
                expected=float(expected),
            )
        return float(expected)
    default = asset_set.blueprint.settings.get("simulation_duration_s")
    if request.verification_profile == WP1C_DYNAMIC_PROFILE and request.simulation_duration_s is None:
        default = 1.5
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
    plan_bindings: list[dict[str, Any]] = []
    template_bindings = catalog_value.get("template_bindings", ())
    if not isinstance(template_bindings, Sequence) or isinstance(template_bindings, (str, bytes, bytearray)):
        template_bindings = ()
    reviewed_by_key: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for declaration in template_bindings:
        if not isinstance(declaration, Mapping):
            continue
        logical = declaration.get("logical_parameter")
        role = declaration.get("role")
        if isinstance(logical, str) and isinstance(role, str):
            reviewed_by_key[(logical, role)].append(declaration)
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
        binding_roles = list(roles)
        if reviewed_by_key.get((parameter.name, "main_control")):
            binding_roles.append("main_control")
        for role in binding_roles:
            if role in role_parameters:
                role_parameters[role][parameter.name] = {
                    "value": parameter.value,
                    "units": parameter.units,
                    "logical_parameter": logical_parameter,
                    "template_parameter": template_parameter,
                }
        parameter_bindings: list[dict[str, Any]] = []
        for role in binding_roles:
            candidates = reviewed_by_key.get((parameter.name, role), [])
            for candidate in candidates:
                selector = candidate.get("selector")
                attribute = candidate.get("attribute")
                units = candidate.get("units")
                if (
                    candidate.get("binding_status") == "reviewed"
                    and isinstance(selector, str)
                    and isinstance(attribute, str)
                    and isinstance(units, str)
                    and units == parameter.units
                ):
                    expected = candidate.get("expected_match_count", 1)
                    if isinstance(expected, bool) or not isinstance(expected, int) or expected <= 0:
                        raise _error(
                            "LCC_PARAMETER_BINDING_UNAVAILABLE",
                            "A reviewed template binding must declare a positive expected match count.",
                            logical_parameter=parameter.name,
                        )
                    parameter_bindings.append(
                        {
                            "logical_parameter": parameter.name,
                            "role": role,
                            "selector": selector,
                            "attribute": attribute,
                            "units": units,
                            "derived_value": parameter.value,
                            "value": parameter.value,
                            "expected_match_count": expected,
                        }
                    )
        if parameter_bindings:
            plan_bindings.extend(parameter_bindings)
        if not parameter_bindings:
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
        "bindings": sorted(
            plan_bindings,
            key=lambda item: (item["logical_parameter"], item["role"], item["selector"]),
        ),
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
    if request.verification_profile not in VERIFICATION_PROFILES:
        raise _error(
            "LCC_BLUEPRINT_INVALID",
            "The LCC verification profile is unsupported.",
            verification_profile=request.verification_profile,
            supported_profiles=sorted(VERIFICATION_PROFILES),
        )
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
    if request.verification_profile == WP1C_DYNAMIC_PROFILE:
        capability = inspect_fixed_lcc_fault_capability(
            blueprint.to_dict(),
            asset_set.catalog,
            inventory if isinstance(inventory, Mapping) else {},
        )
        if capability["status"] != "PASS":
            raise _error(
                "LCC_DYNAMIC_EVENT_UNAVAILABLE",
                "The fixed LCC blueprint has no complete fault/event binding.",
                reasons=capability.get("reasons", []),
            )
    duration = _duration(request, asset_set)
    if request.verification_profile == WP1C_DYNAMIC_PROFILE:
        event = blueprint.dynamic_events[0] if blueprint.dynamic_events else {}
        bindings = capability.get("bindings", {})
        try:
            minimum_duration = (
                float(event.get("time_s"))
                + float(event.get("duration_s"))
                + float(bindings.get("recovery_window_s"))
            )
        except (TypeError, ValueError):
            minimum_duration = float("inf")
        if duration + 1e-12 < minimum_duration:
            raise _error(
                "LCC_DYNAMIC_EVENT_UNAVAILABLE",
                "Simulation duration does not cover the complete recovery window.",
                simulation_duration_s=duration,
                minimum_duration_s=minimum_duration,
            )
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
    audited_master = _audited_master_registry(asset_set, inventory)
    normalized_components: list[LccComponentSpec] = []
    resolved_master_components: dict[str, dict[str, Any]] = {}
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
            records = [measurement_map[logical_id] for logical_id in logical_ids]
            roots = [record for record in records if record.get("derived_from") is None]
            derived = [record for record in records if record.get("derived_from") is not None]
            if len(roots) != 1 or any(
                not isinstance(record.get("derived_from"), str)
                or record["derived_from"] not in logical_ids
                for record in derived
            ):
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
        if component.definition.startswith("master:") and audited_master is not None:
            resolved_master_components[component.logical_id] = (
                audited_master.resolve_component(
                    component.definition,
                    normalized_parameters,
                ).to_evidence()
            )
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
    checks = (
        ()
        if request.verification_profile == WP1B_SMOKE_PROFILE
        else _acceptance_checks(asset_set)
    )
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
        arguments = {
            "definition": component.definition,
            "canvas": component.canvas,
            "location": list(component.location),
            "orientation": component.orientation,
            "parameters": dict(component.parameters),
            "ports": list(component.ports),
        }
        if component.logical_id in resolved_master_components:
            arguments["binding"] = resolved_master_components[component.logical_id]
        add(
            phase,
            "place_component",
            component.logical_id,
            arguments,
        )
    for component in blueprint.components:
        arguments = {
            "parameters": dict(component.parameters),
        }
        if component.logical_id in resolved_master_components:
            arguments["binding"] = resolved_master_components[component.logical_id]
        add(
            "verify_parameters",
            "verify_parameters",
            component.logical_id,
            arguments,
        )
    connection_labels = (
        _wp1b_connection_labels(blueprint)
        if request.verification_profile == WP1B_SMOKE_PROFILE
        else {}
    )
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
                "label": connection_labels.get(net.logical_id, net.label),
            },
        )
    planned_outputs = blueprint.outputs
    if request.verification_profile == WP1B_SMOKE_PROFILE:
        output_by_path = {output.path: output for output in blueprint.outputs}
        required_paths = tuple(asset_set.smoke["required_channels"])
        if len(output_by_path) != len(blueprint.outputs) or any(
            path not in output_by_path for path in required_paths
        ):
            raise _error(
                "LCC_BLUEPRINT_INVALID",
                "The WP1B smoke outputs are not an exact blueprint subset.",
                required_channels=list(required_paths),
            )
        planned_outputs = tuple(output_by_path[path] for path in required_paths)
    if request.verification_profile != WP1B_SMOKE_PROFILE:
        for output in planned_outputs:
            add("create_outputs", "create_output", output.logical_id, output.to_dict())
    add("save_and_validate", "save_and_validate", project_name, {})
    add("compile", "compile", project_name, {})
    if request.verification_profile == WP1C_DYNAMIC_PROFILE:
        dynamic_control = capability["bindings"]
        if dynamic_control["control_mode"] == "embedded_emtdc":
            add(
                "verify_dynamic_control",
                "verify_dynamic_control",
                project_name,
                dynamic_control,
            )
        else:
            add(
                "register_dynamic_events",
                "register_dynamic_events",
                project_name,
                {"events": _dynamic_schedule_events(blueprint.dynamic_events)},
            )
    if request.verification_profile == WP1B_SMOKE_PROFILE:
        for output in planned_outputs:
            add("create_outputs", "create_output", output.logical_id, output.to_dict())
    add("simulate", "simulate", project_name, {"duration_s": duration})
    if request.verification_profile == WP1B_SMOKE_PROFILE:
        add(
            "smoke_validate",
            "smoke_validate",
            project_name,
            {
                "contract_sha256": asset_set.hashes["smoke.json"],
                "required_channels": list(
                    asset_set.smoke["required_channels"]
                ),
            },
        )
    elif request.verification_profile == WP1C_DYNAMIC_PROFILE:
        add(
            "dynamic_accept",
            "dynamic_accept",
            project_name,
            {
                "contract_sha256": asset_set.hashes["dynamic.json"],
                "event": capability["bindings"]["event"],
            },
        )
    else:
        add(
            "accept",
            "accept",
            project_name,
            {"required_checks": [check.name for check in checks]},
        )
    add("publish", "publish", project_name, {"target_path": str(final_path)})
    payload = {
        "request": {
            "project_name": project_name,
            "folder": str(final_path.parent),
            "simulation_duration_s": duration,
            "blueprint": request.blueprint,
            "verification_profile": request.verification_profile,
        },
        "target_path": str(final_path),
        "staging_path": str(staging_path),
        "pscad_version": asset_set.pscad_version,
        "asset_hashes": dict(asset_set.hashes),
        "catalog_identity": catalog.identity,
        "project_settings": settings,
        "operations": [operation.to_dict() for operation in operations],
        "acceptance_contract": [check.to_dict() for check in checks],
        "verification_profile": request.verification_profile,
    }
    if request.verification_profile == WP1B_SMOKE_PROFILE:
        payload["smoke_contract_sha256"] = asset_set.hashes["smoke.json"]
    if request.verification_profile == WP1C_DYNAMIC_PROFILE:
        dynamic_metadata = dict(capability["bindings"])
        dynamic_metadata["mode"] = dynamic_metadata.pop("control_mode")
        payload["dynamic_control"] = dynamic_metadata
    if audited_master is not None:
        payload["master_sha256"] = audited_master.master_sha256
        payload["master_binding_registry_sha256"] = (
            audited_master.registry.sha256
        )
    plan_hash = hashlib.sha256(canonical_json(payload)).hexdigest()
    return LccBuildPlan(
        blueprint=blueprint,
        operations=tuple(operations),
        plan_hash=plan_hash,
        verification_profile=request.verification_profile,
        acceptance_checks=checks,
        target_path=str(final_path),
        staging_path=str(staging_path),
        asset_hashes=dict(asset_set.hashes),
        pscad_version=asset_set.pscad_version,
        catalog_identity=catalog.identity,
        metadata=(
            {**payload["request"], "dynamic_control": payload["dynamic_control"]}
            if request.verification_profile == WP1C_DYNAMIC_PROFILE
            else payload["request"]
        ),
        master_sha256=payload.get("master_sha256"),
        master_binding_registry_sha256=payload.get(
            "master_binding_registry_sha256"
        ),
    )
