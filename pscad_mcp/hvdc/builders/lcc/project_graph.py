"""Structured, metadata-independent normalization of PSCX project graphs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError
from ....topology.connectivity import build_connectivity
from ....topology.providers.pscx import PscxSnapshotProvider
from ....topology.reconcile import reconcile_snapshots
from .catalog import LccCatalog, parse_catalog


@dataclass(frozen=True)
class GraphPort:
    name: str
    kind: str
    dimension: int
    offset: tuple[int, int]
    absolute: tuple[int, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "dimension": self.dimension,
            "offset": list(self.offset),
            "absolute": list(self.absolute),
        }


@dataclass(frozen=True)
class GraphComponent:
    logical_id: str
    definition: str
    canvas: str
    location: tuple[int, int]
    orientation: int
    parameters: Mapping[str, str]
    ports: tuple[GraphPort, ...] = ()
    component_id: str | None = field(default=None, compare=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_id": self.logical_id,
            "definition": self.definition,
            "canvas": self.canvas,
            "location": list(self.location),
            "orientation": self.orientation,
            "parameters": dict(sorted(self.parameters.items())),
            "ports": [port.to_dict() for port in self.ports],
        }


@dataclass(frozen=True)
class GraphWire:
    kind: str
    vertices: tuple[tuple[int, int], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "vertices": [list(point) for point in self.vertices],
        }


@dataclass(frozen=True)
class GraphLabel:
    text: str
    kind: str
    location: tuple[int, int] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "kind": self.kind,
            "location": (
                None if self.location is None else list(self.location)
            ),
        }


@dataclass(frozen=True)
class GraphNet:
    kind: str
    points: tuple[tuple[int, int], ...]
    labels: tuple[str, ...] = ()
    endpoints: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "points": [list(point) for point in self.points],
            "labels": list(self.labels),
            "endpoints": list(self.endpoints),
        }


@dataclass(frozen=True)
class ProjectGraph:
    project_name: str
    pscad_version: str | None
    components: tuple[GraphComponent, ...]
    wires: tuple[GraphWire, ...]
    labels: tuple[GraphLabel, ...]
    nets: tuple[GraphNet, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "pscad_version": self.pscad_version,
            "components": [component.to_dict() for component in self.components],
            "wires": [wire.to_dict() for wire in self.wires],
            "labels": [label.to_dict() for label in self.labels],
            "nets": [net.to_dict() for net in self.nets],
        }


def read_project_graph(
    path: str | Path,
    catalog: LccCatalog | Mapping[str, Any] | None = None,
) -> ProjectGraph:
    if isinstance(catalog, Mapping):
        catalog = parse_catalog(catalog)
    try:
        from ....topology.adapters.lcc import (
            lcc_port_contracts,
            topology_to_lcc_graph,
        )

        saved = PscxSnapshotProvider(
            definition_ports=lcc_port_contracts(catalog)
        ).read(path, "Main")
        topology = build_connectivity(
            reconcile_snapshots(None, saved)
        ).topology
        return topology_to_lcc_graph(topology, catalog)
    except BackendError as error:
        if error.code == "LCC_STRUCTURE_INVALID":
            raise
        project_path = Path(path).expanduser().resolve()
        raise BackendError(
            "LCC_STRUCTURE_INVALID",
            "Unable to read the PSCX project graph.",
            "hvdc",
            "read_lcc_project_graph",
            {"path": str(project_path), "reason": error.code},
        ) from error
