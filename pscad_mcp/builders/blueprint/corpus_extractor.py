"""Bounded, read-only extraction of admitted PSCAD project XML."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import unicodedata
import xml.etree.ElementTree as ET

from ...core.backend.base import BackendError
from .corpus_models import (
    CorpusCanvas,
    CorpusComponent,
    CorpusConnection,
    CorpusDefinition,
    CorpusDependency,
    CorpusOutputChannel,
    CorpusSource,
    CorpusWarning,
    DefinitionParameter,
    DefinitionPort,
    ProjectGraph,
)
from .models import freeze


_ALLOWED_SETTINGS = {
    "time_duration",
    "time_step",
    "sample_step",
    "chatter_threshold",
    "branch_threshold",
    "StartType",
    "PlotType",
    "SnapType",
    "SnapTime",
    "MrunType",
    "Mruns",
    "Scenario",
    "Advanced",
    "Options",
    "Build",
    "Warn",
    "Check",
    "description",
}
_KNOWN_ELEMENTS = {
    "project",
    "paramlist",
    "param",
    "Layers",
    "Layer",
    "definitions",
    "Definition",
    "form",
    "category",
    "parameter",
    "value",
    "svg",
    "port",
    "cond",
    "rect",
    "text",
    "line",
    "Line",
    "path",
    "error_msg",
    "regex",
    "script",
    "graphics",
    "Port",
    "ellipse",
    "schematic",
    "User",
    "Wire",
    "vertex",
    "references",
    "using",
    "Frame",
    "Control",
    "Graph",
    "Curve",
    "Sticky",
    "Instrument",
    "Gfx",
    "List",
    "Settings",
    "ref",
    "hierarchy",
    "call",
    "output",
    "sample",
    "domain",
    "analog",
    "digital",
    "grouping",
    "row",
    "help",
    "channel",
}
_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


@dataclass(frozen=True)
class ExtractionLimits:
    max_file_bytes: int = 8 * 1024 * 1024
    max_elements: int = 100_000
    max_text_chars: int = 4 * 1024 * 1024
    max_unknown_names: int = 128

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


def _error(code: str, message: str, project_id: str, **details: Any) -> BackendError:
    return BackendError(code, message, "corpus", "extract_project", {"project_id": project_id, **details})


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_child(root: Path, basename: str, project_id: str) -> Path:
    if not basename or Path(basename).name != basename or "/" in basename or "\\" in basename:
        raise _error("CORPUS_SOURCE_INVALID", "Admitted source name is not a simple basename.", project_id)
    candidate = root / basename
    if not candidate.exists():
        raise _error("CORPUS_SOURCE_MISSING", "An admitted source file is missing.", project_id, basename=basename)
    if candidate.is_symlink() or not candidate.is_file():
        raise _error("CORPUS_SOURCE_INVALID", "An admitted source must be a regular non-link file.", project_id, basename=basename)
    return candidate


def _verify_size(path: Path, expected: int, limits: ExtractionLimits, project_id: str, basename: str) -> None:
    observed = path.stat().st_size
    if observed > limits.max_file_bytes:
        raise _error(
            "CORPUS_SOURCE_TOO_LARGE",
            "An admitted source exceeds the extraction size limit.",
            project_id,
            basename=basename,
            byte_length=observed,
            max_file_bytes=limits.max_file_bytes,
        )
    if observed != expected:
        raise _error(
            "CORPUS_SOURCE_SIZE_MISMATCH",
            "An admitted source byte length does not match its specification.",
            project_id,
            basename=basename,
            expected_byte_length=expected,
            observed_byte_length=observed,
        )


def _verify_hash(path: Path, expected: str, project_id: str, basename: str) -> str:
    observed = sha256_file(path)
    if observed != expected:
        raise _error(
            "CORPUS_SOURCE_HASH_MISMATCH",
            "An admitted source hash does not match its specification.",
            project_id,
            basename=basename,
            expected_sha256=expected,
            observed_sha256=observed,
        )
    return observed


def _admit_file(
    root: Path,
    basename: str,
    byte_length: int,
    expected_hash: str,
    limits: ExtractionLimits,
    project_id: str,
) -> tuple[Path, str]:
    path = _regular_child(root, basename, project_id)
    _verify_size(path, byte_length, limits, project_id, basename)
    return path, _verify_hash(path, expected_hash, project_id, basename)


def _bounded_parse(content: bytes, limits: ExtractionLimits, project_id: str) -> ET.Element:
    upper = content.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise _error("CORPUS_XML_UNSAFE", "PSCAD corpus XML cannot contain DTD or entity declarations.", project_id)
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise _error("CORPUS_XML_MALFORMED", "PSCAD corpus XML is malformed.", project_id) from error
    elements = 0
    text_chars = 0
    for element in root.iter():
        elements += 1
        text_chars += len(element.text or "") + len(element.tail or "")
        if elements > limits.max_elements or text_chars > limits.max_text_chars:
            raise _error(
                "CORPUS_XML_TOO_COMPLEX",
                "PSCAD corpus XML exceeds configured complexity bounds.",
                project_id,
                elements=elements,
                text_chars=text_chars,
            )
    return root


def _project_settings(root: ET.Element) -> dict[str, str]:
    settings: dict[str, str] = {}
    for paramlist in root.findall("./paramlist"):
        if paramlist.get("name") != "Settings":
            continue
        for parameter in paramlist.findall("./param"):
            name = parameter.get("name")
            value = parameter.get("value")
            if name in _ALLOWED_SETTINGS and value is not None:
                settings[name] = value
    return dict(sorted(settings.items()))


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold().replace("_", "-")
    normalized = re.sub(r"[^\w.-]+", "-", normalized, flags=re.UNICODE)
    normalized = re.sub(r"-+", "-", normalized).strip("-.")
    return normalized or "unnamed"


def _integer(value: str | None, field: str, project_id: str, *, default: int | None = None) -> int:
    if value is None and default is not None:
        return default
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise _error("CORPUS_XML_INVALID", f"{field} must be an integer.", project_id, field=field) from error


def _unit(value: str | None) -> str:
    normalized = (value or "").strip()
    if normalized.casefold() in {"p.u.", "p.u", "per-unit", "per unit"}:
        return "pu"
    return normalized


def _safe_value(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if _ABSOLUTE_PATH.match(stripped):
        return None
    return stripped


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _unique_keys(values: list[Any], project_id: str, kind: str) -> None:
    keys = [value.key for value in values]
    if len(set(keys)) != len(keys):
        raise _error(
            "CORPUS_LOGICAL_KEY_COLLISION",
            "Normalized logical keys are not unique.",
            project_id,
            record_kind=kind,
        )


def _definition_key(name: str) -> str:
    return f"definition:user:{_slug(name)}"


def _definition_reference(
    value: str | None,
    project_name: str,
    local_definitions: dict[str, str],
    project_id: str,
) -> str:
    if not value:
        raise _error("CORPUS_REFERENCE_UNRESOLVED", "A component definition reference is empty.", project_id)
    if ":" in value:
        namespace, local_name = value.split(":", 1)
        if namespace.casefold() in {project_name.casefold(), "user"}:
            observed = local_definitions.get(local_name.casefold())
            if observed is None:
                raise _error(
                    "CORPUS_REFERENCE_UNRESOLVED",
                    "A local component definition reference is missing.",
                    project_id,
                    definition=value,
                )
            return observed
        return f"definition:{_slug(namespace)}:{_slug(local_name)}"
    observed = local_definitions.get(value.casefold())
    if observed is None:
        raise _error(
            "CORPUS_REFERENCE_UNRESOLVED",
            "An unqualified component definition reference is missing.",
            project_id,
            definition=value,
        )
    return observed


def _definition_parameters(element: ET.Element, project_id: str) -> tuple[DefinitionParameter, ...]:
    parameters: list[DefinitionParameter] = []
    names: set[str] = set()
    for parameter in element.findall("./form/category/parameter"):
        name = parameter.get("name")
        if not name or name.casefold() in names:
            raise _error("CORPUS_LOGICAL_KEY_COLLISION", "Definition parameter names must be unique.", project_id)
        names.add(name.casefold())
        default_element = parameter.find("./value")
        default = _safe_value(default_element.text if default_element is not None else None)
        parameters.append(
            DefinitionParameter(
                name=name,
                type=(parameter.get("type") or "").strip().casefold(),
                dimension=(parameter.get("dim") or "1").strip(),
                units=_unit(parameter.get("unit")),
                minimum=_safe_value(parameter.get("min")),
                maximum=_safe_value(parameter.get("max")),
                intent=(parameter.get("intent") or "").strip().casefold(),
                default=default,
            )
        )
    return tuple(sorted(parameters, key=lambda item: (item.name.casefold(), item.name)))


def _definition_ports(element: ET.Element, definition_key: str, project_id: str) -> tuple[DefinitionPort, ...]:
    candidates: list[tuple[str, str, str, str, str, int, int]] = []
    for port in element.findall("./svg/port"):
        name = port.get("name")
        if not name:
            raise _error("CORPUS_XML_INVALID", "Definition ports require names.", project_id)
        candidates.append(
            (
                name,
                (port.get("model") or "").strip().casefold(),
                (port.get("dim") or "1").strip(),
                (port.get("mode") or "").strip().casefold(),
                (port.get("type") or "").strip().casefold(),
                _integer(port.get("x"), "port.x", project_id),
                _integer(port.get("y"), "port.y", project_id),
            )
        )
    candidates.sort(key=lambda item: (item[0].casefold(), item[1:]))
    ordinals: dict[str, int] = {}
    ports: list[DefinitionPort] = []
    for name, model, dimension, mode, port_type, x, y in candidates:
        base = _slug(name)
        ordinals[base] = ordinals.get(base, 0) + 1
        ports.append(
            DefinitionPort(
                key=f"{definition_key}/port:{base}#{ordinals[base]}",
                name=name,
                model=model,
                dimension=dimension,
                mode=mode,
                type=port_type,
                offset=(x, y),
            )
        )
    return tuple(ports)


def _definitions_and_canvases(
    root: ET.Element,
    project_id: str,
) -> tuple[tuple[CorpusDefinition, ...], tuple[CorpusCanvas, ...], dict[str, str], list[tuple[ET.Element, str]]]:
    elements = list(root.findall("./definitions/Definition"))
    local_definitions: dict[str, str] = {}
    for element in elements:
        name = element.get("name")
        if not name:
            raise _error("CORPUS_XML_INVALID", "Definitions require names.", project_id)
        folded = name.casefold()
        key = _definition_key(name)
        if folded in local_definitions or key in local_definitions.values():
            raise _error("CORPUS_LOGICAL_KEY_COLLISION", "Definition logical keys must be unique.", project_id)
        local_definitions[folded] = key

    definitions: list[CorpusDefinition] = []
    canvases: list[CorpusCanvas] = []
    schematic_elements: list[tuple[ET.Element, str]] = []
    for element in elements:
        name = element.get("name") or ""
        key = local_definitions[name.casefold()]
        schematic = element.find("./schematic")
        canvas_key = f"canvas:{_slug(name)}" if schematic is not None else None
        definitions.append(
            CorpusDefinition(
                key=key,
                name=name,
                class_id=(element.get("classid") or "").strip().casefold(),
                parameters=_definition_parameters(element, project_id),
                ports=_definition_ports(element, key, project_id),
                canvas_key=canvas_key,
            )
        )
        if schematic is not None and canvas_key is not None:
            canvases.append(
                CorpusCanvas(
                    key=canvas_key,
                    name=name,
                    owner_definition=key,
                    class_id=(schematic.get("classid") or "").strip().casefold(),
                )
            )
            schematic_elements.append((schematic, canvas_key))
    definitions.sort(key=lambda item: item.key)
    canvases.sort(key=lambda item: item.key)
    _unique_keys(definitions, project_id, "definition")
    _unique_keys(canvases, project_id, "canvas")
    return tuple(definitions), tuple(canvases), local_definitions, schematic_elements


def _instance_parameters(element: ET.Element, project_id: str) -> dict[str, str]:
    entries: list[tuple[int, str, str]] = []
    counts: dict[str, int] = {}
    for group_index, paramlist in enumerate(element.findall("./paramlist"), start=1):
        for parameter in paramlist.findall("./param"):
            name = parameter.get("name")
            value = _safe_value(parameter.get("value"))
            if not name or value is None:
                continue
            entries.append((group_index, name, value))
            counts[name] = counts.get(name, 0) + 1
    parameters: dict[str, str] = {}
    for group_index, name, value in entries:
        key = name if counts[name] == 1 else f"group-{group_index}:{name}"
        if key in parameters:
            raise _error("CORPUS_LOGICAL_KEY_COLLISION", "Instance parameter keys are ambiguous.", project_id)
        parameters[key] = value
    return dict(sorted(parameters.items()))


def _components(
    schematic_elements: list[tuple[ET.Element, str]],
    project_name: str,
    local_definitions: dict[str, str],
    project_id: str,
) -> tuple[tuple[CorpusComponent, ...], dict[int, str]]:
    candidates: list[dict[str, Any]] = []
    for schematic, canvas_key in schematic_elements:
        instance_elements: list[tuple[ET.Element, ET.Element | None]] = [
            (element, None) for element in schematic.findall("./User")
        ]
        instance_elements.extend((element, wire) for wire in schematic.findall("./Wire") for element in wire.findall("./User"))
        for element, parent_wire in instance_elements:
            runtime_id = _integer(element.get("id"), "component.id", project_id)
            location_source = parent_wire if parent_wire is not None else element
            x = _integer(location_source.get("x"), "component.x", project_id, default=0)
            y = _integer(location_source.get("y"), "component.y", project_id, default=0)
            orientation = _integer(location_source.get("orient"), "component.orient", project_id, default=0)
            if orientation not in range(8):
                raise _error("CORPUS_XML_INVALID", "Component orientation must be from 0 through 7.", project_id)
            definition_key = _definition_reference(element.get("defn"), project_name, local_definitions, project_id)
            name = (element.get("name") or element.get("defn") or "unnamed").strip()
            candidates.append(
                {
                    "runtime_id": runtime_id,
                    "canvas_key": canvas_key,
                    "definition_key": definition_key,
                    "name": name,
                    "x": x,
                    "y": y,
                    "orientation": orientation,
                    "parameters": _instance_parameters(element, project_id),
                }
            )
    candidates.sort(
        key=lambda item: (
            item["canvas_key"],
            item["definition_key"],
            item["x"],
            item["y"],
            item["name"].casefold(),
            item["orientation"],
            json.dumps(item["parameters"], sort_keys=True, ensure_ascii=True),
        )
    )
    ordinals: dict[str, int] = {}
    runtime_keys: dict[int, str] = {}
    components: list[CorpusComponent] = []
    for item in candidates:
        local_definition = item["definition_key"].rsplit(":", 1)[-1]
        base = f"{item['canvas_key']}/component:{local_definition}@{item['x']},{item['y']}"
        ordinals[base] = ordinals.get(base, 0) + 1
        key = f"{base}#{ordinals[base]}"
        if item["runtime_id"] in runtime_keys:
            raise _error("CORPUS_LOGICAL_KEY_COLLISION", "Runtime component IDs are ambiguous within one parse.", project_id)
        runtime_keys[item["runtime_id"]] = key
        components.append(
            CorpusComponent(
                key=key,
                canvas_key=item["canvas_key"],
                definition_key=item["definition_key"],
                name=item["name"],
                location=(item["x"], item["y"]),
                orientation=item["orientation"],
                parameters=freeze(item["parameters"]),
                resolved=True,
            )
        )
    _unique_keys(components, project_id, "component")
    return tuple(components), runtime_keys


def _wire_connections(
    schematic_elements: list[tuple[ET.Element, str]],
    project_name: str,
    local_definitions: dict[str, str],
    runtime_keys: dict[int, str],
    project_id: str,
) -> list[CorpusConnection]:
    candidates: list[dict[str, Any]] = []
    for schematic, canvas_key in schematic_elements:
        for wire in schematic.findall("./Wire"):
            x = _integer(wire.get("x"), "wire.x", project_id, default=0)
            y = _integer(wire.get("y"), "wire.y", project_id, default=0)
            vertices = tuple(
                (x + _integer(vertex.get("x"), "vertex.x", project_id), y + _integer(vertex.get("y"), "vertex.y", project_id))
                for vertex in wire.findall("./vertex")
            )
            if not vertices:
                width = _integer(wire.get("w"), "wire.w", project_id, default=0)
                height = _integer(wire.get("h"), "wire.h", project_id, default=0)
                vertices = ((x, y), (x + width, y + height)) if width or height else ((x, y),)
            endpoint_keys: list[str] = []
            for attribute in ("send", "recv"):
                raw = wire.get(attribute)
                if raw in {None, "", "0", "-1"}:
                    continue
                runtime_id = _integer(raw, f"wire.{attribute}", project_id)
                endpoint = runtime_keys.get(runtime_id)
                if endpoint is None:
                    raise _error(
                        "CORPUS_REFERENCE_UNRESOLVED",
                        "An explicit wire endpoint reference is missing.",
                        project_id,
                        reference_kind=attribute,
                    )
                endpoint_keys.append(endpoint)
            kind = (wire.get("classid") or "wire").strip().casefold()
            source_definition = None
            if wire.get("defn"):
                builtin_stub = kind == "wirebranch" and wire.get("defn") == "STUB" and wire.find("./User") is not None
                source_definition = (
                    "definition:builtin:stub"
                    if builtin_stub
                    else _definition_reference(wire.get("defn"), project_name, local_definitions, project_id)
                )
            signature = {
                "canvas": canvas_key,
                "kind": kind,
                "vertices": vertices,
                "endpoints": endpoint_keys,
                "source_definition": source_definition,
            }
            candidates.append({**signature, "digest": _stable_hash(signature)[:16]})
    candidates.sort(key=lambda item: (item["canvas"], item["kind"], item["digest"], item["vertices"]))
    ordinals: dict[str, int] = {}
    connections: list[CorpusConnection] = []
    for item in candidates:
        base = f"{item['canvas']}/connection:{item['kind']}:{item['digest']}"
        ordinals[base] = ordinals.get(base, 0) + 1
        endpoints = tuple(item["endpoints"])
        connections.append(
            CorpusConnection(
                key=f"{base}#{ordinals[base]}",
                canvas_key=item["canvas"],
                kind=item["kind"],
                vertices=tuple(item["vertices"]),
                endpoints=endpoints,
                source_definition=item["source_definition"],
                resolution="explicit" if endpoints else "geometry_only",
            )
        )
    return connections


def _hierarchy_connections(root: ET.Element, runtime_keys: dict[int, str], project_id: str) -> list[CorpusConnection]:
    hierarchy = root.find("./hierarchy")
    if hierarchy is None:
        return []
    project_endpoint = f"project:{_slug(root.get('name') or project_id)}"
    candidates: list[tuple[str, str]] = []

    def visit(call: ET.Element, parent: str, depth: int) -> None:
        runtime_id = _integer(call.get("link"), "hierarchy.call.link", project_id)
        endpoint = runtime_keys.get(runtime_id)
        if endpoint is None:
            call_name = (call.get("name") or "").strip()
            local_name = call_name.rsplit(":", 1)[-1].casefold()
            virtual_root = (
                depth == 0
                and local_name == "station"
                and call.get("instance") == "0"
                and (call.get("view") or "").casefold() == "false"
                and bool(call.findall("./call"))
            )
            if not virtual_root:
                raise _error("CORPUS_REFERENCE_UNRESOLVED", "A hierarchy call target is missing.", project_id)
            endpoint = "hierarchy-root:station"
        candidates.append((parent, endpoint))
        for child in call.findall("./call"):
            visit(child, endpoint, depth + 1)

    for call in hierarchy.findall("./call"):
        visit(call, project_endpoint, 0)
    candidates.sort()
    ordinals: dict[str, int] = {}
    connections: list[CorpusConnection] = []
    for parent, endpoint in candidates:
        digest = _stable_hash([parent, endpoint])[:16]
        base = f"hierarchy:{digest}"
        ordinals[base] = ordinals.get(base, 0) + 1
        connections.append(
            CorpusConnection(
                key=f"{base}#{ordinals[base]}",
                canvas_key=None,
                kind="hierarchy",
                vertices=(),
                endpoints=(parent, endpoint),
                source_definition=None,
                resolution="explicit",
            )
        )
    return connections


def _output_channels(
    root: ET.Element,
    runtime_keys: dict[int, str],
    project_id: str,
) -> tuple[tuple[CorpusOutputChannel, ...], tuple[CorpusWarning, ...]]:
    channels: list[CorpusOutputChannel] = []
    unresolved = 0
    for channel in root.findall("./output/analog/channel"):
        index = _integer(channel.get("index"), "output.channel.index", project_id)
        binding = channel.get("id") or ""
        runtime_text, separator, source_port = binding.partition(":")
        source_component = None
        if separator:
            try:
                source_component = runtime_keys.get(int(runtime_text))
            except ValueError:
                source_component = None
        if source_component is None:
            unresolved += 1
        name = (channel.get("name") or channel.get("label") or "unnamed").strip() or "unnamed"
        channels.append(
            CorpusOutputChannel(
                key=f"output:{index}:{_slug(name)}",
                name=name,
                label=(channel.get("label") or "").strip(),
                dimension=(channel.get("dim") or "1").strip(),
                units=_unit(channel.get("unit")),
                minimum=_safe_value(channel.get("min")),
                maximum=_safe_value(channel.get("max")),
                source_component=source_component,
                source_port=source_port,
                resolved=source_component is not None,
            )
        )
    channels.sort(key=lambda item: item.key)
    _unique_keys(channels, project_id, "output_channel")
    warnings = (
        (CorpusWarning("unresolved_output_binding", "project/output/analog/channel", unresolved, False),)
        if unresolved
        else ()
    )
    return tuple(channels), warnings


def _unknown_warnings(root: ET.Element, limits: ExtractionLimits, project_id: str) -> tuple[CorpusWarning, ...]:
    counts: dict[str, tuple[int, bool]] = {}

    def visit(element: ET.Element, parents: tuple[str, ...]) -> None:
        path_parts = (*parents, element.tag)
        if element.tag not in _KNOWN_ELEMENTS:
            path = "/".join(path_parts)
            blocking = any(parent in {"definitions", "hierarchy", "output"} for parent in parents)
            count, prior_blocking = counts.get(path, (0, False))
            counts[path] = (count + 1, prior_blocking or blocking)
            if len(counts) > limits.max_unknown_names:
                raise _error("CORPUS_XML_TOO_COMPLEX", "Too many unknown XML element names were observed.", project_id)
        for child in list(element):
            visit(child, path_parts)

    visit(root, ())
    return tuple(
        CorpusWarning("unknown_element", path, count, blocking)
        for path, (count, blocking) in counts.items()
    )


def _normalize_graph(
    root: ET.Element,
    source: CorpusSource,
    pre_hash: str,
    dependency_hashes: dict[str, str],
    limits: ExtractionLimits,
) -> ProjectGraph:
    project_name = root.get("name") or ""
    definitions, canvases, local_definitions, schematic_elements = _definitions_and_canvases(root, source.project_id)
    components, runtime_keys = _components(
        schematic_elements,
        project_name,
        local_definitions,
        source.project_id,
    )
    connections = _wire_connections(
        schematic_elements,
        project_name,
        local_definitions,
        runtime_keys,
        source.project_id,
    )
    connections.extend(_hierarchy_connections(root, runtime_keys, source.project_id))
    connections.sort(key=lambda item: (item.kind, item.canvas_key or "", item.endpoints, item.vertices, item.key))
    _unique_keys(connections, source.project_id, "connection")
    output_channels, output_warnings = _output_channels(root, runtime_keys, source.project_id)
    return ProjectGraph(
        project_id=source.project_id,
        source_sha256=pre_hash,
        dependency_hashes=freeze(dependency_hashes),
        name=project_name,
        pscad_version=root.get("version") or "",
        target=root.get("Target") or "",
        settings=freeze(_project_settings(root)),
        definitions=definitions,
        canvases=canvases,
        components=components,
        connections=tuple(connections),
        output_channels=output_channels,
        warnings=(*_unknown_warnings(root, limits, source.project_id), *output_warnings),
    )


def graph_signature(graph: ProjectGraph) -> str:
    """Hash normalized engineering structure without source or dependency hashes."""

    value = graph.to_dict()
    value.pop("source_sha256", None)
    value.pop("dependency_hashes", None)
    return _stable_hash(value)


def _dependency_values(source: CorpusSource) -> tuple[CorpusDependency, ...]:
    return tuple(sorted(source.dependencies, key=lambda dependency: dependency.basename))


def extract_project(
    source_root: str | Path,
    source: CorpusSource,
    limits: ExtractionLimits | None = None,
) -> ProjectGraph:
    """Extract a portable project header while proving admitted files did not change."""

    configured_limits = limits or ExtractionLimits()
    try:
        root_directory = Path(source_root).resolve(strict=True)
    except OSError as error:
        raise _error("CORPUS_SOURCE_MISSING", "The corpus source root is unavailable.", source.project_id) from error
    if not root_directory.is_dir():
        raise _error("CORPUS_SOURCE_INVALID", "The corpus source root must be a directory.", source.project_id)

    source_path, pre_hash = _admit_file(
        root_directory,
        source.basename,
        source.byte_length,
        source.sha256,
        configured_limits,
        source.project_id,
    )
    dependency_paths: list[tuple[CorpusDependency, Path]] = []
    dependency_hashes: dict[str, str] = {}
    for dependency in _dependency_values(source):
        dependency_path, dependency_hash = _admit_file(
            root_directory,
            dependency.basename,
            dependency.byte_length,
            dependency.sha256,
            configured_limits,
            source.project_id,
        )
        dependency_paths.append((dependency, dependency_path))
        dependency_hashes[dependency.basename] = dependency_hash

    content = source_path.read_bytes()
    if hashlib.sha256(content).hexdigest() != pre_hash:
        raise _error("CORPUS_SOURCE_CHANGED", "Source changed while it was being read.", source.project_id)
    root = _bounded_parse(content, configured_limits, source.project_id)
    if root.tag != "project":
        raise _error("CORPUS_XML_UNSUPPORTED_ROOT", "PSCAD corpus XML root must be project.", source.project_id, root_tag=root.tag)
    name = root.get("name")
    pscad_version = root.get("version")
    target = root.get("Target")
    if not name or not pscad_version or not target:
        raise _error("CORPUS_XML_INVALID", "PSCAD project identity fields are incomplete.", source.project_id)
    if pscad_version not in source.pscad_versions:
        raise _error(
            "CORPUS_SOURCE_VERSION_MISMATCH",
            "Observed PSCAD version is not admitted by the source specification.",
            source.project_id,
            observed_version=pscad_version,
            expected_versions=list(source.pscad_versions),
        )

    post_hash = sha256_file(source_path)
    if post_hash != pre_hash or source_path.stat().st_size != source.byte_length:
        raise _error("CORPUS_SOURCE_CHANGED", "Source changed during extraction.", source.project_id)
    for dependency, dependency_path in dependency_paths:
        if sha256_file(dependency_path) != dependency.sha256 or dependency_path.stat().st_size != dependency.byte_length:
            raise _error(
                "CORPUS_SOURCE_CHANGED",
                "A dependency changed during extraction.",
                source.project_id,
                basename=dependency.basename,
            )

    return _normalize_graph(root, source, pre_hash, dependency_hashes, configured_limits)
