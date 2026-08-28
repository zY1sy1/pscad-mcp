"""Namespace-aware PSCX graph reader used for independent MMC validation."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError
from ..common.records import JsonRecord, freeze


def _error(message: str, **details: Any) -> BackendError:
    return BackendError("MMC_STRUCTURE_INVALID", message, "hvdc", "read_mmc_project_graph", details)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _text(value: str | None, context: str) -> str:
    result = (value or "").strip()
    if not result:
        raise _error(f"{context} must be non-empty.", context=context)
    return result


def _integer(value: str | None, context: str, *, default: int | None = None) -> int:
    raw = value if value is not None else default
    try:
        if isinstance(raw, bool) or raw is None:
            raise ValueError
        number = int(raw)
    except (TypeError, ValueError):
        raise _error(f"{context} must be an integer.", context=context) from None
    return number


@dataclass(frozen=True)
class GraphPort(JsonRecord):
    name: str
    kind: str
    dimension: int
    role: str | None = None
    source: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", freeze(self.source))


@dataclass(frozen=True)
class GraphComponent(JsonRecord):
    logical_id: str
    definition: str
    location: tuple[int, int]
    orientation: int
    ports: tuple[GraphPort, ...]
    role: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    canvas: str = "Main"
    source: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "ports", tuple(self.ports))
        object.__setattr__(self, "parameters", freeze(self.parameters))
        object.__setattr__(self, "source", freeze(self.source))


@dataclass(frozen=True)
class GraphNet(JsonRecord):
    logical_id: str
    kind: str
    endpoints: tuple[str, ...]
    vertices: tuple[tuple[int, int], ...] = ()
    label: str | None = None
    source: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "endpoints", tuple(self.endpoints))
        object.__setattr__(self, "vertices", tuple(tuple(point) for point in self.vertices))
        object.__setattr__(self, "source", freeze(self.source))


@dataclass(frozen=True)
class GraphOutput(JsonRecord):
    logical_id: str
    path: str
    units: str
    role: str
    measurement: str | None = None
    source: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", freeze(self.source))


@dataclass(frozen=True)
class MmcProjectGraph(JsonRecord):
    project_name: str
    components: tuple[GraphComponent, ...]
    nets: tuple[GraphNet, ...]
    outputs: tuple[GraphOutput, ...]
    source_path: str
    source: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "components", tuple(self.components))
        object.__setattr__(self, "nets", tuple(self.nets))
        object.__setattr__(self, "outputs", tuple(self.outputs))
        object.__setattr__(self, "source", freeze(self.source))


ProjectGraph = MmcProjectGraph


def _child_elements(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(element) if _local(child.tag) == name]


def _parse_component(element: ET.Element, canvas: str, index: int) -> GraphComponent:
    logical_id = _text(element.attrib.get("logical_id") or element.attrib.get("id") or element.attrib.get("name"), f"component[{index}].logical_id")
    definition = _text(element.attrib.get("definition") or element.attrib.get("scoped_name"), f"component[{index}].definition")
    ports: list[GraphPort] = []
    for port_index, port in enumerate(_child_elements(element, "port")):
        port_name = _text(port.attrib.get("name"), f"component[{index}].ports[{port_index}].name")
        kind = _text(port.attrib.get("kind", "signal"), f"component[{index}].ports[{port_index}].kind")
        dimension = _integer(port.attrib.get("dimension"), f"component[{index}].ports[{port_index}].dimension", default=1)
        ports.append(GraphPort(port_name, kind, dimension, port.attrib.get("role"), {"element": "port", "component": logical_id, "index": port_index}))
    if len({port.name for port in ports}) != len(ports):
        raise _error("component contains duplicate ports.", component=logical_id)
    parameters: dict[str, Any] = {}
    for parameter in _child_elements(element, "parameter"):
        name = _text(parameter.attrib.get("name"), f"component[{index}].parameter.name")
        raw = parameter.attrib.get("value")
        if raw is None:
            continue
        try:
            value: Any = float(raw) if any(character in raw for character in ".eE") else int(raw)
        except ValueError:
            value = raw
        if isinstance(value, float) and not math.isfinite(value):
            raise _error("component parameter is non-finite.", component=logical_id, parameter=name)
        parameters[name] = value
    return GraphComponent(logical_id, definition, (_integer(element.attrib.get("x"), f"component[{index}].x", default=0), _integer(element.attrib.get("y"), f"component[{index}].y", default=0)), _integer(element.attrib.get("orientation"), f"component[{index}].orientation", default=0), tuple(ports), element.attrib.get("role"), parameters, canvas, {"element": "component", "logical_id": logical_id, "canvas": canvas, "index": index})


def _parse_net(element: ET.Element, index: int) -> GraphNet:
    logical_id = _text(element.attrib.get("logical_id") or element.attrib.get("id") or element.attrib.get("name"), f"net[{index}].logical_id")
    kind = _text(element.attrib.get("kind", "electrical"), f"net[{index}].kind")
    endpoints: list[str] = []
    for endpoint_index, endpoint in enumerate(_child_elements(element, "endpoint")):
        component = _text(endpoint.attrib.get("component"), f"net[{index}].endpoints[{endpoint_index}].component")
        port = _text(endpoint.attrib.get("port"), f"net[{index}].endpoints[{endpoint_index}].port")
        endpoints.append(f"{component}:{port}")
    vertices: list[tuple[int, int]] = []
    vertex_container = next(iter(_child_elements(element, "vertices")), None)
    vertex_elements = _child_elements(vertex_container, "point") if vertex_container is not None else _child_elements(element, "point")
    for vertex_index, point in enumerate(vertex_elements):
        vertices.append((_integer(point.attrib.get("x"), f"net[{index}].vertices[{vertex_index}].x"), _integer(point.attrib.get("y"), f"net[{index}].vertices[{vertex_index}].y")))
    return GraphNet(logical_id, kind, tuple(endpoints), tuple(vertices), element.attrib.get("label"), {"element": "net", "logical_id": logical_id, "index": index})


def _parse_output(element: ET.Element, index: int) -> GraphOutput:
    return GraphOutput(_text(element.attrib.get("logical_id") or element.attrib.get("id") or element.attrib.get("name"), f"output[{index}].logical_id"), _text(element.attrib.get("path"), f"output[{index}].path"), _text(element.attrib.get("units", "1"), f"output[{index}].units"), _text(element.attrib.get("role", "unknown"), f"output[{index}].role"), element.attrib.get("measurement"), {"element": "output", "index": index})


def read_project_graph(path: str | Path) -> MmcProjectGraph:
    """Read only structured PSCX graph fields; no regular-expression parsing."""

    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file():
        raise _error("PSCX file does not exist.", path=str(source_path))
    try:
        root = ET.parse(source_path).getroot()
    except (OSError, ET.ParseError) as error:
        raise _error("PSCX XML could not be parsed.", path=str(source_path), parse_error=str(error)) from error
    project_elements = [element for element in root.iter() if _local(element.tag) == "project"]
    project_name = (project_elements[0].attrib.get("name") if project_elements else None) or root.attrib.get("name") or source_path.stem
    components: list[GraphComponent] = []
    nets: list[GraphNet] = []
    outputs: list[GraphOutput] = []
    component_ids: set[str] = set()
    net_ids: set[str] = set()
    output_ids: set[str] = set()
    component_index = net_index = output_index = 0
    for element in root.iter():
        local = _local(element.tag)
        if local == "component":
            canvas = "Main"
            parent = next((candidate for candidate in root.iter() if element in list(candidate)), None)
            if parent is not None and _local(parent.tag) == "canvas":
                canvas = parent.attrib.get("name", "Main")
            component = _parse_component(element, canvas, component_index)
            component_index += 1
            if component.logical_id in component_ids:
                raise _error("duplicate component logical ID.", logical_id=component.logical_id)
            component_ids.add(component.logical_id)
            components.append(component)
        elif local == "net":
            net = _parse_net(element, net_index)
            net_index += 1
            if net.logical_id in net_ids:
                raise _error("duplicate net logical ID.", logical_id=net.logical_id)
            net_ids.add(net.logical_id)
            nets.append(net)
        elif local == "output":
            output = _parse_output(element, output_index)
            output_index += 1
            if output.logical_id in output_ids:
                raise _error("duplicate output logical ID.", logical_id=output.logical_id)
            output_ids.add(output.logical_id)
            outputs.append(output)
    return MmcProjectGraph(project_name, tuple(components), tuple(nets), tuple(outputs), str(source_path), {"element": _local(root.tag), "source_path": str(source_path)})


parse_project_graph = read_project_graph


__all__ = ["GraphComponent", "GraphNet", "GraphOutput", "GraphPort", "MmcProjectGraph", "ProjectGraph", "parse_project_graph", "read_project_graph"]
