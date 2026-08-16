"""Read-only, tolerant PSCX evidence extraction."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from .models import (
    HvdcComponentRecord,
    HvdcLabelRecord,
    HvdcProjectEvidence,
    HvdcSourceRef,
)


def _text(value: str | None) -> str:
    return (value or "").strip()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _children_named(parent: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in parent.iter() if _local_name(child.tag) == name]


def _parameter_values(element: ET.Element) -> dict[str, str]:
    parameters: dict[str, str] = {}

    def visit(parent: ET.Element) -> None:
        for child in parent:
            child_name = _local_name(child.tag)
            if child_name == "port":
                continue
            if child_name in {"parameter", "param"}:
                parameter_name = _text(child.attrib.get("name"))
                if parameter_name:
                    parameters[parameter_name] = _text(child.attrib.get("value") or child.text)
            visit(child)

    visit(element)
    return parameters


def _parameter_value(parameters: dict[str, str], name: str) -> str:
    wanted = name.casefold()
    return next((value for key, value in parameters.items() if key.casefold() == wanted), "")


def _label_value(element: ET.Element) -> str:
    value = _text(
        element.text
        or element.attrib.get("name")
        or element.attrib.get("label")
        or element.attrib.get("text")
        or element.attrib.get("value")
    )
    if value:
        return value
    parameters = _parameter_values(element)
    for name in ("Text", "Name", "Label"):
        value = _parameter_value(parameters, name)
        if value:
            return value
    return ""


def _canvas_scopes(root: ET.Element, canvas_name: str) -> list[ET.Element]:
    wanted = canvas_name.casefold()

    def matches(element: ET.Element) -> bool:
        return any(_text(element.attrib.get(key)).casefold() == wanted for key in ("name", "id"))

    canvases = [element for element in root.iter() if _local_name(element.tag) == "canvas" and matches(element)]
    if canvases:
        return canvases
    definitions = [element for element in root.iter() if _local_name(element.tag) == "definition" and matches(element)]
    if definitions:
        return definitions
    schematics = [element for element in root.iter() if _local_name(element.tag) == "schematic" and matches(element)]
    if schematics:
        return schematics
    return [
        element
        for element in root.iter()
        if _local_name(element.tag) == "canvas" and not _text(element.attrib.get("name"))
    ]


def _component_elements(scope: ET.Element) -> list[ET.Element]:
    return [
        element
        for element in scope.iter()
        if _local_name(element.tag) == "component"
        or (
            _local_name(element.tag) == "user"
            and _text(element.attrib.get("classid")).casefold() == "usercmp"
        )
    ]


def _scope_name(scope: ET.Element, fallback: str) -> str:
    if _local_name(scope.tag) in {"definition", "canvas", "schematic"}:
        return _text(scope.attrib.get("name") or scope.attrib.get("id")) or fallback
    return fallback


def _reachable_scopes(root: ET.Element, initial: list[ET.Element], canvas_name: str) -> list[tuple[ET.Element, str]]:
    definitions = {
        _text(element.attrib.get("name")).casefold(): element
        for element in root.iter()
        if _local_name(element.tag) == "definition" and _text(element.attrib.get("name"))
    }
    queue = [(scope, _scope_name(scope, canvas_name)) for scope in initial]
    result: list[tuple[ET.Element, str]] = []
    visited_definitions = {
        source_name.casefold()
        for scope, source_name in queue
        if _local_name(scope.tag) == "definition"
    }
    while queue:
        scope, source_name = queue.pop(0)
        result.append((scope, source_name))
        for component in _component_elements(scope):
            reference = _text(component.attrib.get("definition") or component.attrib.get("defn") or component.attrib.get("type"))
            local_reference = reference.rsplit(":", 1)[-1].casefold()
            definition = definitions.get(local_reference)
            if definition is None or local_reference in visited_definitions:
                continue
            visited_definitions.add(local_reference)
            definition_name = _text(definition.attrib.get("name"))
            queue.append((definition, definition_name))
    return result


def scan_project(path: str | Path, canvas_name: str = "Main") -> HvdcProjectEvidence:
    project_path = Path(path).expanduser().resolve()
    warnings: list[str] = []
    project_name = project_path.stem
    try:
        root = ET.parse(project_path).getroot()
    except (OSError, ET.ParseError) as error:
        return HvdcProjectEvidence(
            str(project_path), project_name, None, warnings=(f"Unable to parse project XML: {error}",)
        )

    version = _text(root.attrib.get("version") or root.attrib.get("pscad_version")) or None
    definitions = tuple(
        sorted({
            _text(element.attrib.get("name"))
            for element in _children_named(root, "definition")
            if _text(element.attrib.get("name"))
        })
    )

    canvases = _canvas_scopes(root, canvas_name)
    if not canvases:
        warnings.append(f"Canvas '{canvas_name}' was not found.")
    scopes = _reachable_scopes(root, canvases, canvas_name)

    components: list[HvdcComponentRecord] = []
    labels: list[HvdcLabelRecord] = []
    for canvas, source_canvas_name in scopes:
        component_elements = _component_elements(canvas)
        component_label_elements: set[int] = set()
        for element in component_elements:
            component_id = _text(element.attrib.get("id") or element.attrib.get("ID")) or str(len(components) + 1)
            definition = _text(element.attrib.get("definition") or element.attrib.get("defn") or element.attrib.get("type"))
            parameters = _parameter_values(element)
            name = _text(element.attrib.get("name") or element.attrib.get("Name"))
            if not name:
                name = _parameter_value(parameters, "Name") or component_id
            local_labels: list[str] = []
            ports = [dict(child.attrib) for child in element.iter() if _local_name(child.tag) == "port"]
            for child in element.iter():
                child_name = _local_name(child.tag)
                if child_name in {"label", "annotation", "datalabel", "nodelabel", "text"}:
                    component_label_elements.add(id(child))
                    value = _label_value(child)
                    if value:
                        local_labels.append(value)
            source = HvdcSourceRef(str(project_path), source_canvas_name, component_id, definition)
            components.append(
                HvdcComponentRecord(
                    component_id,
                    name,
                    definition,
                    parameters,
                    tuple(dict.fromkeys(local_labels)),
                    tuple(ports),
                    source,
                )
            )
            labels.extend(
                HvdcLabelRecord(
                    value,
                    "component",
                    HvdcSourceRef(str(project_path), source_canvas_name, component_id, definition, label=value),
                )
                for value in dict.fromkeys(local_labels)
            )
            if "datalabel" in f"{name} {definition}".casefold():
                value = _parameter_value(parameters, "Name")
                if value:
                    labels.append(
                        HvdcLabelRecord(
                            value,
                            "datalabel",
                            HvdcSourceRef(str(project_path), source_canvas_name, component_id, definition, label=value),
                        )
                    )
        for element in canvas.iter():
            if id(element) in component_label_elements:
                continue
            if _local_name(element.tag) in {"label", "annotation", "datalabel", "nodelabel"}:
                value = _label_value(element)
                if value:
                    labels.append(HvdcLabelRecord(value, _local_name(element.tag), HvdcSourceRef(str(project_path), source_canvas_name, label=value)))
            elif _local_name(element.tag) == "text":
                value = _label_value(element)
                if value:
                    labels.append(HvdcLabelRecord(value, "text", HvdcSourceRef(str(project_path), source_canvas_name, label=value)))

    return HvdcProjectEvidence(
        project_path=str(project_path),
        project_name=project_name,
        pscad_version=version,
        definitions=definitions,
        components=tuple(components),
        labels=tuple(labels),
        warnings=tuple(warnings),
    )
