from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ...core.backend.base import BackendError
from ..geometry import GeometryError, absolute_port
from ..models import (
    DefinitionPortContract,
    EvidenceRef,
    Namespace,
    Point,
    TopologyBoundaryLink,
    TopologyCanvas,
    TopologyComponent,
    TopologyConductor,
    TopologyLabel,
    TopologyPort,
    TopologySnapshot,
)


@dataclass(frozen=True)
class _DefinitionTemplate:
    name: str
    element: ET.Element
    schematic: ET.Element
    ports: tuple[DefinitionPortContract, ...]
    page_ports: tuple[DefinitionPortContract, ...]


@dataclass(frozen=True)
class _CanvasRequest:
    definition_name: str
    canvas_key: str
    parent_key: str | None
    ancestry: tuple[str, ...]


class PscxSnapshotProvider:
    def __init__(
        self,
        definition_ports: Mapping[
            str, tuple[DefinitionPortContract, ...]
        ]
        | None = None,
    ) -> None:
        self.definition_ports = dict(definition_ports or {})
        self._definition_cache: dict[
            tuple[str, str, str], _DefinitionTemplate
        ] = {}

    def read(self, path: str | Path, canvas_name: str) -> TopologySnapshot:
        project_path = Path(path).expanduser().resolve()
        if project_path.suffix.casefold() != ".pscx":
            raise _source_error(project_path, canvas_name, "unsupported_extension")
        try:
            source = project_path.read_bytes()
        except OSError as error:
            raise _source_error(
                project_path, canvas_name, "file_unreadable"
            ) from error
        source_hash = hashlib.sha256(source).hexdigest()
        try:
            root = ET.parse(project_path).getroot()
        except ET.ParseError as error:
            raise _source_error(
                project_path, canvas_name, "xml_parse_error"
            ) from error
        except OSError as error:
            raise _source_error(
                project_path, canvas_name, "file_unreadable"
            ) from error

        project_name = _text(_attr(root, "name", "project_name"))
        if not project_name:
            raise _source_error(
                project_path, canvas_name, "project_identity_missing"
            )
        definitions = {
            name.casefold(): element
            for element in root.iter()
            if _local_name(element.tag) in {"definition", "canvas"}
            for name in [_text(_attr(element, "name", "id"))]
            if name
        }
        if canvas_name.casefold() not in definitions:
            raise _source_error(
                project_path, canvas_name, "requested_canvas_missing"
            )

        canvases: list[TopologyCanvas] = []
        components: list[TopologyComponent] = []
        conductors: list[TopologyConductor] = []
        labels: list[TopologyLabel] = []
        boundary_links: list[TopologyBoundaryLink] = []
        unresolved: set[str] = set()
        queue = deque(
            (
                _CanvasRequest(
                    canvas_name,
                    canvas_name,
                    None,
                    (canvas_name.casefold(),),
                ),
            )
        )

        while queue:
            request = queue.popleft()
            definition_element = definitions.get(request.definition_name.casefold())
            if definition_element is None:
                unresolved.add(
                    f"local_definition_unavailable:{request.canvas_key}"
                )
                continue
            template = self._template(
                project_path,
                source_hash,
                definition_element,
                request.definition_name,
            )
            page_port_keys = tuple(
                f"{request.canvas_key}:{contract.name}"
                for contract in template.page_ports
            )
            canvases.append(
                TopologyCanvas(
                    key=request.canvas_key,
                    name=template.name,
                    parent_key=request.parent_key,
                    page_ports=page_port_keys,
                )
            )
            parsed_components = self._parse_components(
                template,
                request.canvas_key,
                definitions,
                project_path,
                source_hash,
                unresolved,
            )
            components.extend(parsed_components)
            conductors.extend(
                _parse_conductors(
                    template.schematic,
                    request.canvas_key,
                    source_hash,
                    unresolved,
                )
            )
            labels.extend(
                _parse_labels(
                    template.schematic,
                    request.canvas_key,
                    source_hash,
                )
            )

            for component in parsed_components:
                local_name = _local_definition_name(
                    component.definition, definitions
                )
                if local_name is None:
                    continue
                child_key = (
                    f"{request.canvas_key}/{component.object_id}:{local_name}"
                )
                if local_name.casefold() in request.ancestry:
                    unresolved.add(f"hierarchy_cycle:{child_key}")
                    continue
                child_element = definitions[local_name.casefold()]
                child_template = self._template(
                    project_path,
                    source_hash,
                    child_element,
                    local_name,
                )
                links, link_unresolved = _boundary_links(
                    component,
                    child_key,
                    child_template.page_ports,
                    source_hash,
                )
                boundary_links.extend(links)
                unresolved.update(link_unresolved)
                queue.append(
                    _CanvasRequest(
                        local_name,
                        child_key,
                        request.canvas_key,
                        request.ancestry + (local_name.casefold(),),
                    )
                )

        self._discard_stale_cache_entries(project_path, source_hash)
        return TopologySnapshot(
            source="pscx",
            project_name=project_name,
            project_path=str(project_path),
            pscad_version=_text(_attr(root, "version", "pscad_version"))
            or None,
            canvases=tuple(sorted(canvases, key=lambda item: item.key)),
            components=tuple(sorted(components, key=lambda item: item.key)),
            conductors=tuple(sorted(conductors, key=lambda item: item.key)),
            labels=tuple(sorted(labels, key=lambda item: item.key)),
            boundary_links=tuple(
                sorted(boundary_links, key=lambda item: item.key)
            ),
            unresolved=tuple(sorted(unresolved)),
            capabilities=(
                ("components", True),
                ("conductors", True),
                ("hierarchy", True),
                ("labels", True),
                ("ports", True),
            ),
            source_fingerprint=source_hash,
            grid_step=_integer(_attr(root, "grid_step", "grid"), default=1)
            or 1,
        )

    def _template(
        self,
        project_path: Path,
        source_hash: str,
        element: ET.Element,
        definition_name: str,
    ) -> _DefinitionTemplate:
        cache_key = (str(project_path), source_hash, definition_name.casefold())
        cached = self._definition_cache.get(cache_key)
        if cached is not None:
            return cached
        schematic = next(
            (
                child
                for child in element.iter()
                if child is not element
                and _local_name(child.tag) in {"schematic", "canvas"}
            ),
            element,
        )
        ports, page_ports = _definition_port_contracts(element, schematic)
        template = _DefinitionTemplate(
            definition_name,
            element,
            schematic,
            ports,
            page_ports,
        )
        self._definition_cache[cache_key] = template
        return template

    def _parse_components(
        self,
        template: _DefinitionTemplate,
        canvas_key: str,
        definitions: Mapping[str, ET.Element],
        project_path: Path,
        source_hash: str,
        unresolved: set[str],
    ) -> tuple[TopologyComponent, ...]:
        result = []
        for index, element in enumerate(template.schematic.iter()):
            tag = _local_name(element.tag)
            if tag not in {"user", "component"}:
                continue
            if tag == "user" and _text(
                _attr(element, "classid", "class")
            ).casefold() not in {"usercmp", "component", ""}:
                continue
            object_id = _text(_attr(element, "id", "object_id"))
            if not object_id:
                unresolved.add(
                    f"component_identity_unreadable:{canvas_key}:{index}"
                )
                continue
            key = f"{canvas_key}:{object_id}"
            definition = _text(_attr(element, "definition", "defn", "type"))
            if _label_kind(element, definition):
                continue
            if not definition:
                definition = "unknown"
                unresolved.add(f"definition_unavailable:{key}")
            location = _point(element)
            if location is None:
                unresolved.add(f"component_geometry_unreadable:{key}")
            orientation = _orientation(
                _attr(element, "orientation", "orient", "rotation")
            )
            evidence = (_evidence(key, source_hash),)
            explicit_ports = _instance_ports(
                element,
                key,
                location,
                orientation,
                source_hash,
                unresolved,
            )
            if explicit_ports:
                ports = explicit_ports
            else:
                local_name = _local_definition_name(definition, definitions)
                contracts = ()
                if local_name is not None:
                    local_element = definitions[local_name.casefold()]
                    contracts = self._template(
                        project_path,
                        source_hash,
                        local_element,
                        local_name,
                    ).ports
                if not contracts:
                    contracts = self.definition_ports.get(
                        definition,
                        self.definition_ports.get(
                            definition.rsplit(":", 1)[-1], ()
                        ),
                    )
                ports = _ports_from_contracts(
                    contracts,
                    key,
                    location,
                    orientation,
                    source_hash,
                    unresolved,
                )
            result.append(
                TopologyComponent(
                    key=key,
                    canvas_key=canvas_key,
                    object_id=object_id,
                    definition=definition,
                    name=_text(_attr(element, "name", "label")) or None,
                    location=location,
                    orientation=orientation,
                    active=_boolean(_attr(element, "active", "enabled"), True),
                    parameters=_parameters(element),
                    ports=ports,
                    evidence=evidence,
                )
            )
        return tuple(sorted(result, key=lambda item: item.key))

    def _discard_stale_cache_entries(
        self, project_path: Path, source_hash: str
    ) -> None:
        path_text = str(project_path)
        stale = [
            key
            for key in self._definition_cache
            if key[0] == path_text and key[1] != source_hash
        ]
        for key in stale:
            self._definition_cache.pop(key, None)


