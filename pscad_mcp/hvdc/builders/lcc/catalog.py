"""Exact PSCAD definition, port, and parameter contracts for LCC assets."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ....core.backend.base import BackendError


_CATALOG_KEYS = {"schema_version", "name", "pscad_version", "identity", "definitions"}
_DEFINITION_KEYS = {"scoped_name", "definition", "ports", "parameters", "bounding_box", "metadata"}
_PORT_KEYS = {"name", "kind", "dimension", "offset", "role"}
_PARAMETER_KEYS = {
    "name",
    "type",
    "minimum",
    "maximum",
    "min",
    "max",
    "enum",
    "allowed_values",
    "required",
    "default",
    "unit",
}


@dataclass(frozen=True)
class LccParameterSpec:
    name: str
    value_type: str
    minimum: int | float | None = None
    maximum: int | float | None = None
    enum: tuple[Any, ...] = ()
    required: bool = True
    default: Any = None
    has_default: bool = False
    unit: str | None = None


@dataclass(frozen=True)
class LccPortSpec:
    name: str
    kind: str
    dimension: int
    offset: tuple[int, int]
    role: str | None = None


@dataclass(frozen=True)
class LccDefinitionSpec:
    scoped_name: str
    ports: tuple[LccPortSpec, ...] = ()
    parameters: dict[str, LccParameterSpec] = field(default_factory=dict)
    bounding_box: tuple[int, int, int, int] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LccCatalog:
    schema_version: int
    name: str
    pscad_version: str
    identity: str
    definitions: dict[str, LccDefinitionSpec]


def _error(code: str, message: str, operation: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", operation, details)


def _invalid(message: str, **details: Any) -> BackendError:
    return _error("LCC_BLUEPRINT_INVALID", message, "parse_lcc_catalog", **details)


def _object(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{context} must be an object.", context=context)
    return value


def _keys(value: Mapping[str, Any], allowed: set[str], context: str) -> None:
    non_string = [key for key in value if not isinstance(key, str)]
    if non_string:
        raise _invalid(f"{context} keys must be strings.", context=context)
    unknown = sorted(key for key in value if key not in allowed)
    if unknown:
        raise _invalid(f"{context} contains unknown field(s): {', '.join(unknown)}", context=context, unknown=unknown)


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{context} must be a non-empty string.", context=context)
    return value.strip()


def _integer(value: Any, context: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(f"{context} must be an integer.", context=context)
    if positive and value <= 0:
        raise _invalid(f"{context} must be positive.", context=context)
    return value


def _number(value: Any, context: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(f"{context} must be numeric.", context=context)
    try:
        finite = math.isfinite(float(value))
    except (OverflowError, ValueError):
        finite = False
    if not finite:
        raise _invalid(f"{context} must be finite.", context=context)
    return value


def _sequence(value: Any, context: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise _invalid(f"{context} must be an array.", context=context)
    return value


def _json_value(value: Any, context: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _invalid(f"{context} must be finite.", context=context)
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise _invalid(f"{context} keys must be strings.", context=context)
        return {key: _json_value(item, f"{context}.{key}") for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item, f"{context}[{index}]") for index, item in enumerate(value)]
    raise _invalid(f"{context} must be JSON-safe.", context=context)


def _parse_port(value: Any, context: str) -> LccPortSpec:
    port = _object(value, context)
    _keys(port, _PORT_KEYS, context)
    for key in ("name", "kind", "dimension"):
        if key not in port:
            raise _invalid(f"{context} requires {key}.", context=context)
    offset = port.get("offset", (0, 0))
    point = _sequence(offset, f"{context}.offset")
    if len(point) != 2:
        raise _invalid(f"{context}.offset requires two coordinates.", context=context)
    return LccPortSpec(
        name=_text(port["name"], f"{context}.name"),
        kind=_text(port["kind"], f"{context}.kind"),
        dimension=_integer(port["dimension"], f"{context}.dimension", positive=True),
        offset=(
            _integer(point[0], f"{context}.offset[0]"),
            _integer(point[1], f"{context}.offset[1]"),
        ),
        role=None if port.get("role") is None else _text(port["role"], f"{context}.role"),
    )


def _parameter_value_type(value: Any, context: str) -> str:
    value_type = _text(value, context).casefold()
    aliases = {"int": "integer", "double": "float", "number": "number", "str": "string"}
    value_type = aliases.get(value_type, value_type)
    if value_type not in {"integer", "float", "number", "boolean", "string", "enum"}:
        raise _invalid(f"{context} has unsupported value type.", context=context, value_type=value_type)
    return value_type


def _parse_parameter(name: str, value: Any, context: str) -> LccParameterSpec:
    parameter = _object(value, context)
    _keys(parameter, _PARAMETER_KEYS, context)
    if "type" not in parameter:
        raise _invalid(f"{context} requires type.", context=context)
    minimum = parameter.get("minimum", parameter.get("min"))
    maximum = parameter.get("maximum", parameter.get("max"))
    if minimum is not None:
        minimum = _number(minimum, f"{context}.minimum")
    if maximum is not None:
        maximum = _number(maximum, f"{context}.maximum")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise _invalid(f"{context} minimum exceeds maximum.", context=context)
    enum_value = parameter.get("enum", parameter.get("allowed_values", ()))
    enum = tuple(_json_value(item, f"{context}.enum[{index}]") for index, item in enumerate(_sequence(enum_value, f"{context}.enum")))
    value_type = _parameter_value_type(parameter["type"], f"{context}.type")
    if value_type == "enum" and not enum:
        raise _invalid(f"{context}.enum must not be empty for enum parameters.", context=context)
    required = parameter.get("required", True)
    if not isinstance(required, bool):
        raise _invalid(f"{context}.required must be boolean.", context=context)
    has_default = "default" in parameter
    default = None if not has_default else _json_value(parameter["default"], f"{context}.default")
    return LccParameterSpec(
        name=name,
        value_type=value_type,
        minimum=minimum,
        maximum=maximum,
        enum=enum,
        required=required,
        default=default,
        has_default=has_default,
        unit=None if parameter.get("unit") is None else _text(parameter["unit"], f"{context}.unit"),
    )


def _parse_definition(value: Any, index: int, key_name: str | None = None) -> LccDefinitionSpec:
    context = f"definitions[{index}]"
    definition = _object(value, context)
    _keys(definition, _DEFINITION_KEYS, context)
    scoped_value = definition.get("scoped_name", definition.get("definition", key_name))
    scoped_name = _text(scoped_value, f"{context}.scoped_name")
    ports_value = _sequence(definition.get("ports", ()), f"{context}.ports")
    ports = tuple(_parse_port(port, f"{context}.ports[{port_index}]") for port_index, port in enumerate(ports_value))
    if len({port.name for port in ports}) != len(ports):
        raise _invalid(f"{context}.ports names must be unique.", context=context)
    parameters_value = definition.get("parameters", {})
    parameters: dict[str, LccParameterSpec] = {}
    if isinstance(parameters_value, Mapping):
        parameter_items = parameters_value.items()
    else:
        parameter_list = _sequence(parameters_value, f"{context}.parameters")
        parameter_items = []
        for parameter_index, item in enumerate(parameter_list):
            parameter = _object(item, f"{context}.parameters[{parameter_index}]")
            if "name" not in parameter:
                raise _invalid(f"{context}.parameters[{parameter_index}] requires name.", context=context)
            parameter_items.append((parameter["name"], parameter))
    for parameter_name, parameter_value in parameter_items:
        name = _text(parameter_name, f"{context}.parameters.name")
        if name in parameters:
            raise _invalid(f"{context} contains duplicate parameter '{name}'.", context=context)
        parameters[name] = _parse_parameter(name, parameter_value, f"{context}.parameters.{name}")
    bounding_box = definition.get("bounding_box")
    parsed_box = None
    if bounding_box is not None:
        box = _sequence(bounding_box, f"{context}.bounding_box")
        if len(box) != 4:
            raise _invalid(f"{context}.bounding_box requires four integers.", context=context)
        parsed_box = tuple(_integer(item, f"{context}.bounding_box[{box_index}]") for box_index, item in enumerate(box))
    metadata = definition.get("metadata", {})
    metadata_value = _json_value(metadata, f"{context}.metadata")
    if not isinstance(metadata_value, dict):
        raise _invalid(f"{context}.metadata must be an object.", context=context)
    return LccDefinitionSpec(
        scoped_name=scoped_name,
        ports=ports,
        parameters=parameters,
        bounding_box=parsed_box,
        metadata=metadata_value,
    )


def parse_catalog(data: Mapping[str, Any]) -> LccCatalog:
    catalog = _object(data, "catalog")
    _keys(catalog, _CATALOG_KEYS, "catalog")
    if "schema_version" not in catalog or isinstance(catalog["schema_version"], bool) or catalog["schema_version"] != 1:
        raise _invalid("catalog schema_version must be 1.", context="catalog")
    for key in ("name", "pscad_version", "identity", "definitions"):
        if key not in catalog:
            raise _invalid(f"catalog requires {key}.", context="catalog")
    name = _text(catalog["name"], "catalog.name")
    pscad_version = _text(catalog["pscad_version"], "catalog.pscad_version")
    identity = _text(catalog["identity"], "catalog.identity")
    definitions_value = catalog["definitions"]
    definitions: dict[str, LccDefinitionSpec] = {}
    if isinstance(definitions_value, Mapping):
        definition_items = list(definitions_value.items())
    else:
        definition_list = _sequence(definitions_value, "catalog.definitions")
        definition_items = [(None, item) for item in definition_list]
    for index, (key_name, definition_value) in enumerate(definition_items):
        definition = _parse_definition(definition_value, index, key_name if isinstance(key_name, str) else None)
        if definition.scoped_name in definitions:
            raise _invalid("catalog definition names must be unique.", scoped_name=definition.scoped_name)
        definitions[definition.scoped_name] = definition
    return LccCatalog(
        schema_version=1,
        name=name,
        pscad_version=pscad_version,
        identity=identity,
        definitions=definitions,
    )


def require_definition(catalog: LccCatalog, scoped_name: str) -> LccDefinitionSpec:
    if not isinstance(scoped_name, str) or scoped_name not in catalog.definitions:
        raise _error(
            "LCC_DEFINITION_MISSING",
            f"Definition '{scoped_name}' is not present in the exact catalog.",
            "require_lcc_definition",
            definition=scoped_name,
        )
    return catalog.definitions[scoped_name]


def require_port(
    definition_or_catalog: LccDefinitionSpec | LccCatalog,
    port_or_definition: str,
    *args: Any,
    kind: str | None = None,
    dimension: int | None = None,
) -> LccPortSpec:
    if isinstance(definition_or_catalog, LccCatalog):
        if not args:
            raise _error("LCC_PORT_MISMATCH", "A port name is required.", "require_lcc_port")
        definition = require_definition(definition_or_catalog, port_or_definition)
        port_name = args[0]
        positional = args[1:]
    else:
        definition = definition_or_catalog
        port_name = port_or_definition
        positional = args
    if positional:
        if kind is not None:
            raise _error("LCC_PORT_MISMATCH", "Port kind was specified twice.", "require_lcc_port")
        kind = positional[0]
    if len(positional) > 1:
        if dimension is not None:
            raise _error("LCC_PORT_MISMATCH", "Port dimension was specified twice.", "require_lcc_port")
        dimension = positional[1]
    if len(positional) > 2:
        raise _error("LCC_PORT_MISMATCH", "Too many port contract arguments.", "require_lcc_port")
    for port in definition.ports:
        if port.name == port_name:
            if kind is not None and port.kind != kind:
                break
            if dimension is not None and port.dimension != dimension:
                break
            return port
    raise _error(
        "LCC_PORT_MISMATCH",
        f"Port '{port_name}' does not match the exact contract.",
        "require_lcc_port",
        definition=definition.scoped_name,
        port=port_name,
        expected_kind=kind,
        expected_dimension=dimension,
    )


def _resolve_parameter_definition(
    definition_or_catalog: LccDefinitionSpec | LccCatalog,
    values_or_definition: Mapping[str, Any] | str,
    values: Mapping[str, Any] | None,
) -> tuple[LccDefinitionSpec, Mapping[str, Any]]:
    if isinstance(definition_or_catalog, LccCatalog):
        if not isinstance(values_or_definition, str) or values is None:
            raise _error("LCC_PARAMETER_MISMATCH", "Catalog validation requires a definition name and values.", "validate_lcc_parameters")
        return require_definition(definition_or_catalog, values_or_definition), values
    if values is not None:
        raise _error("LCC_PARAMETER_MISMATCH", "Values were specified twice.", "validate_lcc_parameters")
    if not isinstance(values_or_definition, Mapping):
        raise _error("LCC_PARAMETER_MISMATCH", "Parameter values must be an object.", "validate_lcc_parameters")
    return definition_or_catalog, values_or_definition


def validate_parameters(
    definition_or_catalog: LccDefinitionSpec | LccCatalog,
    values_or_definition: Mapping[str, Any] | str,
    values: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    definition, requested = _resolve_parameter_definition(definition_or_catalog, values_or_definition, values)
    unknown = sorted(key for key in requested if key not in definition.parameters)
    if unknown:
        raise _error(
            "LCC_PARAMETER_MISMATCH",
            "The request contains unknown exact parameter names.",
            "validate_lcc_parameters",
            definition=definition.scoped_name,
            unknown=unknown,
        )
    normalized: dict[str, Any] = {}
    for name, spec in definition.parameters.items():
        if name not in requested:
            if spec.has_default:
                value = spec.default
            elif spec.required:
                raise _error(
                    "LCC_PARAMETER_MISMATCH",
                    f"Required parameter '{name}' is missing.",
                    "validate_lcc_parameters",
                    definition=definition.scoped_name,
                    parameter=name,
                )
            else:
                continue
        else:
            value = requested[name]
        try:
            if spec.value_type == "integer":
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError
                converted = value
            elif spec.value_type in {"float", "number"}:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise ValueError
                converted = float(value) if spec.value_type == "float" else value
            elif spec.value_type == "boolean":
                if not isinstance(value, bool):
                    raise ValueError
                converted = value
            elif spec.value_type == "string":
                if not isinstance(value, str):
                    raise ValueError
                converted = value
            else:
                if value not in spec.enum:
                    raise ValueError
                converted = value
            if spec.minimum is not None and converted < spec.minimum:
                raise ValueError
            if spec.maximum is not None and converted > spec.maximum:
                raise ValueError
            if spec.enum and spec.value_type != "enum" and converted not in spec.enum:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            raise _error(
                "LCC_PARAMETER_MISMATCH",
                f"Parameter '{name}' does not match its exact contract.",
                "validate_lcc_parameters",
                definition=definition.scoped_name,
                parameter=name,
                value=value,
            ) from None
        normalized[name] = converted
    return normalized

