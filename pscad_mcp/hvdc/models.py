"""JSON-safe evidence and domain contracts for HVDC workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HvdcSourceRef:
    project_path: str
    canvas_name: str | None = None
    component_id: str | None = None
    definition: str | None = None
    parameter_name: str | None = None
    label: str | None = None


@dataclass(frozen=True)
class HvdcComponentRecord:
    component_id: str
    name: str
    definition: str
    parameters: dict[str, Any] = field(default_factory=dict)
    labels: tuple[str, ...] = ()
    ports: tuple[dict[str, Any], ...] = ()
    source: HvdcSourceRef = field(default_factory=lambda: HvdcSourceRef(""))


@dataclass(frozen=True)
class HvdcLabelRecord:
    text: str
    kind: str
    source: HvdcSourceRef


@dataclass(frozen=True)
class HvdcConnectionRecord:
    connection_id: str
    source_component_id: str
    source_port: str
    target_component_id: str
    target_port: str
    source: HvdcSourceRef
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class HvdcProjectEvidence:
    project_path: str
    project_name: str
    pscad_version: str | None
    definitions: tuple[str, ...] = ()
    components: tuple[HvdcComponentRecord, ...] = ()
    labels: tuple[HvdcLabelRecord, ...] = ()
    connections: tuple[HvdcConnectionRecord, ...] = ()
    warnings: tuple[str | dict[str, Any], ...] = ()


@dataclass(frozen=True)
class HvdcAsset:
    kind: str
    name: str
    source: HvdcSourceRef
    confidence: float
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class HvdcReturnPath:
    mode: str
    segments: tuple[HvdcSourceRef, ...] = ()
    endpoints: tuple[HvdcSourceRef, ...] = ()
    closed: bool = False
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()


@dataclass(frozen=True)
class HvdcTopologySummary:
    family: str
    polarity: str
    terminal_count: int | None
    breaker_protection_present: bool
    dc_line_present: bool
    confidence: float
    return_mode: str = "unknown"
    return_path_status: str = "incomplete"
    return_path: tuple[HvdcReturnPath, ...] = ()
    pole_roles: dict[str, HvdcSourceRef] = field(default_factory=dict)
    neutral_assets: tuple[HvdcSourceRef, ...] = ()
    mode_evidence: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()


@dataclass(frozen=True)
class HvdcMapping:
    canonical: str
    aliases: tuple[str, ...]
    source: HvdcSourceRef | None
    units: str | None
    unit_family: str | None
    direction: str
    status: str
    confidence: float


@dataclass(frozen=True)
class HvdcMetric:
    name: str
    value: float | None
    units: str | None
    time_window: tuple[float, float] | None
    source_channels: tuple[str, ...]
    method: str
    status: str
    warning: str | None = None


@dataclass(frozen=True)
class HvdcScenarioResult:
    scenario_id: str
    project_name: str
    status: str
    changed_parameters: tuple[dict[str, Any], ...] = ()
    output_files: tuple[str, ...] = ()
    resolved_channels: tuple[str, ...] = ()
    calculated_metrics: tuple[HvdcMetric, ...] = ()
    warnings: tuple[str, ...] = ()
    verdict: str | None = None