def _definition_port_contracts(
    element: ET.Element,
    schematic: ET.Element,
) -> tuple[
    tuple[DefinitionPortContract, ...],
    tuple[DefinitionPortContract, ...],
]:
    ports = []
    page_ports = []
    for port in element.iter():
        tag = _local_name(port.tag)
        if tag not in {"port", "pageport"} or _inside(port, schematic):
            continue
        name = _text(_attr(port, "name", "id"))
        offset = _point(port)
        if not name or offset is None:
            continue
        contract = DefinitionPortContract(
            name=name,
            kind=_namespace(_attr(port, "kind", "type"), tag),
            dimension=_integer(_attr(port, "dimension", "dim")),
            offset=offset,
            required=_optional_boolean(_attr(port, "required")),
        )
        ports.append(contract)
        if tag == "pageport" or _boolean(_attr(port, "page"), False):
            page_ports.append(contract)
    return (
        tuple(sorted(ports, key=lambda item: item.name)),
        tuple(sorted(page_ports, key=lambda item: item.name)),
    )


def _inside(element: ET.Element, ancestor: ET.Element) -> bool:
    return element is ancestor or any(element is child for child in ancestor.iter())


def _instance_ports(
    element: ET.Element,
    component_key: str,
    location: Point | None,
    orientation: int | None,
    source_hash: str,
    unresolved: set[str],
) -> tuple[TopologyPort, ...]:
    ports = []
    for port in element.iter():
        if port is element or _local_name(port.tag) != "port":
            continue
        name = _text(_attr(port, "name", "id"))
        if not name:
            continue
        key = f"{component_key}:{name}"
        relative = _point(port)
        absolute = _absolute_or_unresolved(
            key,
            location,
            relative,
            orientation,
            unresolved,
        )
        ports.append(
            TopologyPort(
                key=key,
                component_key=component_key,
                name=name,
                absolute=absolute,
                relative=relative,
                kind=_namespace(_attr(port, "kind", "type"), "port"),
                dimension=_integer(_attr(port, "dimension", "dim")),
                active=_boolean(_attr(port, "active", "enabled"), True),
                required=_optional_boolean(_attr(port, "required")),
                evidence=(_evidence(key, source_hash),),
            )
        )
    return tuple(sorted(ports, key=lambda item: item.key))


