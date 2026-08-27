"""Normalized live definition and component inventory for blueprint planning."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any, Mapping

from ...core.backend.base import BackendError
from .assets import canonical_json, sha256_bytes
from .models import FrozenDict, freeze, json_safe


def _error(message: str, **details: Any) -> BackendError:
    return BackendError("BLUEPRINT_INVENTORY_INVALID", message, "blueprint", "normalize_inventory", details)


def _finite_json(value: Any) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _error("Live inventory contains a non-finite number.")
        return
    if isinstance(value, list):
        for item in value:
            _finite_json(item)
        return
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise _error("Live inventory mapping keys must be strings.")
        for item in value.values():
            _finite_json(item)
        return
    raise _error("Live inventory contains a non-JSON value.", value_type=type(value).__name__)


@dataclass(frozen=True)
class InventorySnapshot:
    pscad_version: str
    definitions: FrozenDict
    components: tuple[FrozenDict, ...]
    inventory_hash: str

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "pscad_version": self.pscad_version,
            "definitions": json_safe(self.definitions),
            "components": json_safe(self.components),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "inventory_hash": self.inventory_hash}


def normalize_inventory(value: Any) -> InventorySnapshot:
    if not isinstance(value, Mapping) or set(value) != {"pscad_version", "definitions", "components"}:
        raise _error("Live inventory must contain pscad_version, definitions, and components.")
    version = value["pscad_version"]
    definitions = value["definitions"]
    components = value["components"]
    if not isinstance(version, str) or not version:
        raise _error("Live inventory PSCAD version must be a non-empty string.")
    if not isinstance(definitions, Mapping) or not all(isinstance(key, str) and key for key in definitions):
        raise _error("Live definitions must be a name-keyed object.")
    if not isinstance(components, list):
        raise _error("Live components must be an array.")
    _finite_json(value)
    identifiers: list[int] = []
    normalized_components: list[Mapping[str, Any]] = []
    required = {
        "id", "logical_id", "name", "definition", "canvas", "location", "orientation",
        "parameters", "parameter_metadata", "ports", "resolved",
    }
    for index, component in enumerate(components):
        if not isinstance(component, Mapping) or set(component) != required:
            raise _error("Live component fields are not exact.", index=index)
        component_id = component["id"]
        location = component["location"]
        if not isinstance(component_id, int) or isinstance(component_id, bool) or component_id < 0:
            raise _error("Live component ID must be a non-negative integer.", index=index)
        if (
            not isinstance(location, list)
            or len(location) != 2
            or any(not isinstance(item, int) or isinstance(item, bool) for item in location)
        ):
            raise _error("Live component location must contain two integers.", index=index)
        if not isinstance(component["resolved"], bool):
            raise _error("Live component resolved flag must be boolean.", index=index)
        for field in ("logical_id", "name", "definition", "canvas"):
            if not isinstance(component[field], str) or not component[field]:
                raise _error(f"Live component {field} must be a non-empty string.", index=index)
        for field in ("parameters", "parameter_metadata", "ports"):
            if not isinstance(component[field], Mapping):
                raise _error(f"Live component {field} must be an object.", index=index)
        identifiers.append(component_id)
        normalized_components.append(component)
    if len(set(identifiers)) != len(identifiers):
        raise _error("Live component IDs must be unique.")
    unsigned = {
        "pscad_version": version,
        "definitions": json_safe(definitions),
        "components": json_safe(normalized_components),
    }
    return InventorySnapshot(version, freeze(definitions), freeze(normalized_components), sha256_bytes(canonical_json(unsigned)))


async def read_live_inventory(service: Any, project_name: str, inspection_profile: str | None = None) -> InventorySnapshot:
    bridge = getattr(service, "get_blueprint_inventory", None)
    if callable(bridge):
        return normalize_inventory(await bridge(project_name, inspection_profile))
    components = await service.list_canvas_components(project_name, canvas_name="Main")
    definitions = await service.get_project_definitions(project_name)
    status = await service.get_pscad_status()
    normalized_definitions = {
        name: {"ports": {}, "parameters": {}}
        for name in definitions
    }
    normalized_components = []
    for component in components:
        component_id = int(component["id"])
        parameters = await service.get_component_parameters(project_name, component_id)
        ports = await service.get_component_ports(project_name, component_id)
        location = await service.get_component_location(project_name, component_id)
        normalized_components.append(
            {
                "id": component_id,
                "logical_id": str(component.get("logical_id") or component.get("name") or component_id),
                "name": str(component.get("name") or component_id),
                "definition": str(component.get("definition") or "unresolved"),
                "canvas": str(component.get("canvas") or "Main"),
                "location": [int(location["x"]), int(location["y"])],
                "orientation": int(component.get("orientation", 0)),
                "parameters": parameters,
                "parameter_metadata": {name: {"resolved": True, "units": None} for name in parameters},
                "ports": ports,
                "resolved": component.get("definition") is not None,
            }
        )
    version = status.get("version") or status.get("pscad_version")
    return normalize_inventory({"pscad_version": version, "definitions": normalized_definitions, "components": normalized_components})

