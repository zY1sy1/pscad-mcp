"""Strict, versioned logical-to-physical PSCAD Master bindings."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .backend.base import BackendError
from .definition_metadata import (
    DefinitionMetadata,
    ParameterMetadata,
    PortMetadata,
    read_definition_metadata_matches,
)

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


@dataclass(frozen=True)
class ResolvedMasterComponent:
    logical_name: str
    physical_definition: str
    physical_parameters: Mapping[str, Any]
    evidence_parameters: Mapping[str, Any]
    instances: tuple[str, ...]
    selected_ports: Mapping[str, Mapping[str, Any]]
    registry_sha256: str
    master_sha256: str
    _binding: MasterBinding

    def logical_parameters(self, observed: Mapping[str, Any]) -> dict[str, Any]:
        """Convert physical read-back values to the requested logical contract."""

        result: dict[str, Any] = dict(self.evidence_parameters)
        for parameter in self._binding.parameters:
            missing = [name for name in parameter.physical if name not in observed]
            if missing:
                raise _runtime_error(
                    "MASTER_READBACK_FAILED",
                    "Physical parameter read-back is incomplete.",
                    "reverse_master_parameters",
                    logical_name=self.logical_name,
                    missing_physical_parameters=missing,
                )
            physical_values = tuple(observed[name] for name in parameter.physical)
            logical_values = _reverse_transform(parameter, physical_values)
            result.update(zip(parameter.logical, logical_values))
        return result

    def to_evidence(self) -> dict[str, Any]:
        return {
            "logical_name": self.logical_name,
            "physical_definition": self.physical_definition,
            "physical_parameters": _thaw(self.physical_parameters),
            "evidence_parameters": _thaw(self.evidence_parameters),
            "instances": list(self.instances),
            "selected_ports": _thaw(self.selected_ports),
            "registry_sha256": self.registry_sha256,
            "master_sha256": self.master_sha256,
            "verification_state": "verified",
        }


@dataclass(frozen=True)
class AuditedMasterRegistry:
    registry: MasterBindingRegistry
    master_path: str
    master_sha256: str
    definitions: Mapping[str, Mapping[str, Any]]

    def resolve_component(
        self,
        logical_name: str,
        parameters: Mapping[str, Any],
    ) -> ResolvedMasterComponent:
        """Resolve one logical request to reviewed physical arguments."""

        try:
            binding = self.registry.by_logical_name[logical_name]
            definition_evidence = self.definitions[logical_name]
        except KeyError as error:
            raise _runtime_error(
                "MASTER_BINDING_MISSING",
                f"No verified Master binding exists for '{logical_name}'.",
                "resolve_master_component",
                logical_name=logical_name,
            ) from error
        if not isinstance(parameters, Mapping):
            raise _runtime_error(
                "MASTER_PARAMETER_MISMATCH",
                "Logical Master parameters must be an object.",
                "resolve_master_component",
                logical_name=logical_name,
            )
        expected = {
            name for item in binding.parameters for name in item.logical
        } | {item.logical for item in binding.evidence_parameters}
        observed = set(parameters)
        if observed != expected:
            raise _runtime_error(
                "MASTER_PARAMETER_MISMATCH",
                "Logical Master parameters do not match the binding contract.",
                "resolve_master_component",
                logical_name=logical_name,
                missing_parameters=sorted(expected - observed),
                unknown_parameters=sorted(observed - expected),
            )

        physical: dict[str, Any] = {
            item.physical: item.value for item in binding.fixed_parameters
        }
        for item in binding.parameters:
            logical_values = tuple(parameters[name] for name in item.logical)
            transformed = _forward_transform(
                logical_name,
                item,
                logical_values,
            )
            physical.update(zip(item.physical, transformed))
        evidence: dict[str, Any] = {}
        for contract in binding.evidence_parameters:
            value = parameters[contract.logical]
            _validate_evidence_value(logical_name, contract, value)
            evidence[contract.logical] = value
        instances = tuple(
            str(item["name"])
            for item in binding.shape.get("instances", ({"name": "default"},))
        )
        return ResolvedMasterComponent(
            logical_name=logical_name,
            physical_definition=binding.physical_definition,
            physical_parameters=_freeze(physical),
            evidence_parameters=_freeze(evidence),
            instances=instances,
            selected_ports=definition_evidence["selected_ports"],
            registry_sha256=self.registry.sha256,
            master_sha256=self.master_sha256,
            _binding=binding,
        )


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


def _runtime_error(
    code: str,
    message: str,
    operation: str,
    **details: Any,
) -> BackendError:
    return BackendError(code, message, "master", operation, details)


def _normalized_kind(port: PortMetadata) -> str:
    declared = (port.kind or "").strip().casefold()
    if declared in {"electrical", "natural"}:
        return "electrical"
    if declared in {"data", "signal", "transfer"}:
        return "data"
    model = (port.model or "").strip().casefold()
    if model == "natural":
        return "electrical"
    if model == "transfer":
        return "data"
    mode = (port.mode or "").strip().casefold()
    if mode == "electrical":
        return "electrical"
    return declared or model or "unknown"


def _normalized_dimension(port: PortMetadata) -> int:
    if port.dim in {None, 0} and _normalized_kind(port) == "electrical":
        return 1
    return int(port.dim or 1)


def _normalized_unit(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().casefold()
    aliases = {
        "p.u.": "pu",
        "p.u": "pu",
        "sec": "s",
    }
    return aliases.get(normalized, normalized)


def _select_port(
    metadata: DefinitionMetadata,
    binding: MasterBinding,
    logical_port: MasterPortBinding,
) -> PortMetadata:
    matches = [
        port for port in metadata.ports if port.name == logical_port.physical
    ]
    if logical_port.occurrence >= len(matches):
        code = "MASTER_BINDING_AMBIGUOUS" if matches else "MASTER_BINDING_MISSING"
        raise _runtime_error(
            code,
            "The physical port occurrence cannot be selected deterministically.",
            "audit_master_bindings",
            logical_name=binding.logical_name,
            physical_definition=binding.physical_definition,
            logical_port=logical_port.logical,
            physical_port=logical_port.physical,
            requested_occurrence=logical_port.occurrence,
            available_occurrences=len(matches),
        )
    selected = matches[logical_port.occurrence]
    observed_kind = _normalized_kind(selected)
    observed_dimension = _normalized_dimension(selected)
    if (
        observed_kind != logical_port.kind
        or observed_dimension != logical_port.dimension
    ):
        raise _runtime_error(
            "MASTER_PORT_MISMATCH",
            "The live Master port does not match the binding contract.",
            "audit_master_bindings",
            logical_name=binding.logical_name,
            physical_definition=binding.physical_definition,
            logical_port=logical_port.logical,
            physical_port=logical_port.physical,
            occurrence=logical_port.occurrence,
            expected_kind=logical_port.kind,
            observed_kind=observed_kind,
            expected_dimension=logical_port.dimension,
            observed_dimension=observed_dimension,
        )
    return selected


def _parameter_contracts(
    binding: MasterBinding,
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for parameter in binding.parameters:
        result.update(parameter.physical_contracts)
    for parameter in binding.fixed_parameters:
        result[parameter.physical] = parameter.contract
    return result


def _validate_parameter_contract(
    binding: MasterBinding,
    name: str,
    expected: Mapping[str, Any],
    observed: ParameterMetadata | None,
) -> None:
    if observed is None:
        raise _runtime_error(
            "MASTER_BINDING_MISSING",
            "A required physical parameter is absent from the live Master definition.",
            "audit_master_bindings",
            logical_name=binding.logical_name,
            physical_definition=binding.physical_definition,
            physical_parameter=name,
        )
    expected_type = str(expected["type"])
    observed_type = observed.type
    expected_unit = _normalized_unit(expected.get("unit"))
    observed_unit = _normalized_unit(observed.unit)
    expected_choices = tuple(str(item) for item in expected.get("choices", ()))
    mismatch = (
        observed_type is None
        or observed_type.casefold() != expected_type.casefold()
        or observed_unit != expected_unit
        or observed.readonly
        or (
            expected_choices
            and not set(expected_choices).issubset(set(observed.choices))
        )
    )
    if mismatch:
        raise _runtime_error(
            "MASTER_PARAMETER_MISMATCH",
            "The live Master parameter does not match the binding contract.",
            "audit_master_bindings",
            logical_name=binding.logical_name,
            physical_definition=binding.physical_definition,
            physical_parameter=name,
            expected_type=expected_type,
            observed_type=observed_type,
            expected_unit=expected_unit,
            observed_unit=observed_unit,
            expected_choices=list(expected_choices),
            observed_choices=list(observed.choices),
            observed_readonly=observed.readonly,
        )


def _port_evidence(port: PortMetadata) -> dict[str, Any]:
    return {
        "physical": port.name,
        "occurrence": port.occurrence,
        "kind": _normalized_kind(port),
        "dimension": _normalized_dimension(port),
        "raw_dimension": port.dim,
        "model": port.model,
        "type": port.type,
        "mode": port.mode,
        "condition": port.condition,
        "offset": [port.x, port.y],
    }


def _definition_evidence(
    binding: MasterBinding,
    metadata: DefinitionMetadata,
) -> dict[str, Any]:
    selected_ports = {
        logical_port.logical: {
            **_port_evidence(_select_port(metadata, binding, logical_port)),
            "instance": logical_port.instance,
        }
        for logical_port in binding.ports
    }
    contracts = _parameter_contracts(binding)
    for name, contract in contracts.items():
        _validate_parameter_contract(
            binding,
            name,
            contract,
            metadata.parameters.get(name),
        )
    result = {
        "logical_name": binding.logical_name,
        "physical_definition": binding.physical_definition,
        "description": metadata.description,
        "selected_ports": selected_ports,
        "parameter_contracts": _thaw(contracts),
        "parameter_transforms": [
            {
                "logical": list(item.logical),
                "physical": list(item.physical),
                "transform": _thaw(item.transform),
            }
            for item in binding.parameters
        ],
        "fixed_parameters": {
            item.physical: item.value for item in binding.fixed_parameters
        },
        "shape": _thaw(binding.shape),
        "verification_state": "verified",
    }
    if binding.shape["kind"] == "phase_expand":
        neutral = binding.shape["neutral"]
        neutral_binding = MasterPortBinding(
            logical="__neutral__",
            physical=str(neutral["physical_port"]),
            kind="electrical",
            dimension=1,
            occurrence=int(neutral["occurrence"]),
        )
        result["neutral_port"] = _port_evidence(
            _select_port(metadata, binding, neutral_binding)
        )
    return result


def audit_master_bindings(
    master_path: str | Path,
    registry: MasterBindingRegistry,
) -> AuditedMasterRegistry:
    """Verify registry records against an immutable live Master PSLX source."""

    if not isinstance(registry, MasterBindingRegistry):
        raise _runtime_error(
            "MASTER_BINDING_MISSING",
            "A parsed Master binding registry is required.",
            "audit_master_bindings",
        )
    path = Path(master_path).expanduser().resolve()
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise _runtime_error(
            "MASTER_BINDING_MISSING",
            "The live Master source could not be read.",
            "audit_master_bindings",
            path=str(path),
        ) from error
    source_hash = hashlib.sha256(payload).hexdigest()
    definitions: dict[str, Mapping[str, Any]] = {}
    for binding in registry.bindings:
        matches = read_definition_metadata_matches(path, binding.physical_definition)
        if not matches:
            raise _runtime_error(
                "MASTER_BINDING_MISSING",
                "The physical definition is absent from the live Master source.",
                "audit_master_bindings",
                logical_name=binding.logical_name,
                physical_definition=binding.physical_definition,
                path=str(path),
            )
        if len(matches) != 1:
            raise _runtime_error(
                "MASTER_BINDING_AMBIGUOUS",
                "The physical definition is duplicated in the live Master source.",
                "audit_master_bindings",
                logical_name=binding.logical_name,
                physical_definition=binding.physical_definition,
                matches=len(matches),
                path=str(path),
            )
        definitions[binding.logical_name] = _freeze(
            _definition_evidence(binding, matches[0])
        )
    return AuditedMasterRegistry(
        registry=registry,
        master_path=str(path),
        master_sha256=source_hash,
        definitions=_freeze(definitions),
    )


def _numeric(value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError("booleans are not numeric Master values")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        token = value.strip().split("[", 1)[0].strip()
        return float(token)
    raise TypeError(f"{type(value).__name__} is not numeric")


def _same_transform_value(left: Any, right: Any) -> bool:
    if left == right:
        return True
    try:
        return _numeric(left) == _numeric(right)
    except (TypeError, ValueError):
        return False


def _forward_transform(
    logical_name: str,
    parameter: MasterParameterBinding,
    values: tuple[Any, ...],
) -> tuple[Any, ...]:
    kind = parameter.transform["kind"]
    try:
        if kind == "identity":
            return values
        if kind == "scale":
            return (_numeric(values[0]) * float(parameter.transform["factor"]),)
        if kind == "ratio_from_fixed_base":
            return (_numeric(values[0]) * float(parameter.transform["base"]),)
        if kind == "harmonic_order":
            return (
                _numeric(values[0])
                / float(parameter.transform["fundamental_hz"]),
            )
        if kind == "lookup_bundle":
            for case in parameter.transform["cases"]:
                if all(
                    _same_transform_value(expected, observed)
                    for expected, observed in zip(case["logical"], values)
                ):
                    return tuple(case["physical"])
    except (TypeError, ValueError, ZeroDivisionError) as error:
        raise _runtime_error(
            "MASTER_TRANSFORM_UNSUPPORTED",
            "The logical Master value cannot be converted.",
            "resolve_master_component",
            logical_name=logical_name,
            logical_parameters=list(parameter.logical),
            values=list(values),
            transform=kind,
        ) from error
    raise _runtime_error(
        "MASTER_TRANSFORM_UNSUPPORTED",
        "The logical Master value has no reviewed conversion.",
        "resolve_master_component",
        logical_name=logical_name,
        logical_parameters=list(parameter.logical),
        values=list(values),
        transform=kind,
    )


def _reverse_transform(
    parameter: MasterParameterBinding,
    values: tuple[Any, ...],
) -> tuple[Any, ...]:
    kind = parameter.transform["kind"]
    try:
        if kind == "identity":
            return values
        if kind == "scale":
            return (_numeric(values[0]) / float(parameter.transform["factor"]),)
        if kind == "ratio_from_fixed_base":
            return (_numeric(values[0]) / float(parameter.transform["base"]),)
        if kind == "harmonic_order":
            return (
                _numeric(values[0])
                * float(parameter.transform["fundamental_hz"]),
            )
        if kind == "lookup_bundle":
            for case in parameter.transform["cases"]:
                if all(
                    _same_transform_value(expected, observed)
                    for expected, observed in zip(case["physical"], values)
                ):
                    return tuple(case["logical"])
    except (TypeError, ValueError, ZeroDivisionError) as error:
        raise _runtime_error(
            "MASTER_READBACK_FAILED",
            "The physical Master value cannot be converted back.",
            "reverse_master_parameters",
            physical_parameters=list(parameter.physical),
            values=list(values),
            transform=kind,
        ) from error
    raise _runtime_error(
        "MASTER_READBACK_FAILED",
        "The physical Master value has no reviewed reverse conversion.",
        "reverse_master_parameters",
        physical_parameters=list(parameter.physical),
        values=list(values),
        transform=kind,
    )


def _validate_evidence_value(
    logical_name: str,
    contract: MasterEvidenceParameter,
    value: Any,
) -> None:
    if contract.type == "float":
        try:
            numeric = _numeric(value)
        except (TypeError, ValueError) as error:
            raise _runtime_error(
                "MASTER_PARAMETER_MISMATCH",
                "An evidence-only Master parameter has the wrong type.",
                "resolve_master_component",
                logical_name=logical_name,
                logical_parameter=contract.logical,
                expected_type=contract.type,
            ) from error
        if contract.minimum is not None and numeric < contract.minimum:
            raise _runtime_error(
                "MASTER_PARAMETER_MISMATCH",
                "An evidence-only Master parameter is below its minimum.",
                "resolve_master_component",
                logical_name=logical_name,
                logical_parameter=contract.logical,
                minimum=contract.minimum,
                observed=numeric,
            )
        if contract.maximum is not None and numeric > contract.maximum:
            raise _runtime_error(
                "MASTER_PARAMETER_MISMATCH",
                "An evidence-only Master parameter exceeds its maximum.",
                "resolve_master_component",
                logical_name=logical_name,
                logical_parameter=contract.logical,
                maximum=contract.maximum,
                observed=numeric,
            )
        return
    if contract.type == "string" and isinstance(value, str):
        return
    raise _runtime_error(
        "MASTER_PARAMETER_MISMATCH",
        "An evidence-only Master parameter has an unsupported contract.",
        "resolve_master_component",
        logical_name=logical_name,
        logical_parameter=contract.logical,
        expected_type=contract.type,
    )


__all__ = [
    "AuditedMasterRegistry",
    "MasterBinding",
    "MasterBindingRegistry",
    "MasterEvidenceParameter",
    "MasterFixedParameter",
    "MasterParameterBinding",
    "MasterPortBinding",
    "ResolvedMasterComponent",
    "audit_master_bindings",
    "parse_master_binding_registry",
]