def _ports_from_contracts(
    contracts: tuple[DefinitionPortContract, ...],
    component_key: str,
    location: Point | None,
    orientation: int | None,
    source_hash: str,
    unresolved: set[str],
) -> tuple[TopologyPort, ...]:
    result = []
    for contract in contracts:
        key = f"{component_key}:{contract.name}"
        result.append(
            TopologyPort(
                key=key,
                component_key=component_key,
                name=contract.name,
                absolute=_absolute_or_unresolved(
                    key,
                    location,
                    contract.offset,
                    orientation,
                    unresolved,
                ),
                relative=contract.offset,
                kind=contract.kind,
                dimension=contract.dimension,
                required=contract.required,
                evidence=(_evidence(key, source_hash),),
            )
        )
    return tuple(sorted(result, key=lambda item: item.key))


def _absolute_or_unresolved(
    key: str,
    location: Point | None,
    relative: Point | None,
    orientation: int | None,
    unresolved: set[str],
) -> Point | None:
    if location is None or relative is None or orientation is None:
        unresolved.add(f"port_geometry_unresolved:{key}")
        return None
    try:
        return absolute_port(location, relative, orientation)
    except GeometryError:
        unresolved.add(f"port_geometry_unresolved:{key}")
        return None


def _parse_conductors(
    schematic: ET.Element,
    canvas_key: str,
    source_hash: str,
    unresolved: set[str],
) -> tuple[TopologyConductor, ...]:
    result = []
    for index, element in enumerate(schematic.iter()):
        tag = _local_name(element.tag)
        if tag not in {"wire", "bus", "connection", "segment"}:
            continue
        object_id = _text(_attr(element, "id", "object_id")) or str(index)
        key = f"{canvas_key}:{object_id}"
        origin = _point(element, default=(0, 0))
        vertices = []
        unreadable = False
        for vertex in element.iter():
            if vertex is element or _local_name(vertex.tag) not in {
                "vertex",
                "point",
                "node",
            }:
                continue
            relative = _point(vertex)
            if relative is None:
                unreadable = True
                break
            vertices.append((origin[0] + relative[0], origin[1] + relative[1]))
        if unreadable or len(vertices) < 2:
            unresolved.add(f"conductor_geometry_unreadable:{key}")
            continue
        result.append(
            TopologyConductor(
                key=key,
                canvas_key=canvas_key,
                object_id=object_id,
                kind=(
                    "bus"
                    if tag == "bus"
                    or "bus" in _text(_attr(element, "classid")).casefold()
                    else "wire"
                ),
                namespace=_namespace(
                    _attr(element, "namespace", "kind", "type"), tag
                ),
                vertices=tuple(vertices),
                evidence=(_evidence(key, source_hash),),
            )
        )
    return tuple(sorted(result, key=lambda item: item.key))


