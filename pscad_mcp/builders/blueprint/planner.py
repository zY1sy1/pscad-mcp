"""Deterministic, side-effect-free blueprint plan creation."""

from __future__ import annotations

from dataclasses import replace
import re
from typing import Any, Mapping

from ...core.backend.base import BackendError
from ...core.path_policy import PathPolicy
from .assets import BlueprintAsset, audit_source_package, canonical_json, sha256_bytes
from .inventory import InventorySnapshot
from .models import BlueprintOperation, BlueprintPlan, freeze, json_safe


_TARGET_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}\Z")


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "blueprint", "plan_pscad_project_build", details)


def _matches(component: Mapping[str, Any], selector: str) -> bool:
    return selector in {component["logical_id"], component["name"], str(component["id"])}


def _resolve_source(snapshot: InventorySnapshot, selector: str) -> Mapping[str, Any]:
    matches = [component for component in snapshot.components if _matches(component, selector)]
    if len(matches) > 1:
        raise _error("BLUEPRINT_SELECTOR_AMBIGUOUS", "A component selector matched more than one live component.", selector=selector)
    if not matches or not matches[0]["resolved"]:
        raise _error("BLUEPRINT_TARGET_UNRESOLVED", "A mutation target is missing or unresolved.", selector=selector)
    return matches[0]


def _parameter_contract(snapshot: InventorySnapshot, definition: str, name: str) -> Mapping[str, Any]:
    definition_contract = snapshot.definitions.get(definition)
    if not isinstance(definition_contract, Mapping):
        raise _error("BLUEPRINT_DEFINITION_MISSING", "A required component definition is not in the live inventory.", definition=definition)
    parameters = definition_contract.get("parameters")
    contract = parameters.get(name) if isinstance(parameters, Mapping) else None
    if not isinstance(contract, Mapping) or not contract.get("resolved"):
        raise _error("BLUEPRINT_TARGET_UNRESOLVED", "A mutated parameter is unresolved in the live definition.", definition=definition, parameter=name)
    return contract


def _validate_parameters(
    snapshot: InventorySnapshot,
    definition: str,
    parameters: Mapping[str, Any],
    units: Mapping[str, Any],
) -> None:
    for name in parameters:
        contract = _parameter_contract(snapshot, definition, name)
        if name in units and units[name] != contract.get("units"):
            raise _error(
                "BLUEPRINT_UNIT_MISMATCH",
                "A parameter unit does not match the live definition.",
                definition=definition,
                parameter=name,
                expected_units=contract.get("units"),
                observed_units=units[name],
            )


def _resolved_operations(
    asset: BlueprintAsset,
    snapshot: InventorySnapshot,
    parameter_overrides: Mapping[str, Mapping[str, Any]],
) -> tuple[tuple[BlueprintOperation, ...], dict[str, int], set[str]]:
    produced_definitions: dict[str, str] = {}
    selectors: dict[str, int] = {}
    touched_sources: set[str] = set()
    result: list[BlueprintOperation] = []
    override_targets = set(parameter_overrides)
    applied_overrides: set[str] = set()
    component_target_kinds = {"set_component_location", "rotate_component", "set_component_parameters"}
    for operation in asset.blueprint.operations:
        arguments = json_safe(operation.arguments)
        if operation.kind == "clone_component":
            source = _resolve_source(snapshot, operation.target)
            touched_sources.add(source["logical_id"])
            selectors[operation.target] = source["id"]
            logical_id = arguments.get("logical_id")
            if not isinstance(logical_id, str) or not logical_id or logical_id in produced_definitions:
                raise _error("BLUEPRINT_OPERATION_INVALID", "Clone operations require a unique logical_id.", operation_id=operation.operation_id)
            expected = arguments.get("expected_definition")
            if expected is not None and expected != source["definition"]:
                raise _error("BLUEPRINT_DEFINITION_MISSING", "Clone source definition differs from the blueprint contract.", operation_id=operation.operation_id)
            produced_definitions[logical_id] = source["definition"]
            arguments["source_component_id"] = source["id"]
        elif operation.kind == "create_component":
            logical_id = arguments.get("logical_id") or operation.target
            definition = arguments.get("definition") or arguments.get("expected_definition")
            if not isinstance(logical_id, str) or not logical_id or not isinstance(definition, str):
                raise _error("BLUEPRINT_OPERATION_INVALID", "Create operations require logical_id and definition.", operation_id=operation.operation_id)
            if definition not in snapshot.definitions:
                raise _error("BLUEPRINT_DEFINITION_MISSING", "Create definition is not in the live inventory.", definition=definition)
            produced_definitions[logical_id] = definition
        elif operation.kind in component_target_kinds and operation.target not in produced_definitions:
            source = _resolve_source(snapshot, operation.target)
            touched_sources.add(source["logical_id"])
            selectors[operation.target] = source["id"]
            produced_definitions.setdefault(operation.target, source["definition"])

        if operation.kind == "connect_ports":
            for endpoint_name in ("from", "to"):
                endpoint = arguments.get(endpoint_name)
                if not isinstance(endpoint, Mapping) or not isinstance(endpoint.get("logical_id"), str) or not isinstance(endpoint.get("port"), str):
                    raise _error("BLUEPRINT_OPERATION_INVALID", "Connection endpoints require logical_id and port.", operation_id=operation.operation_id)
                logical_id = endpoint["logical_id"]
                definition = produced_definitions.get(logical_id)
                if definition is None:
                    source = _resolve_source(snapshot, logical_id)
                    touched_sources.add(source["logical_id"])
                    selectors[logical_id] = source["id"]
                    definition = source["definition"]
                    produced_definitions[logical_id] = definition
                contract = snapshot.definitions.get(definition)
                ports = contract.get("ports") if isinstance(contract, Mapping) else None
                if not isinstance(ports, Mapping) or endpoint["port"] not in ports:
                    raise _error(
                        "BLUEPRINT_PORT_MISSING",
                        "A connection port is not declared by the live definition.",
                        operation_id=operation.operation_id,
                        logical_id=logical_id,
                        port=endpoint["port"],
                    )

        if operation.kind == "set_component_parameters":
            definition = produced_definitions.get(operation.target)
            if definition is None:
                raise _error("BLUEPRINT_TARGET_UNRESOLVED", "Parameter target has no resolved definition.", target=operation.target)
            parameters = arguments.get("parameters")
            units = arguments.get("units", {})
            if not isinstance(parameters, Mapping) or not isinstance(units, Mapping):
                raise _error("BLUEPRINT_OPERATION_INVALID", "Parameter operations require parameters and units objects.", operation_id=operation.operation_id)
            if operation.target in parameter_overrides:
                parameters = {**parameters, **parameter_overrides[operation.target]}
                arguments["parameters"] = parameters
                applied_overrides.add(operation.target)
            _validate_parameters(snapshot, definition, parameters, units)
        result.append(replace(operation, arguments=freeze(arguments)))
    if override_targets != applied_overrides:
        raise _error(
            "BLUEPRINT_OVERRIDE_INVALID",
            "Parameter overrides must target a declared set_component_parameters operation.",
            unknown_targets=sorted(override_targets - applied_overrides),
        )
    return tuple(result), selectors, touched_sources


