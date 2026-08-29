"""Strict, versioned logical-to-physical PSCAD Master bindings."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .backend.base import BackendError

_TOP_LEVEL_FIELDS = {"schema_version", "name", "pscad_version", "bindings"}
_BINDING_FIELDS = {
    "logical_name",
    "physical_definition",
    "shape",
    "ports",
    "parameters",
    "fixed_parameters",
    "evidence_parameters",
}
_PORT_FIELDS = {
    "logical",
    "physical",
    "kind",
    "dimension",
    "occurrence",
    "instance",
}
_PARAMETER_FIELDS = {
    "logical",
    "physical",
    "transform",
    "physical_contracts",
}
_FIXED_PARAMETER_FIELDS = {"physical", "value", "contract"}
_EVIDENCE_PARAMETER_FIELDS = {
    "logical",
    "type",
    "unit",
    "minimum",
    "maximum",
}
_CONTRACT_FIELDS = {"type", "unit", "choices"}
_SUPPORTED_SHAPES = {"direct", "phase_expand"}
_SUPPORTED_TRANSFORMS = {
    "identity",
    "scale",
    "lookup_bundle",
    "ratio_from_fixed_base",
    "harmonic_order",
    "evidence_only",
}
_TRANSFORM_FIELDS = {
    "identity": {"kind"},
    "scale": {"kind", "factor"},
    "lookup_bundle": {"kind", "cases"},
    "ratio_from_fixed_base": {"kind", "base"},
    "harmonic_order": {"kind", "fundamental_hz"},
    "evidence_only": {"kind"},
}


def _error(
    code: str,
    message: str,
    *,
    field: str | None = None,
    **details: Any,
) -> BackendError:
    if field is not None:
        details["field"] = field
    return BackendError(
        code,
        message,
        "master",
        "parse_master_binding_registry",
        details,
    )


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(
            "MASTER_BINDING_MISSING",
            f"{field} must be an object.",
            field=field,
        )
    return value


def _exact_fields(
    value: Mapping[str, Any],
    allowed: set[str],
    field: str,
    *,
    required: set[str] | None = None,
) -> None:
    unknown = sorted(set(value) - allowed)
    missing = sorted((required if required is not None else allowed) - set(value))
    if unknown or missing:
        raise _error(
            "MASTER_BINDING_MISSING",
            f"{field} has an invalid field set.",
            field=field,
            unknown_fields=unknown,
            missing_fields=missing,
        )


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(
            "MASTER_BINDING_MISSING",
            f"{field} must be a non-empty string.",
            field=field,
        )
    return value.strip()


def _number(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error(
            "MASTER_BINDING_MISSING",
            f"{field} must be numeric.",
            field=field,
        )
    result = float(value)
    if positive and result <= 0:
        raise _error(
            "MASTER_BINDING_MISSING",
            f"{field} must be positive.",
            field=field,
        )
    return result


def _integer(
    value: Any,
    field: str,
    *,
    minimum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "non-negative" if minimum == 0 else f"at least {minimum}"
        raise _error(
            "MASTER_BINDING_MISSING",
            f"{field} must be an integer that is {qualifier}.",
            field=field,
        )
    return value


def _sequence(value: Any, field: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise _error(
            "MASTER_BINDING_MISSING",
            f"{field} must be an array.",
            field=field,
        )
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class MasterPortBinding:
    logical: str
    physical: str
    kind: str
    dimension: int
    occurrence: int
    instance: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = {
            "logical": self.logical,
            "physical": self.physical,
            "kind": self.kind,
            "dimension": self.dimension,
            "occurrence": self.occurrence,
        }
        if self.instance is not None:
            value["instance"] = self.instance
        return value


@dataclass(frozen=True)
class MasterParameterBinding:
    logical: tuple[str, ...]
    physical: tuple[str, ...]
    transform: Mapping[str, Any]
    physical_contracts: Mapping[str, Mapping[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical": list(self.logical),
            "physical": list(self.physical),
            "transform": _thaw(self.transform),
            "physical_contracts": _thaw(self.physical_contracts),
        }


@dataclass(frozen=True)
class MasterFixedParameter:
    physical: str
    value: Any
    contract: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "physical": self.physical,
            "value": _thaw(self.value),
            "contract": _thaw(self.contract),
        }


@dataclass(frozen=True)
class MasterEvidenceParameter:
    logical: str
    type: str
    unit: str | None
    minimum: float | None = None
    maximum: float | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "logical": self.logical,
            "type": self.type,
            "unit": self.unit,
        }
        if self.minimum is not None:
            result["minimum"] = self.minimum
        if self.maximum is not None:
            result["maximum"] = self.maximum
        return result


@dataclass(frozen=True)
class MasterBinding:
    logical_name: str
    physical_definition: str
    shape: Mapping[str, Any]
    ports: tuple[MasterPortBinding, ...]
    parameters: tuple[MasterParameterBinding, ...]
    fixed_parameters: tuple[MasterFixedParameter, ...]
    evidence_parameters: tuple[MasterEvidenceParameter, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_name": self.logical_name,
            "physical_definition": self.physical_definition,
            "shape": _thaw(self.shape),
            "ports": [item.to_dict() for item in self.ports],
            "parameters": [item.to_dict() for item in self.parameters],
            "fixed_parameters": [item.to_dict() for item in self.fixed_parameters],
            "evidence_parameters": [
                item.to_dict() for item in self.evidence_parameters
            ],
        }


@dataclass(frozen=True)
class MasterBindingRegistry:
    schema_version: int
    name: str
    pscad_version: str
    bindings: tuple[MasterBinding, ...]
    sha256: str

    @property
    def by_logical_name(self) -> dict[str, MasterBinding]:
        return {item.logical_name: item for item in self.bindings}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "pscad_version": self.pscad_version,
            "bindings": [item.to_dict() for item in self.bindings],
        }


def _parse_contract(value: Any, field: str) -> Mapping[str, Any]:
    record = _mapping(value, field)
    _exact_fields(
        record,
        _CONTRACT_FIELDS,
        field,
        required={"type", "unit"},
    )
    contract: dict[str, Any] = {
        "type": _text(record.get("type"), f"{field}.type"),
        "unit": record.get("unit"),
    }
    if contract["unit"] is not None and not isinstance(contract["unit"], str):
        raise _error(
            "MASTER_BINDING_MISSING",
            f"{field}.unit must be a string or null.",
            field=f"{field}.unit",
        )
    if "choices" in record:
        choices = tuple(
            _text(item, f"{field}.choices")
            for item in _sequence(record["choices"], f"{field}.choices")
        )
        if not choices or len(choices) != len(set(choices)):
            raise _error(
                "MASTER_BINDING_MISSING",
                f"{field}.choices must be unique and non-empty.",
                field=f"{field}.choices",
            )
        contract["choices"] = choices
    return _freeze(contract)


def _parse_shape(value: Any) -> Mapping[str, Any]:
    record = _mapping(value, "shape")
    kind = record.get("kind")
    if kind not in _SUPPORTED_SHAPES:
        raise _error(
            "MASTER_BINDING_MISSING",
            "shape.kind is unsupported.",
            field="shape.kind",
            observed=kind,
        )
    if kind == "direct":
        _exact_fields(record, {"kind"}, "shape")
        return _freeze(dict(record))
    _exact_fields(record, {"kind", "instances", "neutral"}, "shape")
    parsed_instances: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, item in enumerate(_sequence(record["instances"], "shape.instances")):
        instance = _mapping(item, f"shape.instances[{index}]")
        _exact_fields(instance, {"name", "offset"}, f"shape.instances[{index}]")
        name = _text(instance["name"], f"shape.instances[{index}].name")
        offset = _sequence(instance["offset"], f"shape.instances[{index}].offset")
        if len(offset) != 2 or any(
            isinstance(coordinate, bool) or not isinstance(coordinate, int)
            for coordinate in offset
        ):
            raise _error(
                "MASTER_BINDING_MISSING",
                "shape instance offsets must contain two integers.",
                field="shape.instances.offset",
            )
        if name in names:
            raise _error(
                "MASTER_BINDING_AMBIGUOUS",
                f"Shape instance '{name}' is duplicated.",
                field="shape.instances.name",
                instance=name,
            )
        names.add(name)
        parsed_instances.append({"name": name, "offset": list(offset)})
    if not parsed_instances:
        raise _error(
            "MASTER_BINDING_MISSING",
            "phase_expand requires at least one instance.",
            field="shape.instances",
        )
    neutral = _mapping(record["neutral"], "shape.neutral")
    neutral_fields = {
        "physical_port",
        "occurrence",
        "ground_definition",
        "ground_port",
        "ground_occurrence",
        "ground_offset",
    }
    _exact_fields(neutral, neutral_fields, "shape.neutral")
    ground_offset = _sequence(neutral["ground_offset"], "shape.neutral.ground_offset")
    if len(ground_offset) != 2 or any(
        isinstance(coordinate, bool) or not isinstance(coordinate, int)
        for coordinate in ground_offset
    ):
        raise _error(
            "MASTER_BINDING_MISSING",
            "shape.neutral.ground_offset must contain two integers.",
            field="shape.neutral.ground_offset",
        )
    parsed_neutral = {
        "physical_port": _text(neutral["physical_port"], "shape.neutral.physical_port"),
        "occurrence": _integer(
            neutral["occurrence"], "shape.neutral.occurrence", minimum=0
        ),
        "ground_definition": _text(
            neutral["ground_definition"], "shape.neutral.ground_definition"
        ),
        "ground_port": _text(neutral["ground_port"], "shape.neutral.ground_port"),
        "ground_occurrence": _integer(
            neutral["ground_occurrence"],
            "shape.neutral.ground_occurrence",
            minimum=0,
        ),
        "ground_offset": list(ground_offset),
    }
    return _freeze(
        {"kind": kind, "instances": parsed_instances, "neutral": parsed_neutral}
    )


def _parse_port(value: Any, index: int) -> MasterPortBinding:
    field = f"ports[{index}]"
    record = _mapping(value, field)
    _exact_fields(
        record,
        _PORT_FIELDS,
        field,
        required=_PORT_FIELDS - {"instance"},
    )
    kind = _text(record["kind"], f"{field}.kind")
    if kind not in {"electrical", "data", "signal"}:
        raise _error(
            "MASTER_BINDING_MISSING",
            f"{field}.kind is unsupported.",
            field="kind",
            observed=kind,
        )
    instance = record.get("instance")
    if instance is not None:
        instance = _text(instance, f"{field}.instance")
    return MasterPortBinding(
        logical=_text(record["logical"], f"{field}.logical"),
        physical=_text(record["physical"], f"{field}.physical"),
        kind=kind,
        dimension=_integer(record["dimension"], "dimension", minimum=1),
        occurrence=_integer(record["occurrence"], "occurrence", minimum=0),
        instance=instance,
    )


def _parse_transform(value: Any) -> Mapping[str, Any]:
    record = _mapping(value, "transform")
    kind = record.get("kind")
    if kind not in _SUPPORTED_TRANSFORMS:
        raise _error(
            "MASTER_BINDING_MISSING",
            "transform.kind is unsupported.",
            field="transform.kind",
            observed=kind,
        )
    _exact_fields(record, _TRANSFORM_FIELDS[str(kind)], "transform")
    parsed = dict(record)
    if kind == "scale":
        parsed["factor"] = _number(record["factor"], "transform.factor")
        if parsed["factor"] == 0:
            raise _error(
                "MASTER_BINDING_MISSING",
                "transform.factor must not be zero.",
                field="transform.factor",
            )
    elif kind == "ratio_from_fixed_base":
        parsed["base"] = _number(
            record["base"], "transform.base", positive=True
        )
    elif kind == "harmonic_order":
        parsed["fundamental_hz"] = _number(
            record["fundamental_hz"],
            "transform.fundamental_hz",
            positive=True,
        )
    elif kind == "lookup_bundle":
        cases = []
        for index, item in enumerate(_sequence(record["cases"], "transform.cases")):
            case = _mapping(item, f"transform.cases[{index}]")
            _exact_fields(case, {"logical", "physical"}, f"transform.cases[{index}]")
            cases.append(
                {
                    "logical": list(
                        _sequence(case["logical"], f"transform.cases[{index}].logical")
                    ),
                    "physical": list(
                        _sequence(
                            case["physical"],
                            f"transform.cases[{index}].physical",
                        )
                    ),
                }
            )
        if not cases:
            raise _error(
                "MASTER_BINDING_MISSING",
                "lookup_bundle requires at least one case.",
                field="transform.cases",
            )
        parsed["cases"] = cases
    return _freeze(parsed)


def _parse_parameter(value: Any, index: int) -> MasterParameterBinding:
    field = f"parameters[{index}]"
    record = _mapping(value, field)
    _exact_fields(record, _PARAMETER_FIELDS, field)
    logical = tuple(
        _text(item, f"{field}.logical")
        for item in _sequence(record["logical"], f"{field}.logical")
    )
    physical = tuple(
        _text(item, f"{field}.physical")
        for item in _sequence(record["physical"], f"{field}.physical")
    )
    if not logical or not physical or len(logical) != len(set(logical)) or len(
        physical
    ) != len(set(physical)):
        raise _error(
            "MASTER_BINDING_MISSING",
            f"{field} names must be unique and non-empty.",
            field=field,
        )
    contracts_value = _mapping(
        record["physical_contracts"], f"{field}.physical_contracts"
    )
    if set(contracts_value) != set(physical):
        raise _error(
            "MASTER_BINDING_MISSING",
            f"{field}.physical_contracts must cover every physical parameter.",
            field=f"{field}.physical_contracts",
        )
    contracts = {
        name: _parse_contract(
            contracts_value[name], f"{field}.physical_contracts.{name}"
        )
        for name in physical
    }
    transform = _parse_transform(record["transform"])
    if transform["kind"] != "lookup_bundle" and (
        len(logical) != 1 or len(physical) != 1
    ):
        raise _error(
            "MASTER_BINDING_MISSING",
            f"{field} requires a one-to-one transform.",
            field=field,
        )
    if transform["kind"] == "lookup_bundle":
        for case in transform["cases"]:
            if len(case["logical"]) != len(logical) or len(case["physical"]) != len(
                physical
            ):
                raise _error(
                    "MASTER_BINDING_MISSING",
                    "lookup_bundle case arity does not match its names.",
                    field="transform.cases",
                )
    return MasterParameterBinding(
        logical=logical,
        physical=physical,
        transform=transform,
        physical_contracts=_freeze(contracts),
    )


def _parse_fixed(value: Any, index: int) -> MasterFixedParameter:
    field = f"fixed_parameters[{index}]"
    record = _mapping(value, field)
    _exact_fields(record, _FIXED_PARAMETER_FIELDS, field)
    return MasterFixedParameter(
        physical=_text(record["physical"], f"{field}.physical"),
        value=_freeze(record["value"]),
        contract=_parse_contract(record["contract"], f"{field}.contract"),
    )


def _parse_evidence(value: Any, index: int) -> MasterEvidenceParameter:
    field = f"evidence_parameters[{index}]"
    record = _mapping(value, field)
    _exact_fields(
        record,
        _EVIDENCE_PARAMETER_FIELDS,
        field,
        required={"logical", "type", "unit"},
    )
    unit = record["unit"]
    if unit is not None and not isinstance(unit, str):
        raise _error(
            "MASTER_BINDING_MISSING",
            f"{field}.unit must be a string or null.",
            field=f"{field}.unit",
        )
    minimum = (
        _number(record["minimum"], f"{field}.minimum")
        if "minimum" in record
        else None
    )
    maximum = (
        _number(record["maximum"], f"{field}.maximum")
        if "maximum" in record
        else None
    )
    if minimum is not None and maximum is not None and minimum > maximum:
        raise _error(
            "MASTER_BINDING_MISSING",
            f"{field} has an inverted range.",
            field=field,
        )
    return MasterEvidenceParameter(
        logical=_text(record["logical"], f"{field}.logical"),
        type=_text(record["type"], f"{field}.type"),
        unit=unit,
        minimum=minimum,
        maximum=maximum,
    )


def _parse_binding(value: Any, index: int) -> MasterBinding:
    field = f"bindings[{index}]"
    record = _mapping(value, field)
    _exact_fields(record, _BINDING_FIELDS, field)
    shape = _parse_shape(record["shape"])
    ports = tuple(
        _parse_port(item, port_index)
        for port_index, item in enumerate(_sequence(record["ports"], "ports"))
    )
    if not ports:
        raise _error(
            "MASTER_BINDING_MISSING",
            "Each binding requires at least one port.",
            field="ports",
        )
    logical_ports = [item.logical for item in ports]
    if len(logical_ports) != len(set(logical_ports)):
        raise _error(
            "MASTER_BINDING_AMBIGUOUS",
            "Logical port names must be unique within a binding.",
            field="ports.logical",
        )
    instance_names = {
        str(item["name"]) for item in shape.get("instances", ())
    }
    for port in ports:
        if shape["kind"] == "direct" and port.instance is not None:
            raise _error(
                "MASTER_BINDING_MISSING",
                "Direct bindings cannot declare a port instance.",
                field="ports.instance",
            )
        if shape["kind"] == "phase_expand" and port.instance not in instance_names:
            raise _error(
                "MASTER_BINDING_MISSING",
                "Expanded ports must reference a declared instance.",
                field="ports.instance",
                instance=port.instance,
            )
    parameters = tuple(
        _parse_parameter(item, parameter_index)
        for parameter_index, item in enumerate(
            _sequence(record["parameters"], "parameters")
        )
    )
    fixed = tuple(
        _parse_fixed(item, fixed_index)
        for fixed_index, item in enumerate(
            _sequence(record["fixed_parameters"], "fixed_parameters")
        )
    )
    evidence = tuple(
        _parse_evidence(item, evidence_index)
        for evidence_index, item in enumerate(
            _sequence(record["evidence_parameters"], "evidence_parameters")
        )
    )
    logical_parameters = [name for item in parameters for name in item.logical]
    logical_parameters.extend(item.logical for item in evidence)
    physical_parameters = [name for item in parameters for name in item.physical]
    physical_parameters.extend(item.physical for item in fixed)
    if len(logical_parameters) != len(set(logical_parameters)):
        raise _error(
            "MASTER_BINDING_AMBIGUOUS",
            "Logical parameter names must be unique within a binding.",
            field="parameters.logical",
        )
    if len(physical_parameters) != len(set(physical_parameters)):
        raise _error(
            "MASTER_BINDING_AMBIGUOUS",
            "Physical parameter names must be unique within a binding.",
            field="parameters.physical",
        )
    return MasterBinding(
        logical_name=_text(record["logical_name"], f"{field}.logical_name"),
        physical_definition=_text(
            record["physical_definition"], f"{field}.physical_definition"
        ),
        shape=shape,
        ports=ports,
        parameters=parameters,
        fixed_parameters=fixed,
        evidence_parameters=evidence,
    )


def parse_master_binding_registry(value: Any) -> MasterBindingRegistry:
    """Parse an exact registry schema and calculate its canonical hash."""

    record = _mapping(value, "registry")
    _exact_fields(record, _TOP_LEVEL_FIELDS, "registry")
    schema_version = record["schema_version"]
    if isinstance(schema_version, bool) or schema_version != 1:
        raise _error(
            "MASTER_BINDING_MISSING",
            "The Master binding registry schema version must be 1.",
            field="schema_version",
            observed=schema_version,
        )
    bindings = tuple(
        _parse_binding(item, index)
        for index, item in enumerate(_sequence(record["bindings"], "bindings"))
    )
    if not bindings:
        raise _error(
            "MASTER_BINDING_MISSING",
            "The Master binding registry must not be empty.",
            field="bindings",
        )
    observed: set[str] = set()
    for binding in bindings:
        if binding.logical_name in observed:
            raise _error(
                "MASTER_BINDING_AMBIGUOUS",
                f"Logical binding '{binding.logical_name}' is duplicated.",
                field="bindings.logical_name",
                logical_name=binding.logical_name,
            )
        observed.add(binding.logical_name)
    normalized = {
        "schema_version": schema_version,
        "name": _text(record["name"], "name"),
        "pscad_version": _text(record["pscad_version"], "pscad_version"),
        "bindings": [item.to_dict() for item in bindings],
    }
    canonical = json.dumps(
        normalized,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return MasterBindingRegistry(
        schema_version=schema_version,
        name=normalized["name"],
        pscad_version=normalized["pscad_version"],
        bindings=bindings,
        sha256=hashlib.sha256(canonical).hexdigest(),
    )


__all__ = [
    "MasterBinding",
    "MasterBindingRegistry",
    "MasterEvidenceParameter",
    "MasterFixedParameter",
    "MasterParameterBinding",
    "MasterPortBinding",
    "parse_master_binding_registry",
]
