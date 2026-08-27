"""Immutable request, design, plan, scenario, and build records for MMC."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ....core.backend.base import BackendError
from ..common.records import JsonRecord, freeze


_FIDELITIES = {"detailed_pwm", "average_value", "both"}
_TOPOLOGIES = {"two_terminal_symmetrical_monopole"}
_CONVERTERS = {"half_bridge"}
_LINK_KINDS = {"overhead_line", "cable"}
_UNITS = {
    "A", "F", "H", "Hz", "J", "V", "W", "kA", "kV", "kW", "km", "mH",
    "ms", "MW", "Mvar", "ohm", "pu", "s", "uF", "%",
}


def _invalid(message: str, **details: object) -> BackendError:
    return BackendError("MMC_REQUEST_INVALID", message, "hvdc", "parse_parametric_mmc_request", details)


def _mapping(value: Any, context: str, allowed: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{context} must be an object.", field=context)
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise _invalid(f"{context} contains unknown fields.", field=context, unknown=unknown)
    return value


def _number(value: Any, context: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise _invalid(f"{context} must be a finite number.", field=context)
    result = float(value)
    if positive and result <= 0:
        raise _invalid(f"{context} must be positive.", field=context)
    return result


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{context} must be a non-empty string.", field=context)
    return value.strip()


@dataclass(frozen=True)
class MmcGridRequest(JsonRecord):
    ac_voltage_kv: float
    short_circuit_ratio: float
    x_over_r: float


@dataclass(frozen=True)
class MmcDcLinkRequest(JsonRecord):
    kind: str
    length_km: float


@dataclass(frozen=True)
class MmcParametricRequest(JsonRecord):
    schema_version: int
    model_fidelity: str
    topology: str
    converter: str
    dc_voltage_kv: float
    active_power_mw: float
    reactive_power_mvar: float
    frequency_hz: float
    station_p: MmcGridRequest
    station_vdc: MmcGridRequest
    dc_link: MmcDcLinkRequest
    power_reversal_time_s: float
    engineering_overrides: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "engineering_overrides", freeze(self.engineering_overrides))


@dataclass(frozen=True)
class MmcConstraintResult(JsonRecord):
    name: str
    passed: bool
    value: float | int | None = None
    limit: float | int | str | None = None
    units: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class MmcCandidate(JsonRecord):
    candidate_id: str
    engine: str
    purpose: str
    parameters: dict[str, Any]
    settings: dict[str, Any] = field(default_factory=dict)
    constraints: tuple[MmcConstraintResult, ...] = ()
    parameter_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", freeze(self.parameters))
        object.__setattr__(self, "settings", freeze(self.settings))
        object.__setattr__(self, "constraints", tuple(self.constraints))


@dataclass(frozen=True)
class MmcDerivedParameters(JsonRecord):
    equation_version: str
    model_fidelity: str
    request: MmcParametricRequest
    common: dict[str, Any]
    candidates: tuple[MmcCandidate, ...]
    constraints: tuple[MmcConstraintResult, ...] = ()
    feasible: bool = True
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "common", freeze(self.common))
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "constraints", tuple(self.constraints))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


@dataclass(frozen=True)
class MmcEnginePlan(JsonRecord):
    engine: str
    target_name: str
    target_path: str
    workspace: str
    candidates: tuple[MmcCandidate, ...]
    plan_hash: str
    source_hashes: dict[str, str] = field(default_factory=dict)
    asset_hashes: dict[str, str] = field(default_factory=dict)
    source_bindings: tuple[dict[str, Any], ...] = ()
    dependencies: tuple[dict[str, Any], ...] = ()
    operations: tuple[dict[str, Any], ...] = ()
    settings: dict[str, Any] = field(default_factory=dict)
    scenarios: tuple[str, ...] = ()
    capabilities: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "source_hashes", freeze(self.source_hashes))
        object.__setattr__(self, "asset_hashes", freeze(self.asset_hashes))
        object.__setattr__(self, "source_bindings", freeze(self.source_bindings))
        object.__setattr__(self, "dependencies", freeze(self.dependencies))
        object.__setattr__(self, "operations", freeze(self.operations))
        object.__setattr__(self, "settings", freeze(self.settings))
        object.__setattr__(self, "scenarios", tuple(self.scenarios))
        object.__setattr__(self, "capabilities", freeze(self.capabilities))


@dataclass(frozen=True)
class MmcParentPlan(JsonRecord):
    request: MmcParametricRequest
    project_name: str
    workspace: str
    equation_version: str
    engine_plans: tuple[MmcEnginePlan, ...]
    plan_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "engine_plans", tuple(self.engine_plans))


@dataclass(frozen=True)
class MmcScenarioRecommendation(JsonRecord):
    name: str
    engine: str
    scenario: dict[str, Any]
    time_step_s: float
    duration_s: float
    capabilities: dict[str, Any]
    preconditions: tuple[str, ...] = ()
    metrics: tuple[dict[str, Any], ...] = ()
    thresholds: dict[str, Any] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario", freeze(self.scenario))
        object.__setattr__(self, "capabilities", freeze(self.capabilities))
        object.__setattr__(self, "preconditions", tuple(self.preconditions))
        object.__setattr__(self, "metrics", freeze(self.metrics))
        object.__setattr__(self, "thresholds", freeze(self.thresholds))
        object.__setattr__(self, "limitations", tuple(self.limitations))


@dataclass(frozen=True)
class MmcAdjustment(JsonRecord):
    category: str
    changes: dict[str, Any]
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "changes", freeze(self.changes))


@dataclass(frozen=True)
class MmcParametricBuildRecord(JsonRecord):
    build_id: str
    state: str
    plan_hash: str
    workspace: str
    engines: tuple[dict[str, Any], ...] = ()
    history: tuple[dict[str, Any], ...] = ()
    error: dict[str, Any] | None = None
    result: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "engines", freeze(self.engines))
        object.__setattr__(self, "history", freeze(self.history))
        object.__setattr__(self, "error", freeze(self.error))
        object.__setattr__(self, "result", freeze(self.result))


def _parse_grid(value: Any, context: str) -> MmcGridRequest:
    raw = _mapping(value, context, {"ac_voltage_kv", "short_circuit_ratio", "x_over_r"})
    required = {"ac_voltage_kv", "short_circuit_ratio", "x_over_r"}
    missing = sorted(required - set(raw))
    if missing:
        raise _invalid(f"{context} is missing required fields.", field=context, missing=missing)
    return MmcGridRequest(
        ac_voltage_kv=_number(raw["ac_voltage_kv"], f"{context}.ac_voltage_kv", positive=True),
        short_circuit_ratio=_number(raw["short_circuit_ratio"], f"{context}.short_circuit_ratio", positive=True),
        x_over_r=_number(raw["x_over_r"], f"{context}.x_over_r", positive=True),
    )


def _parse_link(value: Any) -> MmcDcLinkRequest:
    raw = _mapping(value, "dc_link", {"kind", "length_km"})
    missing = sorted({"kind", "length_km"} - set(raw))
    if missing:
        raise _invalid("dc_link is missing required fields.", field="dc_link", missing=missing)
    kind = _text(raw["kind"], "dc_link.kind")
    if kind not in _LINK_KINDS:
        raise _invalid("dc_link.kind is unsupported.", field="dc_link.kind", value=kind)
    return MmcDcLinkRequest(kind, _number(raw["length_km"], "dc_link.length_km", positive=True))


def _parse_overrides(value: Any) -> dict[str, Any]:
    raw = _mapping(value, "engineering_overrides", set(value) if isinstance(value, Mapping) else set())
    result: dict[str, Any] = {}
    for name, item in raw.items():
        override = _mapping(item, f"engineering_overrides.{name}", {"value", "unit"})
        if set(override) != {"value", "unit"}:
            raise _invalid("Engineering overrides require value and unit.", field=f"engineering_overrides.{name}")
        unit = _text(override["unit"], f"engineering_overrides.{name}.unit")
        if unit not in _UNITS:
            raise _invalid("Engineering override unit is unsupported.", field=f"engineering_overrides.{name}.unit", unit=unit)
        result[_text(name, "engineering_overrides.name")] = {
            "value": _number(override["value"], f"engineering_overrides.{name}.value"),
            "unit": unit,
        }
    return result


def parse_parametric_request(payload: Mapping[str, Any] | MmcParametricRequest) -> MmcParametricRequest:
    if isinstance(payload, MmcParametricRequest):
        return payload
    allowed = {
        "schema_version", "model_fidelity", "topology", "converter", "dc_voltage_kv",
        "active_power_mw", "reactive_power_mvar", "frequency_hz", "station_p",
        "station_vdc", "dc_link", "power_reversal_time_s", "engineering_overrides",
    }
    raw = _mapping(payload, "request", allowed)
    missing = sorted(allowed - set(raw))
    if missing:
        raise _invalid("The MMC request is missing required fields.", missing=missing)
    schema_version = raw["schema_version"]
    if isinstance(schema_version, bool) or schema_version != 1:
        raise _invalid("schema_version must be 1.", field="schema_version")
    fidelity = _text(raw["model_fidelity"], "model_fidelity")
    topology = _text(raw["topology"], "topology")
    converter = _text(raw["converter"], "converter")
    if fidelity not in _FIDELITIES:
        raise _invalid("model_fidelity is unsupported.", field="model_fidelity", value=fidelity)
    if topology not in _TOPOLOGIES:
        raise _invalid("topology is unsupported.", field="topology", value=topology)
    if converter not in _CONVERTERS:
        raise _invalid("converter is unsupported.", field="converter", value=converter)
    return MmcParametricRequest(
        schema_version=1,
        model_fidelity=fidelity,
        topology=topology,
        converter=converter,
        dc_voltage_kv=_number(raw["dc_voltage_kv"], "dc_voltage_kv", positive=True),
        active_power_mw=_number(raw["active_power_mw"], "active_power_mw", positive=True),
        reactive_power_mvar=_number(raw["reactive_power_mvar"], "reactive_power_mvar"),
        frequency_hz=_number(raw["frequency_hz"], "frequency_hz", positive=True),
        station_p=_parse_grid(raw["station_p"], "station_p"),
        station_vdc=_parse_grid(raw["station_vdc"], "station_vdc"),
        dc_link=_parse_link(raw["dc_link"]),
        power_reversal_time_s=_number(raw["power_reversal_time_s"], "power_reversal_time_s", positive=True),
        engineering_overrides=_parse_overrides(raw["engineering_overrides"]),
    )


__all__ = [
    "MmcAdjustment", "MmcCandidate", "MmcConstraintResult", "MmcDcLinkRequest",
    "MmcDerivedParameters", "MmcEnginePlan", "MmcGridRequest", "MmcParametricBuildRecord",
    "MmcParametricRequest", "MmcParentPlan", "MmcScenarioRecommendation", "parse_parametric_request",
]
