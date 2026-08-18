"""Structured, metadata-independent normalization of PSCX project graphs."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ....core.backend.base import BackendError
from .catalog import LccCatalog, require_definition, require_port
from .routing import absolute_port, validate_orthogonal_route


def _name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _attr(element: ET.Element, *names: str) -> str | None:
    wanted = {name.casefold() for name in names}
    for key, value in element.attrib.items():
        if key.casefold() in wanted:
            return value
    return None


def _text(value: str | None) -> str:
    return (value or "").strip()


def _integer(value: str | None, context: str, default: int | None = None) -> int:
    if value is None or not value.strip():
        if default is not None:
            return default
        raise BackendError("LCC_STRUCTURE_INVALID", f"{context} is missing.", "hvdc", "read_lcc_project_graph", {"context": context})
    try:
        return int(value.strip())
    except ValueError as error:
        raise BackendError("LCC_STRUCTURE_INVALID", f"{context} must be an integer.", "hvdc", "read_lcc_project_graph", {"context": context, "value": value}) from error


def _point(element: ET.Element, context: str) -> tuple[int, int]:
    x = _attr(element, "x", "left")
    y = _attr(element, "y", "top")
    if x is None or y is None:
        raw = _attr(element, "location", "position")
        if raw:
            parts = raw.replace("(", "").replace(")", "").split(",")
            if len(parts) == 2:
                x, y = parts
    return (_integer(x, f"{context}.x"), _integer(y, f"{context}.y"))


def _parameters(element: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for child in element.iter():
        if _name(child.tag) not in {"param", "parameter"}:
            continue
        name = _text(_attr(child, "name", "key"))
        if not name:
            continue
        value = _attr(child, "value")
        result[name] = _text(value if value is not None else child.text)
    return result


def _kind(value: str | None, tag: str | None = None) -> str:
    raw = _text(value).casefold()
    if raw in {"data", "signal", "digital"}:
        return "data"
    if raw in {"electrical", "power", "analog", "node"}:
        return "electrical"
    tag_name = (tag or "").casefold()
    if "data" in tag_name or "signal" in tag_name:
        return "data"
    return "electrical"


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
        return {"kind": self.kind, "vertices": [list(point) for point in self.vertices]}


@dataclass(frozen=True)
class GraphLabel:
    text: str
    kind: str
    location: tuple[int, int] | None

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "kind": self.kind, "location": None if self.location is None else list(self.location)}


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


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[tuple[str, tuple[int, int]], tuple[str, tuple[int, int]]] = {}

    def add(self, value: tuple[str, tuple[int, int]]) -> None:
        self.parent.setdefault(value, value)

    def find(self, value: tuple[str, tuple[int, int]]) -> tuple[str, tuple[int, int]]:
        self.add(value)
        parent = self.parent[value]
        if parent != value:
            parent = self.find(parent)
            self.parent[value] = parent
        return parent

    def union(self, left: tuple[str, tuple[int, int]], right: tuple[str, tuple[int, int]]) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def _main_scope(root: ET.Element) -> ET.Element:
    definitions = [
        element
        for element in root.iter()
        if _name(element.tag) in {"definition", "canvas", "schematic"}
        and _text(_attr(element, "name", "id")).casefold() == "main"
    ]
    if not definitions:
        raise BackendError("LCC_STRUCTURE_INVALID", "Main definition was not found.", "hvdc", "read_lcc_project_graph")
    scope = definitions[0]
    schematics = [element for element in scope.iter() if _name(element.tag) in {"schematic", "canvas"}]
    return schematics[0] if schematics else scope


def _component_elements(scope: ET.Element) -> list[ET.Element]:
    return [
        element
        for element in scope.iter()
        if _name(element.tag) == "component"
        or (_name(element.tag) == "user" and _text(_attr(element, "classid", "class")).casefold() in {"usercmp", "component"})
    ]


def _component_location(element: ET.Element, context: str) -> tuple[int, int]:
    if _attr(element, "x", "y", "location", "position") is not None:
        return _point(element, context)
    for child in element:
        if _name(child.tag) in {"location", "position", "origin"}:
            return _point(child, context)
    return (0, 0)


def _component_ports(
    element: ET.Element,
    definition_name: str,
    location: tuple[int, int],
    orientation: int,
    catalog: LccCatalog | None,
    context: str,
) -> tuple[GraphPort, ...]:
    parsed: list[GraphPort] = []
    seen_names: set[str] = set()
    for index, port_element in enumerate(element.iter()):
        if _name(port_element.tag) != "port":
            continue
        port_name = _text(_attr(port_element, "name", "id"))
        if not port_name:
            continue
        seen_names.add(port_name)
        kind = _kind(_attr(port_element, "kind", "type", "model"), "port")
        dimension = _integer(_attr(port_element, "dimension", "dim"), f"{context}.ports[{index}].dimension", default=1)
        offset = _point(port_element, f"{context}.ports[{index}]")
        if catalog is not None:
            try:
                contract = require_port(require_definition(catalog, definition_name), port_name)
            except BackendError:
                pass
            else:
                kind = contract.kind
                dimension = contract.dimension
                offset = contract.offset
        parsed.append(GraphPort(port_name, kind, dimension, offset, absolute_port(location, offset, orientation)))
    if catalog is not None:
        try:
            definition = require_definition(catalog, definition_name)
        except BackendError:
            definition = None
        if definition is not None:
            for contract in definition.ports:
                if contract.name in seen_names:
                    continue
                parsed.append(
                    GraphPort(
                        contract.name,
                        contract.kind,
                        contract.dimension,
                        contract.offset,
                        absolute_port(location, contract.offset, orientation),
                    )
                )
    return tuple(sorted(parsed, key=lambda port: (port.name, port.kind, port.dimension, port.offset)))


def _parse_components(scope: ET.Element, catalog: LccCatalog | None) -> tuple[GraphComponent, ...]:
    result: list[GraphComponent] = []
    for index, element in enumerate(_component_elements(scope)):
        context = f"components[{index}]"
        component_id = _text(_attr(element, "id", "ID")) or None
        definition = _text(_attr(element, "definition", "defn", "type"))
        if not definition:
            raise BackendError("LCC_STRUCTURE_INVALID", f"{context}.definition is missing.", "hvdc", "read_lcc_project_graph", {"context": context})
        location = _component_location(element, context)
        orientation = _integer(_attr(element, "orientation", "orient", "rotation", "angle"), f"{context}.orientation", default=0)
        logical_id = _text(_attr(element, "logical_id", "logical", "name"))
        parameters = _parameters(element)
        if not logical_id:
            logical_id = parameters.get("LogicalId", parameters.get("LOGICAL_ID", ""))
        if not logical_id:
            logical_id = f"{definition}@{location[0]},{location[1]}"
        result.append(
            GraphComponent(
                logical_id=logical_id,
                definition=definition,
                canvas="Main",
                location=location,
                orientation=orientation,
                parameters=MappingProxyType(dict(sorted(parameters.items()))),
                ports=_component_ports(element, definition, location, orientation, catalog, context),
                component_id=component_id,
            )
        )
    return tuple(sorted(result, key=lambda item: (item.canvas, item.definition, item.location, item.logical_id)))


def _parse_wires(scope: ET.Element) -> tuple[GraphWire, ...]:
    result: list[GraphWire] = []
    for index, element in enumerate(scope.iter()):
        if _name(element.tag) not in {"wire", "connection", "segment"}:
            continue
        origin_x = _integer(_attr(element, "x", "left"), f"wires[{index}].x", default=0)
        origin_y = _integer(_attr(element, "y", "top"), f"wires[{index}].y", default=0)
        vertices = [
            (
                point[0] + origin_x,
                point[1] + origin_y,
            )
            for vertex_index, vertex in enumerate(element.iter())
            if vertex is not element and _name(vertex.tag) in {"vertex", "point", "node"}
            for point in [_point(vertex, f"wires[{index}].vertices[{vertex_index}]")]
        ]
        if len(vertices) < 2:
            start = _attr(element, "x1")
            end = _attr(element, "x2")
            if start is not None and end is not None:
                vertices = [
                    (
                        _integer(start, f"wires[{index}].x1") + origin_x,
                        _integer(_attr(element, "y1"), f"wires[{index}].y1") + origin_y,
                    ),
                    (
                        _integer(end, f"wires[{index}].x2") + origin_x,
                        _integer(_attr(element, "y2"), f"wires[{index}].y2") + origin_y,
                    ),
                ]
        if len(vertices) < 2:
            raise BackendError("LCC_STRUCTURE_INVALID", "A wire requires at least two vertices.", "hvdc", "read_lcc_project_graph", {"wire": index})
        kind = _kind(_attr(element, "kind", "type", "namespace"), "wire")
        result.append(GraphWire(kind, validate_orthogonal_route(vertices)))
    return tuple(sorted(result, key=lambda wire: (wire.kind, wire.vertices)))


def _parse_labels(scope: ET.Element) -> tuple[GraphLabel, ...]:
    result: list[GraphLabel] = []
    for element in scope.iter():
        tag = _name(element.tag)
        if tag not in {"label", "datalabel", "nodelabel", "annotation", "text"}:
            continue
        text = _text(element.text or _attr(element, "text", "name", "label", "value"))
        if not text:
            continue
        location = None
        if _attr(element, "x", "y", "location", "position") is not None:
            location = _point(element, f"label.{text}")
        else:
            for child in element:
                if _name(child.tag) in {"location", "position"}:
                    location = _point(child, f"label.{text}")
                    break
        result.append(GraphLabel(text, _kind(_attr(element, "kind", "type"), tag), location))
    return tuple(sorted(result, key=lambda label: (label.kind, label.text, label.location or (0, 0))))


def _normalized_nets(
    components: tuple[GraphComponent, ...],
    wires: tuple[GraphWire, ...],
    labels: tuple[GraphLabel, ...],
) -> tuple[GraphNet, ...]:
    union = _UnionFind()
    wire_points: set[tuple[str, tuple[int, int]]] = set()
    for wire in wires:
        points = [(wire.kind, vertex) for vertex in wire.vertices]
        for point in points:
            union.add(point)
            wire_points.add(point)
        for left, right in zip(points, points[1:]):
            union.union(left, right)
    label_points: list[tuple[GraphLabel, tuple[str, tuple[int, int]]]] = []
    for label in labels:
        if label.location is None:
            continue
        point = (label.kind, label.location)
        union.add(point)
        label_points.append((label, point))
    by_label: dict[tuple[str, str], list[tuple[str, tuple[int, int]]]] = {}
    for label, point in label_points:
        by_label.setdefault((label.kind, label.text), []).append(point)
    for points in by_label.values():
        for point in points[1:]:
            union.union(points[0], point)
    endpoint_points: list[tuple[str, str, tuple[str, tuple[int, int]]]] = []
    for component in components:
        for port in component.ports:
            point = (port.kind, port.absolute)
            union.add(point)
            if point in wire_points:
                endpoint_points.append((component.logical_id, port.name, point))
    groups: dict[tuple[str, tuple[int, int]], set[tuple[str, tuple[int, int]]] ] = {}
    for point in union.parent:
        groups.setdefault(union.find(point), set()).add(point)
    nets: list[GraphNet] = []
    for root, members in groups.items():
        kind = root[0]
        active = any(member in wire_points for member in members) or any(
            point in members for _, point in label_points
        )
        if not active:
            continue
        net_labels = sorted({label.text for label, point in label_points if union.find(point) == root})
        endpoints = sorted(f"{component}:{port}" for component, port, point in endpoint_points if union.find(point) == root)
        nets.append(GraphNet(kind, tuple(sorted(point for _, point in members)), tuple(net_labels), tuple(endpoints)))
    return tuple(sorted(nets, key=lambda net: (net.kind, net.points, net.labels, net.endpoints)))


def read_project_graph(path: str | Path, catalog: LccCatalog | Mapping[str, Any] | None = None) -> ProjectGraph:
    project_path = Path(path).expanduser().resolve()
    if isinstance(catalog, Mapping):
        from .catalog import parse_catalog

        catalog = parse_catalog(catalog)
    try:
        root = ET.parse(project_path).getroot()
    except (OSError, ET.ParseError) as error:
        raise BackendError("LCC_STRUCTURE_INVALID", f"Unable to parse PSCX graph: {error}", "hvdc", "read_lcc_project_graph", {"path": str(project_path)}) from error
    scope = _main_scope(root)
    components = _parse_components(scope, catalog)
    wires = _parse_wires(scope)
    labels = _parse_labels(scope)
    return ProjectGraph(
        project_name=_text(_attr(root, "name")) or project_path.stem,
        pscad_version=_text(_attr(root, "version", "pscad_version")) or None,
        components=components,
        wires=wires,
        labels=labels,
        nets=_normalized_nets(components, wires, labels),
    )
