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

    canvases = [
        element for element in root.iter()
        if _local_name(element.tag) in {"canvas", "schematic", "definition"}
        and (element.attrib.get("name") == canvas_name or element.attrib.get("id") == canvas_name)
    ]
    if not canvases:
        canvases = [element for element in root.iter() if _local_name(element.tag) == "canvas" and not element.attrib.get("name")]
    if not canvases:
        warnings.append(f"Canvas '{canvas_name}' was not found.")

    components: list[HvdcComponentRecord] = []
    labels: list[HvdcLabelRecord] = []
    for canvas in canvases:
        for element in canvas.iter():
            if _local_name(element.tag) != "component":
                continue
            component_id = _text(element.attrib.get("id") or element.attrib.get("ID")) or str(len(components) + 1)
            name = _text(element.attrib.get("name") or element.attrib.get("Name")) or component_id
            definition = _text(element.attrib.get("definition") or element.attrib.get("defn") or element.attrib.get("type"))
            parameters: dict[str, str] = {}
            local_labels: list[str] = []
            ports: list[dict[str, str]] = []
            for child in element.iter():
                child_name = _local_name(child.tag)
                if child_name in {"parameter", "param"}:
                    parameter_name = _text(child.attrib.get("name"))
                    if parameter_name:
                        parameters[parameter_name] = child.attrib.get("value", _text(child.text))
                elif child_name in {"label", "annotation"} and _text(child.text):
                    local_labels.append(_text(child.text))
                elif child_name == "port":
                    ports.append(dict(child.attrib))
            source = HvdcSourceRef(str(project_path), canvas_name, component_id, definition)
            components.append(HvdcComponentRecord(component_id, name, definition, parameters, tuple(local_labels), tuple(ports), source))
            labels.extend(HvdcLabelRecord(value, "component", HvdcSourceRef(str(project_path), canvas_name, component_id, definition, label=value)) for value in local_labels)
        for element in canvas.iter():
            if _local_name(element.tag) in {"label", "annotation", "datalabel", "nodelabel"}:
                value = _text(element.text or element.attrib.get("name") or element.attrib.get("label"))
                if value:
                    labels.append(HvdcLabelRecord(value, _local_name(element.tag), HvdcSourceRef(str(project_path), canvas_name, label=value)))

    return HvdcProjectEvidence(
        project_path=str(project_path),
        project_name=project_name,
        pscad_version=version,
        definitions=definitions,
        components=tuple(components),
        labels=tuple(labels),
        warnings=tuple(warnings),
    )
