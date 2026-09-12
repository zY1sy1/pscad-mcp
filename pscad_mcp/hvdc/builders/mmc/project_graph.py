"""Namespace-aware PSCX graph reader used for independent MMC validation."""

from __future__ import annotations

import hashlib
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError
from ....topology.connectivity import build_connectivity
from ....topology.providers.pscx import PscxSnapshotProvider
from ....topology.reconcile import reconcile_snapshots
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


def _read_native_graph(path, *, definition_ports=None, logical_ids=None):
    snapshot = PscxSnapshotProvider(definition_ports).read(path, "Main")
    logical_ids = logical_ids or {}
    original_ports = {port.key: port for component in snapshot.components for port in component.ports}
    original_labels = {label.key: label for label in snapshot.labels}
    # First discover physical contact without merging same-name label aliases.
    # Native WireOrthogonal objects do not encode electrical/data namespaces.
    physical = replace(
        snapshot,
        components=tuple(replace(component, ports=tuple(replace(port, kind="electrical") for port in component.ports)) for component in snapshot.components),
        conductors=tuple(replace(wire, namespace="electrical") for wire in snapshot.conductors),
        labels=tuple(replace(label, namespace="electrical", name=label.key) for label in snapshot.labels),
        boundary_links=tuple(replace(link, namespace="electrical") for link in snapshot.boundary_links),
    )
    physical_nets = build_connectivity(reconcile_snapshots(None, physical))
    wire_kinds = {}
    for net in physical_nets.topology.nets:
        kinds = {original_ports[key].kind for key in net.port_keys if key in original_ports and original_ports[key].kind != "unknown"}
        kinds.update(original_labels[key].namespace for key in net.label_keys if original_labels[key].namespace != "unknown")
        if len(kinds) > 1:
            raise _error("Native wire joins electrical and data terminals.", net=net.key)
        kind = next(iter(kinds), "unknown")
        wire_kinds.update((key, kind) for key in net.conductor_keys)
    typed = replace(snapshot, conductors=tuple(replace(wire, namespace=wire_kinds.get(wire.key, "unknown")) for wire in snapshot.conductors))
    connected = build_connectivity(reconcile_snapshots(None, typed))
    topology = connected.topology
    ids = {component.key: logical_ids.get(component.key, component.key) for component in snapshot.components}
    components = tuple(GraphComponent(
        ids[component.key], component.definition, component.location or (0, 0),
        component.orientation or 0,
        tuple(GraphPort(port.name, "signal" if port.kind == "data" else port.kind, port.dimension or 0,
                        source={"native_port_key": port.key, "absolute": port.absolute}) for port in component.ports),
        parameters=dict(component.parameters), canvas=component.canvas_key,
        source={"element": "User", "native_id": component.object_id, "source_sha256": snapshot.source_fingerprint},
    ) for component in snapshot.components)
    port_endpoints = {port.key: f"{ids[component.key]}:{port.name}" for component in snapshot.components for port in component.ports}
    wires = {wire.key: wire for wire in topology.conductors}
    nets = tuple(GraphNet(
        net.key, net.namespace,
        tuple(port_endpoints[key] for key in net.port_keys if key in port_endpoints),
        vertices=wires[net.conductor_keys[0]].vertices if len(net.conductor_keys) == 1 else (),
        label=original_labels[net.label_keys[0]].name if len(net.label_keys) == 1 else None,
        source={"element": "Wire", "conductor_keys": net.conductor_keys, "label_keys": net.label_keys,
                "source_sha256": snapshot.source_fingerprint},
    ) for net in topology.nets)
    outputs = []
    for component in snapshot.components:
        if component.definition != "master:pgb":
            continue
        parameters = dict(component.parameters)
        name, group = parameters.get("Name", ""), parameters.get("Group", "")
        outputs.append(GraphOutput(ids[component.key], "/".join(filter(None, (component.canvas_key, group, name))),
                                   parameters.get("Units", "1"), "unknown", source={"native_id": component.object_id}))
    unresolved = set(topology.unresolved)
    unresolved.update("missing_port_contract:" + component.key for component in snapshot.components if not component.ports)
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != snapshot.source_fingerprint:
        raise _error("Native PSCX changed while its topology was read.")
    return MmcProjectGraph(snapshot.project_name, components, nets, tuple(outputs), str(path), {
        "format": "native_pscx", "source_sha256": snapshot.source_fingerprint,
        "unresolved": tuple(sorted(unresolved)),
        "ambiguous_crossings": connected.ambiguous_crossings,
        "malformed_conductors": connected.malformed_conductors,
        "native_component_count": len(snapshot.components),
        "native_wire_count": len(snapshot.conductors), "native_label_count": len(snapshot.labels),
    })


def read_project_graph(path: str | Path, *, definition_ports=None, logical_ids=None) -> MmcProjectGraph:
    """Read only structured PSCX graph fields; no regular-expression parsing."""

    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file():
        raise _error("PSCX file does not exist.", path=str(source_path))
    try:
        root = ET.parse(source_path).getroot()
    except (OSError, ET.ParseError) as error:
        raise _error("PSCX XML could not be parsed.", path=str(source_path), parse_error=str(error)) from error
    if any(_local(element.tag) == "user" for element in root.iter()):
        return _read_native_graph(source_path, definition_ports=definition_ports, logical_ids=logical_ids)
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
