"""Immutable records for deterministic PSCAD blueprint corpora."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import FrozenDict, json_safe


@dataclass(frozen=True)
class CorpusDependency:
    basename: str
    byte_length: int
    sha256: str
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "basename": self.basename,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class CorpusSource:
    project_id: str
    basename: str
    byte_length: int
    sha256: str
    pscad_versions: tuple[str, ...]
    dependencies: tuple[CorpusDependency, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "basename": self.basename,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
            "pscad_versions": list(self.pscad_versions),
            "dependencies": [dependency.to_dict() for dependency in self.dependencies],
        }


@dataclass(frozen=True)
class CorpusSpec:
    schema_version: int
    normalization_profile: str
    name: str
    inclusion_policy: str
    exclusion_policy: str
    entry_points: tuple[CorpusSource, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "normalization_profile": self.normalization_profile,
            "name": self.name,
            "inclusion_policy": self.inclusion_policy,
            "exclusion_policy": self.exclusion_policy,
            "entry_points": [entry.to_dict() for entry in self.entry_points],
        }


@dataclass(frozen=True)
class CorpusWarning:
    kind: str
    path: str
    count: int
    blocking: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "count": self.count,
            "blocking": self.blocking,
        }


@dataclass(frozen=True)
class DefinitionParameter:
    name: str
    type: str
    dimension: str
    units: str
    minimum: str | None
    maximum: str | None
    intent: str
    default: str | None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "dimension": self.dimension,
            "units": self.units,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "intent": self.intent,
        }
        if self.default is not None:
            result["default"] = self.default
        return result


@dataclass(frozen=True)
class DefinitionPort:
    key: str
    name: str
    model: str
    dimension: str
    mode: str
    type: str
    offset: tuple[int, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "model": self.model,
            "dimension": self.dimension,
            "mode": self.mode,
            "type": self.type,
            "offset": list(self.offset),
        }


@dataclass(frozen=True)
class CorpusDefinition:
    key: str
    name: str
    class_id: str
    parameters: tuple[DefinitionParameter, ...]
    ports: tuple[DefinitionPort, ...]
    canvas_key: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "class_id": self.class_id,
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "ports": [port.to_dict() for port in self.ports],
            "canvas_key": self.canvas_key,
        }


@dataclass(frozen=True)
class CorpusCanvas:
    key: str
    name: str
    owner_definition: str
    class_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "owner_definition": self.owner_definition,
            "class_id": self.class_id,
        }


@dataclass(frozen=True)
class CorpusComponent:
    key: str
    canvas_key: str
    definition_key: str
    name: str
    location: tuple[int, int]
    orientation: int
    parameters: FrozenDict
    resolved: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "canvas_key": self.canvas_key,
            "definition_key": self.definition_key,
            "name": self.name,
            "location": list(self.location),
            "orientation": self.orientation,
            "parameters": json_safe(self.parameters),
            "resolved": self.resolved,
        }


@dataclass(frozen=True)
class CorpusConnection:
    key: str
    canvas_key: str | None
    kind: str
    vertices: tuple[tuple[int, int], ...]
    endpoints: tuple[str, ...]
    source_definition: str | None
    resolution: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "canvas_key": self.canvas_key,
            "kind": self.kind,
            "vertices": [list(vertex) for vertex in self.vertices],
            "endpoints": list(self.endpoints),
            "source_definition": self.source_definition,
            "resolution": self.resolution,
        }


@dataclass(frozen=True)
class CorpusOutputChannel:
    key: str
    name: str
    label: str
    dimension: str
    units: str
    minimum: str | None
    maximum: str | None
    source_component: str | None
    source_port: str
    resolved: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "label": self.label,
            "dimension": self.dimension,
            "units": self.units,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "source_component": self.source_component,
            "source_port": self.source_port,
            "resolved": self.resolved,
        }


@dataclass(frozen=True)
class ProjectGraph:
    project_id: str
    source_sha256: str
    dependency_hashes: FrozenDict
    name: str
    pscad_version: str
    target: str
    settings: FrozenDict
    definitions: tuple[CorpusDefinition, ...] = ()
    canvases: tuple[CorpusCanvas, ...] = ()
    components: tuple[CorpusComponent, ...] = ()
    connections: tuple[CorpusConnection, ...] = ()
    output_channels: tuple[CorpusOutputChannel, ...] = ()
    warnings: tuple[CorpusWarning, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "source_sha256": self.source_sha256,
            "dependency_hashes": json_safe(self.dependency_hashes),
            "name": self.name,
            "pscad_version": self.pscad_version,
            "target": self.target,
            "settings": json_safe(self.settings),
            "definitions": [definition.to_dict() for definition in self.definitions],
            "canvases": [canvas.to_dict() for canvas in self.canvases],
            "components": [component.to_dict() for component in self.components],
            "connections": [connection.to_dict() for connection in self.connections],
            "output_channels": [channel.to_dict() for channel in self.output_channels],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


@dataclass(frozen=True)
class CorpusRecord:
    schema_version: int
    normalization_profile: str
    corpus_name: str
    project_id: str
    source_sha256: str
    kind: str
    record_key: str
    payload: FrozenDict
    resolved: bool
    verification_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "normalization_profile": self.normalization_profile,
            "corpus_name": self.corpus_name,
            "project_id": self.project_id,
            "source_sha256": self.source_sha256,
            "kind": self.kind,
            "record_key": self.record_key,
            "payload": json_safe(self.payload),
            "resolved": self.resolved,
            "verification_status": self.verification_status,
        }


@dataclass(frozen=True)
class CorpusProjectManifest:
    project_id: str
    source_sha256: str
    graph_path: str
    graph_sha256: str
    graph_byte_length: int
    graph_signature: str
    records_path: str
    records_sha256: str
    records_byte_length: int
    record_count: int
    record_counts: FrozenDict

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "source_sha256": self.source_sha256,
            "graph_path": self.graph_path,
            "graph_sha256": self.graph_sha256,
            "graph_byte_length": self.graph_byte_length,
            "graph_signature": self.graph_signature,
            "records_path": self.records_path,
            "records_sha256": self.records_sha256,
            "records_byte_length": self.records_byte_length,
            "record_count": self.record_count,
            "record_counts": json_safe(self.record_counts),
        }


@dataclass(frozen=True)
class CorpusManifest:
    schema_version: int
    normalization_profile: str
    name: str
    source_spec_sha256: str
    project_count: int
    projects: tuple[CorpusProjectManifest, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "normalization_profile": self.normalization_profile,
            "name": self.name,
            "source_spec_sha256": self.source_spec_sha256,
            "project_count": self.project_count,
            "projects": [project.to_dict() for project in self.projects],
        }
