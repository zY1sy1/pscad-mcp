"""Immutable relationship records for schema-v2 PSCAD corpora."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import FrozenDict, json_safe

Point = tuple[int, int]


@dataclass(frozen=True)
class CorpusDefinitionClassification:
    key: str
    namespace: str
    pscad_version: str
    physical_name: str
    classification: str
    port_contract_keys: tuple[str, ...]
    source_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "namespace": self.namespace,
            "pscad_version": self.pscad_version,
            "physical_name": self.physical_name,
            "classification": self.classification,
            "port_contract_keys": list(self.port_contract_keys),
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True)
class CorpusComponentOccurrence:
    key: str
    source_component_key: str
    canvas_key: str
    source_canvas_key: str
    definition_key: str
    hierarchy_path: tuple[str, ...]
    name: str
    location: Point
    orientation: int
    parameters: FrozenDict

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "source_component_key": self.source_component_key,
            "canvas_key": self.canvas_key,
            "source_canvas_key": self.source_canvas_key,
            "definition_key": self.definition_key,
            "hierarchy_path": list(self.hierarchy_path),
            "name": self.name,
            "location": list(self.location),
            "orientation": self.orientation,
            "parameters": json_safe(self.parameters),
        }


@dataclass(frozen=True)
class CorpusConductorOccurrence:
    key: str
    source_connection_key: str
    canvas_key: str
    kind: str
    namespace: str
    vertices: tuple[Point, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "source_connection_key": self.source_connection_key,
            "canvas_key": self.canvas_key,
            "kind": self.kind,
            "namespace": self.namespace,
            "vertices": [list(point) for point in self.vertices],
        }


@dataclass(frozen=True)
class CorpusLabelOccurrence:
    key: str
    source_component_key: str
    canvas_key: str
    name: str
    namespace: str
    scope: str
    location: Point

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "source_component_key": self.source_component_key,
            "canvas_key": self.canvas_key,
            "name": self.name,
            "namespace": self.namespace,
            "scope": self.scope,
            "location": list(self.location),
        }


@dataclass(frozen=True)
class CorpusInstancePort:
    key: str
    component_key: str
    source_component_key: str
    definition_port_key: str
    name: str
    occurrence: int
    relative: Point
    absolute: Point
    namespace: str
    dimension: int | None
    active: bool
    source_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "component_key": self.component_key,
            "source_component_key": self.source_component_key,
            "definition_port_key": self.definition_port_key,
            "name": self.name,
            "occurrence": self.occurrence,
            "relative": list(self.relative),
            "absolute": list(self.absolute),
            "namespace": self.namespace,
            "dimension": self.dimension,
            "active": self.active,
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True)
class CorpusConfirmedNet:
    key: str
    namespace: str
    port_keys: tuple[str, ...]
    conductor_keys: tuple[str, ...]
    label_keys: tuple[str, ...]
    junctions: tuple[Point, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "namespace": self.namespace,
            "port_keys": list(self.port_keys),
            "conductor_keys": list(self.conductor_keys),
            "label_keys": list(self.label_keys),
            "junctions": [list(point) for point in self.junctions],
        }


@dataclass(frozen=True)
class CorpusPortNetMembership:
    key: str
    component_key: str
    port_key: str
    net_key: str
    namespace: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "component_key": self.component_key,
            "port_key": self.port_key,
            "net_key": self.net_key,
            "namespace": self.namespace,
        }


@dataclass(frozen=True)
class CorpusHierarchyRelation:
    key: str
    parent_component_key: str
    child_canvas_key: str
    outer_port_key: str
    inner_port_key: str
    namespace: str
    dimension: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "parent_component_key": self.parent_component_key,
            "child_canvas_key": self.child_canvas_key,
            "outer_port_key": self.outer_port_key,
            "inner_port_key": self.inner_port_key,
            "namespace": self.namespace,
            "dimension": self.dimension,
        }


@dataclass(frozen=True)
class CorpusCandidateEdge:
    left: str
    right: str
    confidence: float
    reasons: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    status: str = "candidate_only"

    def to_dict(self) -> dict[str, Any]:
        return {
            "left": self.left,
            "right": self.right,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "counter_evidence": list(self.counter_evidence),
            "status": self.status,
        }


@dataclass(frozen=True)
class CorpusUnresolvedEvidence:
    code: str
    object_keys: tuple[str, ...]
    evidence: tuple[str, ...]
    classification: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "object_keys": list(self.object_keys),
            "evidence": list(self.evidence),
            "classification": self.classification,
        }