def _parse_labels(
    schematic: ET.Element,
    canvas_key: str,
    source_hash: str,
) -> tuple[TopologyLabel, ...]:
    result = []
    for index, element in enumerate(schematic.iter()):
        tag = _local_name(element.tag)
        definition = _text(_attr(element, "definition", "defn", "type"))
        kind = _label_kind(element, definition)
        if kind is None:
            continue
        name = ""
        if tag in {"label", "nodelabel", "datalabel"}:
            name = _text(
                _attr(element, "name", "text", "value") or element.text
            )
        if not name:
            parameters = _parameters(element)
            for parameter_name, parameter_value in parameters:
                if parameter_name.casefold() in {"name", "label", "text"}:
                    name = _text(parameter_value)
                    if name:
                        break
        if not name:
            continue
        object_id = _text(_attr(element, "id", "object_id")) or f"label{index}"
        key = f"{canvas_key}:{object_id}"
        result.append(
            TopologyLabel(
                key=key,
                canvas_key=canvas_key,
                object_id=object_id,
                name=name,
                namespace=_namespace(
                    _attr(element, "namespace", "kind", "type"), kind
                ),
                scope=canvas_key,
                location=_point(element),
                evidence=(_evidence(key, source_hash),),
            )
        )
    return tuple(sorted(result, key=lambda item: item.key))


def _label_kind(element: ET.Element, definition: str = "") -> str | None:
    tag = _local_name(element.tag)
    if tag in {"label", "nodelabel", "datalabel"}:
        return tag
    normalized = definition.rsplit(":", 1)[-1].casefold()
    return normalized if normalized in {"nodelabel", "datalabel"} else None