def create_plan(
    asset: BlueprintAsset,
    source_path: str,
    target_name: str,
    inventory: InventorySnapshot,
    path_policy: PathPolicy,
    *,
    parameter_overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> BlueprintPlan:
    if not isinstance(target_name, str) or _TARGET_NAME.fullmatch(target_name) is None:
        raise _error("BLUEPRINT_TARGET_INVALID", "Target name must be a safe PSCAD project name.", target_name=target_name)
    if inventory.pscad_version not in asset.blueprint.identity.supported_pscad_versions:
        raise _error(
            "BLUEPRINT_PSCAD_VERSION_UNSUPPORTED",
            "The live PSCAD version is not supported by the blueprint.",
            observed=inventory.pscad_version,
            supported=list(asset.blueprint.identity.supported_pscad_versions),
        )
    overrides: Mapping[str, Mapping[str, Any]] = parameter_overrides or {}
    if not isinstance(overrides, Mapping) or any(not isinstance(key, str) or not isinstance(value, Mapping) for key, value in overrides.items()):
        raise _error("BLUEPRINT_OVERRIDE_INVALID", "Parameter overrides must map logical IDs to parameter objects.")
    try:
        canonical_json(overrides)
    except BackendError as error:
        raise _error("BLUEPRINT_OVERRIDE_INVALID", "Parameter overrides must contain finite JSON values.") from error
    source = audit_source_package(asset.blueprint, source_path, path_policy)
    operations, selectors, touched_sources = _resolved_operations(asset, inventory, overrides)
    warnings = tuple(
        f"unresolved source element left untouched: {component['logical_id']}"
        for component in inventory.components
        if not component["resolved"] and component["logical_id"] not in touched_sources
    )
    workspace = path_policy.workspace_root
    if workspace is None:
        raise _error("BLUEPRINT_WORKSPACE_REQUIRED", "A configured workspace is required for blueprint planning.")
    staging = (workspace / ".pscad-mcp" / "blueprint-builds" / "pending" / target_name).as_posix()
    unsigned = {
        "blueprint": asset.blueprint.to_dict(),
        "blueprint_hash": asset.hashes["blueprint.json"],
        "asset_hashes": json_safe(asset.hashes),
        "source_path": source.root,
        "source_entry_point": source.entry_point,
        "source_manifest": json_safe(source.package_hashes),
        "source_package_hash": source.package_hash,
        "inventory_hash": inventory.inventory_hash,
        "pscad_version": inventory.pscad_version,
        "target_name": target_name,
        "staging_path": staging,
        "resolved_selectors": selectors,
        "operations": [operation.to_dict() for operation in operations],
        "warnings": list(warnings),
        "parameter_overrides": json_safe(overrides),
    }
    plan_hash = sha256_bytes(canonical_json(unsigned))
    return BlueprintPlan(
        plan_hash,
        asset.blueprint,
        asset.hashes["blueprint.json"],
        freeze(asset.hashes),
        source.root,
        source.entry_point,
        freeze(source.package_hashes),
        source.package_hash,
        inventory.inventory_hash,
        inventory.pscad_version,
        target_name,
        staging,
        freeze(selectors),
        operations,
        warnings,
        freeze(overrides),
    )
