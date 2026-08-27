from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Point = tuple[int, int]
EvidenceStatus = Literal["observed", "derived", "conflict", "unresolved"]
Namespace = Literal["electrical", "data", "unknown"]


@dataclass(frozen=True)
class EvidenceRef:
    source: str
    reference: str
    fingerprint: str | None = None
    status: EvidenceStatus = "observed"
    observed_at_ns: int | None = None


@dataclass(frozen=True)
class TopologyCanvas:
    key: str
    name: str
    parent_key: str | None = None
    page_ports: tuple[str, ...] = ()


@dataclass(frozen=True)
class TopologyPort:
    key: str
    component_key: str
    name: str
    absolute: Point | None
    relative: Point | None = None
    kind: Namespace = "unknown"
    dimension: int | None = None
    active: bool = True
    required: bool | None = None
    evidence: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True)
class DefinitionPortContract:
    name: str
    kind: Namespace
    dimension: int | None
    offset: Point
    required: bool | None = None


@dataclass(frozen=True)
class TopologyBoundaryLink:
    key: str
    outer_port_key: str
    outer_canvas_key: str
    outer_point: Point
    inner_port_key: str
    inner_canvas_key: str
    inner_point: Point
    namespace: Namespace
    dimension: int | None = None
    evidence: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True)
class TopologyComponent:
    key: str
    canvas_key: str
    object_id: str
    definition: str
    name: str | None = None
    location: Point | None = None
    orientation: int | None = None
    active: bool = True
    parameters: tuple[tuple[str, Any], ...] = ()
    ports: tuple[TopologyPort, ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True)
class TopologyConductor:
    key: str
    canvas_key: str
    object_id: str
    kind: Literal["wire", "bus"]
    namespace: Namespace
    vertices: tuple[Point, ...]
    evidence: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True)
class TopologyLabel:
    key: str
    canvas_key: str
    object_id: str
    name: str
    namespace: Namespace
    scope: str
    location: Point | None = None
    evidence: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True)
class TopologyNet:
    key: str
    namespace: Namespace
    port_keys: tuple[str, ...] = ()
    conductor_keys: tuple[str, ...] = ()
    label_keys: tuple[str, ...] = ()
    junctions: tuple[Point, ...] = ()


@dataclass(frozen=True)
class TopologyConflict:
    field: str
    object_key: str
    live_value: Any
    file_value: Any
    evidence: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True)
class CandidateEdge:
    left: str
    right: str
    confidence: float
    reasons: tuple[str, ...]
    counter_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiagnosticFinding:
    code: str
    severity: Literal["info", "warning", "error"]
    status: EvidenceStatus
    confidence: float
    objects: tuple[str, ...]
    evidence: tuple[str, ...]
    message: str
    suggested_action: str


@dataclass(frozen=True)
class DiagnosticReport:
    topology_hash: str
    valid: bool
    findings: tuple[DiagnosticFinding, ...]
    summary: tuple[tuple[str, int], ...]
    timings_ms: tuple[tuple[str, float], ...] = field(
        default=(), compare=False
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TopologySnapshot:
    source: Literal["live", "pscx"]
    project_name: str
    project_path: str | None = None
    pscad_version: str | None = None
    canvases: tuple[TopologyCanvas, ...] = ()
    components: tuple[TopologyComponent, ...] = ()
    conductors: tuple[TopologyConductor, ...] = ()
    labels: tuple[TopologyLabel, ...] = ()
    boundary_links: tuple[TopologyBoundaryLink, ...] = ()
    unresolved: tuple[str, ...] = ()
    capabilities: tuple[tuple[str, bool], ...] = ()
    source_fingerprint: str | None = None
    grid_step: int = 1


@dataclass(frozen=True)
class ProjectTopology:
    project_name: str
    pscad_version: str | None
    project_path: str | None = None
    canvases: tuple[TopologyCanvas, ...] = ()
    components: tuple[TopologyComponent, ...] = ()
    conductors: tuple[TopologyConductor, ...] = ()
    labels: tuple[TopologyLabel, ...] = ()
    boundary_links: tuple[TopologyBoundaryLink, ...] = ()
    nets: tuple[TopologyNet, ...] = ()
    conflicts: tuple[TopologyConflict, ...] = ()
    unresolved: tuple[str, ...] = ()
    candidate_edges: tuple[CandidateEdge, ...] = ()
    source_fingerprints: tuple[tuple[str, str], ...] = ()
    source_capabilities: tuple[tuple[str, bool], ...] = ()
    grid_step: int = 1
    timings_ms: tuple[tuple[str, float], ...] = field(default=(), compare=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def confirmed_payload(self) -> dict[str, Any]:
        payload = self.to_dict()
        for key in (
            "candidate_edges",
            "timings_ms",
            "project_path",
            "source_fingerprints",
            "source_capabilities",
        ):
            payload.pop(key)
        return _without_observation_metadata(payload)


def _without_observation_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_observation_metadata(item)
            for key, item in value.items()
            if key not in {"evidence", "observed_at_ns"}
        }
    if isinstance(value, tuple):
        return tuple(_without_observation_metadata(item) for item in value)
    if isinstance(value, list):
        return [_without_observation_metadata(item) for item in value]
    return value
