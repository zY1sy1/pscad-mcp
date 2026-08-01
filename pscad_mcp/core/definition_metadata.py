"""Read PSCAD component ports and legal ranges from project/library XML."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class PortMetadata:
    name: str
    x: int
    y: int
    dim: int | None
    type: str | None


@dataclass(frozen=True)
class DefinitionMetadata:
    ports: tuple[PortMetadata, ...]
    parameter_ranges: dict[str, object]


def _number(value: str) -> int | float:
    numeric = float(value)
    return int(numeric) if numeric.is_integer() else numeric


def read_definition_metadata(
    file_path: str | Path,
    definition_name: str,
) -> DefinitionMetadata:
    """Return static definition metadata without modifying the PSCAD file."""
    root = ET.parse(Path(file_path)).getroot()
    definition = root.find(f".//Definition[@name='{definition_name}']")
    if definition is None:
        raise KeyError(
            f"Definition '{definition_name}' was not found in {file_path}."
        )

    ports = []
    for port in definition.findall(".//svg/port"):
        raw_dim = port.get("dim")
        ports.append(
            PortMetadata(
                name=str(port.get("name", "")),
                x=int(port.get("x", "0")),
                y=int(port.get("y", "0")),
                dim=int(raw_dim) if raw_dim not in {None, ""} else None,
                type=port.get("type") or port.get("model"),
            )
        )

    ranges: dict[str, object] = {}
    for parameter in definition.findall(".//form//parameter"):
        name = parameter.get("name")
        if not name:
            continue
        choices = []
        for choice in parameter.findall("choice"):
            text = (choice.text or "").strip()
            choices.append(text.split("=", 1)[0].strip())
        if choices:
            ranges[name] = choices
            continue
        minimum = parameter.get("min", "").strip()
        maximum = parameter.get("max", "").strip()
        if minimum or maximum:
            ranges[name] = (
                _number(minimum) if minimum else None,
                _number(maximum) if maximum else None,
            )

    return DefinitionMetadata(tuple(ports), ranges)
