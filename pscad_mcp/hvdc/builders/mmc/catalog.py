"""Exact definition, port, and parameter contracts used by the MMC planner."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ....core.backend.base import BackendError


@dataclass(frozen=True)
class MmcPortSpec:
    name: str
    kind: str
    dimension: int
    offset: tuple[int, int] = (0, 0)
    role: str | None = None


@dataclass(frozen=True)
class MmcParameterSpec:
    name: str
    value_type: str = "number"
    minimum: int | float | None = None
    maximum: int | float | None = None
    required: bool = True
    default: Any = None
    has_default: bool = False


@dataclass(frozen=True)
class MmcDefinitionSpec:
    scoped_name: str
    ports: tuple[MmcPortSpec, ...] = ()
    parameters: dict[str, MmcParameterSpec] = field(default_factory=dict)
    bounding_box: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class MmcCatalog:
    schema_version: int
    name: str
    pscad_version: str
    identity: str
    definitions: dict[str, MmcDefinitionSpec]


def _error(code: str, message: str, operation: str = "parse_mmc_catalog", **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", operation, details)


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error("MMC_BLUEPRINT_INVALID", f"{context} must be a non-empty string.", context=context)
    return value.strip()


def _integer(value: Any, context: str, *, positive: bool = False) -> int:
    if isinstance(value, str) and re.fullmatch(r"[+]?[0-9]+", value.strip()):
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or positive and value <= 0:
        raise _error("MMC_BLUEPRINT_INVALID", f"{context} must be a {'positive ' if positive else ''}integer.", context=context)
    return value


def _number(value: Any, context: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise _error("MMC_BLUEPRINT_INVALID", f"{context} must be finite numeric.", context=context)
    return value


def parse_catalog(data: Mapping[str, Any]) -> MmcCatalog:
    if not isinstance(data, Mapping):
        raise _error("MMC_BLUEPRINT_INVALID", "catalog must be an object.")
    if data.get("schema_version") != 1:
        raise _error("MMC_BLUEPRINT_INVALID", "catalog schema_version must be 1.")
    version = _text(data.get("pscad_version"), "catalog.pscad_version")
    if version != "4.6.2":
        raise _error("MMC_VERSION_UNSUPPORTED", "MMC catalog requires PSCAD 4.6.2.", observed_version=version)
    definitions_value = data.get("definitions")
    if not isinstance(definitions_value, Mapping):
        raise _error("MMC_BLUEPRINT_INVALID", "catalog.definitions must be an object.")
    definitions: dict[str, MmcDefinitionSpec] = {}
    for scoped_name, raw in definitions_value.items():
        name = _text(scoped_name, "catalog.definition.name")
        if not isinstance(raw, Mapping):
            raise _error("MMC_BLUEPRINT_INVALID", f"catalog definition {name} must be an object.")
        ports_value = raw.get("ports", ())
        if isinstance(ports_value, Mapping):
            ports_iter = [{"name": port_name, **port_value} for port_name, port_value in ports_value.items() if isinstance(port_value, Mapping)]
        elif isinstance(ports_value, Sequence) and not isinstance(ports_value, (str, bytes, bytearray)):
            ports_iter = list(ports_value)
        else:
            raise _error("MMC_BLUEPRINT_INVALID", f"catalog definition {name}.ports must be an array or object.")
        ports: list[MmcPortSpec] = []
        for index, port_value in enumerate(ports_iter):
            if not isinstance(port_value, Mapping):
                raise _error("MMC_BLUEPRINT_INVALID", f"catalog definition {name}.ports[{index}] must be an object.")
            port_name = _text(port_value.get("name"), f"catalog definition {name}.ports[{index}].name")
            kind = _text(port_value.get("kind", "signal"), f"catalog definition {name}.ports[{index}].kind")
            dimension = _integer(port_value.get("dimension", 1), f"catalog definition {name}.ports[{index}].dimension", positive=True)
            offset_value = port_value.get("offset", (0, 0))
            if not isinstance(offset_value, Sequence) or isinstance(offset_value, (str, bytes, bytearray)) or len(offset_value) != 2:
                raise _error("MMC_BLUEPRINT_INVALID", f"catalog definition {name}.ports[{index}].offset must contain two coordinates.")
            offset = (_integer(offset_value[0], "port.offset.x"), _integer(offset_value[1], "port.offset.y"))
            ports.append(MmcPortSpec(port_name, kind, dimension, offset, None if port_value.get("role") is None else _text(port_value["role"], "port.role")))
        if len({port.name for port in ports}) != len(ports):
            raise _error("MMC_BLUEPRINT_INVALID", f"catalog definition {name} has duplicate ports.")
        parameters_value = raw.get("parameters", {})
        parameters: dict[str, MmcParameterSpec] = {}
        if isinstance(parameters_value, Mapping):
            items = parameters_value.items()
        elif isinstance(parameters_value, Sequence) and not isinstance(parameters_value, (str, bytes, bytearray)):
            items = ((item.get("name"), item) for item in parameters_value if isinstance(item, Mapping))
        else:
            raise _error("MMC_BLUEPRINT_INVALID", f"catalog definition {name}.parameters must be an object or array.")
        for parameter_name, parameter_value in items:
            parameter = _text(parameter_name, f"catalog definition {name}.parameter.name")
            if not isinstance(parameter_value, Mapping):
                raise _error("MMC_BLUEPRINT_INVALID", f"catalog parameter {parameter} must be an object.")
            minimum = parameter_value.get("minimum", parameter_value.get("min"))
            maximum = parameter_value.get("maximum", parameter_value.get("max"))
            if minimum is not None:
                minimum = _number(minimum, f"catalog parameter {parameter}.minimum")
            if maximum is not None:
                maximum = _number(maximum, f"catalog parameter {parameter}.maximum")
            parameters[parameter] = MmcParameterSpec(parameter, _text(parameter_value.get("type", "number"), f"catalog parameter {parameter}.type"), minimum, maximum, bool(parameter_value.get("required", True)), parameter_value.get("default"), "default" in parameter_value)
        box_value = raw.get("bounding_box")
        box = None
        if box_value is not None:
            if not isinstance(box_value, Sequence) or isinstance(box_value, (str, bytes, bytearray)) or len(box_value) != 4:
                raise _error("MMC_BLUEPRINT_INVALID", f"catalog definition {name}.bounding_box must contain four integers.")
            box = tuple(_integer(item, f"catalog definition {name}.bounding_box[{index}]") for index, item in enumerate(box_value))
        definitions[name] = MmcDefinitionSpec(name, tuple(ports), parameters, box)
    return MmcCatalog(
        schema_version=1,
        name=_text(data.get("name", data.get("scope", "cigre_b4_p2p_avm_v1")), "catalog.name"),
        pscad_version=version,
        identity=_text(data.get("identity", f"{data.get('name', data.get('scope', 'mmc'))}/catalog-pscad-{version}"), "catalog.identity"),
        definitions=definitions,
    )


def require_definition(catalog: MmcCatalog, scoped_name: str) -> MmcDefinitionSpec:
    if scoped_name not in catalog.definitions:
        raise _error("MMC_DEFINITION_MISSING", f"Definition '{scoped_name}' is not in the exact catalog.", "require_mmc_definition", definition=scoped_name)
    return catalog.definitions[scoped_name]


def require_port(definition: MmcDefinitionSpec, port_name: str, *, kind: str | None = None, dimension: int | None = None) -> MmcPortSpec:
    for port in definition.ports:
        if port.name == port_name:
            if kind is not None and port.kind != kind:
                break
            if dimension is not None and port.dimension != dimension:
                break
            return port
    raise _error("MMC_PORT_MISMATCH", f"Port '{port_name}' does not match the exact catalog contract.", "require_mmc_port", definition=definition.scoped_name, port=port_name, expected_kind=kind, expected_dimension=dimension)


def validate_parameters(definition: MmcDefinitionSpec, requested: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(requested, Mapping):
        raise _error("MMC_PARAMETER_MISMATCH", "component parameters must be an object.", "validate_mmc_parameters", definition=definition.scoped_name)
    if not definition.parameters:
        return dict(requested)
    unknown = sorted(key for key in requested if key not in definition.parameters)
    if unknown:
        raise _error("MMC_PARAMETER_MISMATCH", "unknown component parameters.", "validate_mmc_parameters", definition=definition.scoped_name, unknown=unknown)
    normalized: dict[str, Any] = {}
    for name, spec in definition.parameters.items():
        if name not in requested:
            if spec.has_default:
                value = spec.default
            elif spec.required:
                raise _error("MMC_PARAMETER_MISMATCH", f"required parameter '{name}' is missing.", "validate_mmc_parameters", definition=definition.scoped_name, parameter=name)
            else:
                continue
        else:
            value = requested[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise _error("MMC_PARAMETER_MISMATCH", f"parameter '{name}' is not finite numeric.", "validate_mmc_parameters", definition=definition.scoped_name, parameter=name)
        if spec.minimum is not None and value < spec.minimum or spec.maximum is not None and value > spec.maximum:
            raise _error("MMC_PARAMETER_MISMATCH", f"parameter '{name}' is outside its exact range.", "validate_mmc_parameters", definition=definition.scoped_name, parameter=name, value=value)
        normalized[name] = value
    return normalized


__all__ = ["MmcCatalog", "MmcDefinitionSpec", "MmcParameterSpec", "MmcPortSpec", "parse_catalog", "require_definition", "require_port", "validate_parameters"]
