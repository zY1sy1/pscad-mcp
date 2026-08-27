"""Immutable, JSON-safe records for the Stage A MMC builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..common.records import JsonRecord as _JsonRecord
from ..common.records import freeze as _freeze


class MmcBuildState(str, Enum):
    VALIDATED = "validated"
    STAGING_CREATED = "staging_created"
    COMPONENTS_PLACED = "components_placed"
    PARAMETERS_VERIFIED = "parameters_verified"
    CONNECTIONS_VERIFIED = "connections_verified"
    STRUCTURE_VERIFIED = "structure_verified"
    STAGING_SAVED = "staging_saved"
    COMPILED = "compiled"
    STARTUP_SIMULATED = "startup_simulated"
    FORWARD_SIMULATED = "forward_simulated"
    REVERSAL_SIMULATED = "reversal_simulated"
    REVERSE_SIMULATED = "reverse_simulated"
    ACCEPTANCE_PASSED = "acceptance_passed"
    PUBLISHED = "published"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    INTERRUPTED = "interrupted"


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    return tuple(value)


@dataclass(frozen=True)
class MmcArmSpec(_JsonRecord):
    logical_id: str
    station_role: str
    phase: str
    arm: str
    definition: str
    location: tuple[int, int]
    parameters: dict[str, Any] = field(default_factory=dict)
    ports: tuple[str, ...] = ()
    orientation: int = 0
    canvas: str = "Main"
    role: str | None = None
    equations: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "location", tuple(self.location))
        object.__setattr__(self, "parameters", _freeze(self.parameters))
        object.__setattr__(self, "ports", tuple(self.ports))
        object.__setattr__(self, "equations", _freeze(self.equations))


@dataclass(frozen=True)
class MmcControlContract(_JsonRecord):
    role: str
    active_power_command: str
    reactive_power_command: str
    dc_voltage_command: str | None = None
    version: str | None = None
    equations: dict[str, str] = field(default_factory=dict)
    modulation_bounds: tuple[float, float] = (0.0, 1.0)
    signals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "equations", _freeze(self.equations))
        object.__setattr__(self, "modulation_bounds", tuple(self.modulation_bounds))
        object.__setattr__(self, "signals", tuple(self.signals))


@dataclass(frozen=True)
class MmcStationSpec(_JsonRecord):
    logical_id: str
    role: str
    arms: tuple[MmcArmSpec, ...]
    ac_component: str
    control_contract: MmcControlContract
    dc_positive_bus: str | None = None
    dc_negative_bus: str | None = None
    transformer_component: str | None = None
    ac_impedance_component: str | None = None
    energy_control_component: str | None = None
    circulating_control_component: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "arms", tuple(self.arms))
        object.__setattr__(self, "parameters", _freeze(self.parameters))


@dataclass(frozen=True)
class MmcComponentSpec(_JsonRecord):
    logical_id: str
    definition: str
    location: tuple[int, int]
    parameters: dict[str, Any] = field(default_factory=dict)
    ports: tuple[str, ...] = ()
    orientation: int = 0
    canvas: str = "Main"
    bounding_box: tuple[int, int, int, int] | None = None
    role: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "location", tuple(self.location))
        object.__setattr__(self, "parameters", _freeze(self.parameters))
        object.__setattr__(self, "ports", tuple(self.ports))
        if self.bounding_box is not None:
            object.__setattr__(self, "bounding_box", tuple(self.bounding_box))


@dataclass(frozen=True)
class MmcNetSpec(_JsonRecord):
    logical_id: str
    kind: str
    endpoints: tuple[str, ...]
    route: tuple[tuple[int, int], ...] = ()
    label: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "endpoints", tuple(self.endpoints))
        object.__setattr__(self, "route", tuple(tuple(point) for point in self.route))


@dataclass(frozen=True)
class MmcOutputSpec(_JsonRecord):
    logical_id: str
    path: str
    units: str
    role: str
    call_id: int | None = None
    location: str | None = None
    measurement: str | None = None


@dataclass(frozen=True)
class MmcSequencePhase(_JsonRecord):
    name: str
    order: int
    entry_condition: str
    exit_condition: str
    duration_s: float
    outputs: tuple[str, ...] = ()
    commands: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "outputs", tuple(self.outputs))
        object.__setattr__(self, "commands", _freeze(self.commands))


@dataclass(frozen=True)
class MmcAcceptanceCheck(_JsonRecord):
    name: str
    kind: str
    required: bool
    expected: dict[str, Any]
    units: str
    comparison_window: tuple[float, float]
    severity: str | None = None
    rationale: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "expected", _freeze(self.expected))
        object.__setattr__(self, "comparison_window", tuple(self.comparison_window))


@dataclass(frozen=True)
class MmcBlueprint(_JsonRecord):
    schema_version: int
    name: str
    profile: str
    nominal_vdc_kv: float
    nominal_power_mw: float
    settings: dict[str, Any]
    stations: tuple[MmcStationSpec, ...]
    components: tuple[MmcComponentSpec, ...]
    nets: tuple[MmcNetSpec, ...]
    outputs: tuple[MmcOutputSpec, ...]
    control_contract: MmcControlContract
    sequence: tuple[MmcSequencePhase, ...]
    acceptance_checks: tuple[MmcAcceptanceCheck, ...]
    model: str | None = None
    topology: str | None = None
    equation_version: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "settings", _freeze(self.settings))
        object.__setattr__(self, "stations", tuple(self.stations))
        object.__setattr__(self, "components", tuple(self.components))
        object.__setattr__(self, "nets", tuple(self.nets))
        object.__setattr__(self, "outputs", tuple(self.outputs))
        object.__setattr__(self, "sequence", tuple(self.sequence))
        object.__setattr__(self, "acceptance_checks", tuple(self.acceptance_checks))
        object.__setattr__(self, "provenance", _freeze(self.provenance))


@dataclass(frozen=True)
class MmcPlanOperation(_JsonRecord):
    sequence: int
    kind: str
    target: str
    arguments: dict[str, Any] = field(default_factory=dict)
    operation_id: str | None = None
    phase: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", _freeze(self.arguments))


@dataclass(frozen=True)
class MmcBuildPlan(_JsonRecord):
    blueprint: MmcBlueprint
    operations: tuple[MmcPlanOperation, ...]
    plan_hash: str
    acceptance_checks: tuple[MmcAcceptanceCheck, ...] = ()
    target_path: str | None = None
    staging_path: str | None = None
    asset_hashes: dict[str, str] = field(default_factory=dict)
    pscad_version: str | None = None
    catalog_identity: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "operations", tuple(self.operations))
        object.__setattr__(self, "acceptance_checks", tuple(self.acceptance_checks))
        object.__setattr__(self, "asset_hashes", _freeze(self.asset_hashes))
        object.__setattr__(self, "metadata", _freeze(self.metadata))


@dataclass(frozen=True)
class MmcBuildRecord(_JsonRecord):
    build_id: str
    state: MmcBuildState
    plan: MmcBuildPlan | None = None
    history: tuple[dict[str, Any], ...] = ()
    error: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    workspace: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "history", _freeze(self.history))
        object.__setattr__(self, "error", _freeze(self.error))
        object.__setattr__(self, "result", _freeze(self.result))


__all__ = [
    "MmcAcceptanceCheck",
    "MmcArmSpec",
    "MmcBlueprint",
    "MmcBuildPlan",
    "MmcBuildRecord",
    "MmcBuildState",
    "MmcComponentSpec",
    "MmcControlContract",
    "MmcNetSpec",
    "MmcOutputSpec",
    "MmcPlanOperation",
    "MmcSequencePhase",
    "MmcStationSpec",
]