def _boundary_links(
    component: TopologyComponent,
    child_canvas_key: str,
    page_ports: tuple[DefinitionPortContract, ...],
    source_hash: str,
) -> tuple[tuple[TopologyBoundaryLink, ...], tuple[str, ...]]:
    outer_ports = {port.name: port for port in component.ports}
    result = []
    unresolved = []
    for page_port in page_ports:
        outer = outer_ports.get(page_port.name)
        link_key = (
            f"{component.key}:{page_port.name}->"
            f"{child_canvas_key}:{page_port.name}"
        )
        if outer is None or outer.absolute is None:
            unresolved.append(f"hierarchy_boundary_unresolved:{link_key}")
            continue
        namespace = page_port.kind
        dimension = page_port.dimension
        result.append(
            TopologyBoundaryLink(
                key=link_key,
                outer_port_key=outer.key,
                outer_canvas_key=component.canvas_key,
                outer_point=outer.absolute,
                inner_port_key=f"{child_canvas_key}:{page_port.name}",
                inner_canvas_key=child_canvas_key,
                inner_point=page_port.offset,
                namespace=namespace,
                dimension=dimension,
                evidence=(_evidence(link_key, source_hash),),
            )
        )
    return tuple(sorted(result, key=lambda item: item.key)), tuple(unresolved)


def _parameters(element: ET.Element) -> tuple[tuple[str, str], ...]:
    values = {}
    for child in element.iter():
        if _local_name(child.tag) not in {"param", "parameter"}:
            continue
        name = _text(_attr(child, "name", "key"))
        if name:
            values[name] = _text(_attr(child, "value") or child.text)
    return tuple(sorted(values.items()))


def _local_definition_name(
    definition: str,
    definitions: Mapping[str, ET.Element],
) -> str | None:
    candidates = (definition, definition.rsplit(":", 1)[-1])
    for candidate in candidates:
        element = definitions.get(candidate.casefold())
        if element is not None:
            return _text(_attr(element, "name", "id")) or candidate
    return None


def _source_error(path: Path, canvas: str, reason: str) -> BackendError:
    return BackendError(
        "TOPOLOGY_SOURCE_INVALID",
        "Saved PSCX topology could not be read.",
        "topology",
        "read_pscx_topology",
        {"file": path.name, "canvas": canvas, "reason": reason},
    )


def _evidence(reference: str, fingerprint: str) -> EvidenceRef:
    return EvidenceRef("pscx", reference, fingerprint=fingerprint)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _attr(element: ET.Element, *names: str) -> str | None:
    wanted = {name.casefold() for name in names}
    for key, value in element.attrib.items():
        if key.casefold() in wanted:
            return value
    return None


def _text(value: str | None) -> str:
    return (value or "").strip()


def _integer(value: str | None, default: int | None = None) -> int | None:
    if value is None or not value.strip():
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def _orientation(value: str | None) -> int | None:
    if value is None or not value.strip():
        return 0
    try:
        return int(value.strip())
    except ValueError:
        return None


def _point(
    element: ET.Element,
    default: Point | None = None,
) -> Point | None:
    x = _integer(_attr(element, "x", "left"))
    y = _integer(_attr(element, "y", "top"))
    if x is not None and y is not None:
        return x, y
    raw = _text(_attr(element, "location", "position"))
    if raw:
        parts = raw.replace("(", "").replace(")", "").split(",")
        if len(parts) == 2:
            parsed_x = _integer(parts[0])
            parsed_y = _integer(parts[1])
            if parsed_x is not None and parsed_y is not None:
                return parsed_x, parsed_y
    return default


def _namespace(value: str | None, tag: str) -> Namespace:
    normalized = _text(value).casefold()
    if normalized in {"data", "signal", "digital"} or "data" in tag:
        return "data"
    if normalized in {"electrical", "power", "analog", "node"}:
        return "electrical"
    if tag in {"wire", "bus", "nodelabel"}:
        return "electrical"
    return "unknown"


def _boolean(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().casefold() not in {"0", "false", "no", "off"}


def _optional_boolean(value: str | None) -> bool | None:
    if value is None:
        return None
    return _boolean(value, False)
