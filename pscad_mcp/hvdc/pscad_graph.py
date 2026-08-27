"""Coordinate-aware PSCAD 4.6 component-port and Wire graph parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree.ElementTree import Element

from .builders.common import transform_offset
from .models import HvdcConnectionRecord, HvdcSourceRef


@dataclass(frozen=True)
class PscadPortPoint:
    component_id: str
    port_name: str
    point: tuple[int, int]
    mode: str
    dimension: str


@dataclass(frozen=True)
class PscadWirePath:
    wire_id: str
    class_id: str
    vertices: tuple[tuple[int, int], ...]


def _name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _text(value: str | None) -> str:
    return (value or "").strip()


def _integer(value: str | None, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def absolute_vertices(wire: Element) -> tuple[tuple[int, int], ...]:
    origin_x = int(wire.attrib.get("x", "0"))
    origin_y = int(wire.attrib.get("y", "0"))
    points = tuple(
        (origin_x + int(vertex.attrib["x"]), origin_y + int(vertex.attrib["y"]))
        for vertex in wire
        if _name(vertex.tag) == "vertex"
    )
    if len(points) < 2:
        raise ValueError("PSCAD Wire requires at least two vertices")
    return points


def _definition_ports(definition: Element) -> tuple[dict[str, str], ...]:
    ports: list[dict[str, str]] = []

    def visit(parent: Element) -> None:
        for child in parent:
            child_name = _name(child.tag)
            if child_name in {"component", "user"}:
                continue
            if child_name == "port":
                ports.append(dict(child.attrib))
            else:
                visit(child)

    visit(definition)
    return tuple(ports)


def _definitions(root: Element) -> dict[str, tuple[dict[str, str], ...]]:
    result: dict[str, tuple[dict[str, str], ...]] = {}
    for element in root.iter():
        if _name(element.tag) != "definition":
            continue
        definition_name = _text(element.attrib.get("name") or element.attrib.get("id"))
        if definition_name:
            result[definition_name.casefold()] = _definition_ports(element)
    return result


def _component_elements(scope: Element) -> tuple[Element, ...]:
    return tuple(
        element
        for element in scope.iter()
        if _name(element.tag) == "component"
        or (_name(element.tag) == "user" and _text(element.attrib.get("classid")).casefold() == "usercmp")
    )


def _component_ports(scope: Element, definitions: dict[str, tuple[dict[str, str], ...]]) -> tuple[PscadPortPoint, ...]:
    result: list[PscadPortPoint] = []
    for index, component in enumerate(_component_elements(scope)):
        component_id = _text(component.attrib.get("id") or component.attrib.get("ID")) or f"component-{index}"
        reference = _text(component.attrib.get("definition") or component.attrib.get("defn") or component.attrib.get("type"))
        port_specs = definitions.get(reference.rsplit(":", 1)[-1].casefold(), ())
        if not port_specs:
            port_specs = tuple(dict(port.attrib) for port in component.iter() if _name(port.tag) == "port")
        origin = (
            _integer(component.attrib.get("x") or component.attrib.get("X")),
            _integer(component.attrib.get("y") or component.attrib.get("Y")),
        )
        orientation = _integer(
            component.attrib.get("orientation") or component.attrib.get("orient") or component.attrib.get("rotation")
        )
        if orientation in {90, 180, 270}:
            orientation //= 90
        for port_index, spec in enumerate(port_specs):
            offset = (_integer(spec.get("x") or spec.get("dx")), _integer(spec.get("y") or spec.get("dy")))
            transformed = transform_offset(offset[0], offset[1], orientation)
            result.append(
                PscadPortPoint(
                    component_id=component_id,
                    port_name=_text(spec.get("name") or spec.get("id")) or f"port-{port_index}",
                    point=(origin[0] + transformed[0], origin[1] + transformed[1]),
                    mode=_text(spec.get("mode") or spec.get("direction")),
                    dimension=_text(spec.get("dimension") or spec.get("dim") or spec.get("kind")),
                )
            )
    return tuple(result)


def _wire_paths(scope: Element) -> tuple[tuple[PscadWirePath, ...], tuple[dict[str, object], ...]]:
    paths: list[PscadWirePath] = []
    warnings: list[dict[str, object]] = []
    for index, wire in enumerate(element for element in scope.iter() if _name(element.tag) == "wire"):
        if not any(_name(child.tag) == "vertex" for child in wire):
            continue
        wire_id = _text(wire.attrib.get("id")) or f"wire-{index}"
        class_id = _text(wire.attrib.get("classid")) or "Wire"
        try:
            vertices = absolute_vertices(wire)
        except (KeyError, TypeError, ValueError) as error:
            warnings.append({"code": "PSCAD_WIRE_INVALID", "wire_id": wire_id, "message": str(error)})
            continue
        if any(first[0] != second[0] and first[1] != second[1] for first, second in zip(vertices, vertices[1:])):
            warnings.append({"code": "PSCAD_WIRE_NON_ORTHOGONAL", "wire_id": wire_id})
            continue
        paths.append(PscadWirePath(wire_id, class_id, vertices))
    return tuple(paths), tuple(warnings)


def _segments(path: PscadWirePath) -> tuple[tuple[tuple[int, int], tuple[int, int]], ...]:
    return tuple(zip(path.vertices, path.vertices[1:]))


def _point_on_segment(point: tuple[int, int], segment: tuple[tuple[int, int], tuple[int, int]]) -> bool:
    (x, y), ((x1, y1), (x2, y2)) = point, segment
    if y1 == y2 == y:
        return min(x1, x2) <= x <= max(x1, x2)
    if x1 == x2 == x:
        return min(y1, y2) <= y <= max(y1, y2)
    return False


def _segments_touch(
    first: tuple[tuple[int, int], tuple[int, int]],
    second: tuple[tuple[int, int], tuple[int, int]],
) -> bool:
    (a1, a2), (b1, b2) = first, second
    if a1[1] == a2[1] and b1[1] == b2[1]:
        return a1[1] == b1[1] and max(min(a1[0], a2[0]), min(b1[0], b2[0])) <= min(max(a1[0], a2[0]), max(b1[0], b2[0]))
    if a1[0] == a2[0] and b1[0] == b2[0]:
        return a1[0] == b1[0] and max(min(a1[1], a2[1]), min(b1[1], b2[1])) <= min(max(a1[1], a2[1]), max(b1[1], b2[1]))
    horizontal, vertical = (first, second) if a1[1] == a2[1] else (second, first)
    (h1, h2), (v1, v2) = horizontal, vertical
    return min(h1[0], h2[0]) <= v1[0] <= max(h1[0], h2[0]) and min(v1[1], v2[1]) <= h1[1] <= max(v1[1], v2[1])


def _paths_touch(first: PscadWirePath, second: PscadWirePath) -> bool:
    return any(_segments_touch(left, right) for left in _segments(first) for right in _segments(second))


def _compatible(first: PscadPortPoint, second: PscadPortPoint) -> bool:
    if first.dimension and second.dimension and first.dimension.casefold() != second.dimension.casefold():
        return False
    inputs = {"in", "input", "sink"}
    outputs = {"out", "output", "source"}
    first_mode, second_mode = first.mode.casefold(), second.mode.casefold()
    return not ((first_mode in inputs and second_mode in inputs) or (first_mode in outputs and second_mode in outputs))


def _scope_connections(
    scope: Element,
    canvas_name: str,
    definitions: dict[str, tuple[dict[str, str], ...]],
    project_path: Path,
) -> tuple[tuple[HvdcConnectionRecord, ...], tuple[dict[str, object], ...]]:
    ports = _component_ports(scope, definitions)
    paths, path_warnings = _wire_paths(scope)
    parent = list(range(len(paths)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = root(left), root(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left in range(len(paths)):
        for right in range(left + 1, len(paths)):
            if _paths_touch(paths[left], paths[right]):
                union(left, right)

    nets: dict[int, list[PscadWirePath]] = {}
    for index, path in enumerate(paths):
        nets.setdefault(root(index), []).append(path)

    records: list[HvdcConnectionRecord] = []
    warnings = list(path_warnings)
    for net_paths in nets.values():
        net_ports = sorted(
            {
                port
                for port in ports
                if any(_point_on_segment(port.point, segment) for path in net_paths for segment in _segments(path))
            },
            key=lambda item: (item.component_id, item.port_name),
        )
        wire_ids = tuple(sorted(path.wire_id for path in net_paths))
        if len(net_ports) != 2:
            warnings.append(
                {
                    "code": "PSCAD_WIRE_NET_AMBIGUOUS",
                    "wire_ids": wire_ids,
                    "port_count": len(net_ports),
                    "ports": tuple(f"{port.component_id}.{port.port_name}" for port in net_ports),
                }
            )
            continue
        if not _compatible(net_ports[0], net_ports[1]):
            warnings.append({"code": "PSCAD_WIRE_PORT_INCOMPATIBLE", "wire_ids": wire_ids})
            continue
        class_ids = tuple(dict.fromkeys(path.class_id for path in sorted(net_paths, key=lambda item: item.wire_id)))
        evidence = class_ids + ("vertex_coordinates",)
        records.append(
            HvdcConnectionRecord(
                connection_id=wire_ids[0] if len(wire_ids) == 1 else "wire-net:" + "+".join(wire_ids),
                source_component_id=net_ports[0].component_id,
                source_port=net_ports[0].port_name,
                target_component_id=net_ports[1].component_id,
                target_port=net_ports[1].port_name,
                source=HvdcSourceRef(str(project_path), canvas_name),
                evidence=evidence,
            )
        )
    return tuple(records), tuple(warnings)


def scan_pscad_connections(
    root: Element,
    project_path: Path,
    scopes: list[tuple[Element, str]],
) -> tuple[tuple[HvdcConnectionRecord, ...], tuple[dict[str, object], ...]]:
    definitions = _definitions(root)
    connections: list[HvdcConnectionRecord] = []
    warnings: list[dict[str, object]] = []
    for scope, canvas_name in scopes:
        scoped_connections, scoped_warnings = _scope_connections(scope, canvas_name, definitions, project_path)
        connections.extend(scoped_connections)
        warnings.extend(scoped_warnings)
    return tuple(connections), tuple(warnings)


__all__ = ["PscadPortPoint", "PscadWirePath", "absolute_vertices", "scan_pscad_connections"]
