"""Read PSCAD component ports and legal ranges from project/library XML."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PortMetadata:
    name: str
    x: int
    y: int
    dim: int | None
    type: str | None
    model: str | None = None
    kind: str | None = None
    page: bool = False
    mode: str | None = None
    condition: str | None = None
    occurrence: int = 0


@dataclass(frozen=True)
class ParameterMetadata:
    name: str
    type: str | None
    unit: str | None
    minimum: int | float | None
    maximum: int | float | None
    choices: tuple[str, ...]
    default: object
    intent: str | None
    readonly: bool


@dataclass(frozen=True)
class DefinitionMetadata:
    ports: tuple[PortMetadata, ...]
    parameter_ranges: dict[str, object]
    parameters: dict[str, ParameterMetadata] = field(default_factory=dict)
    name: str = ""
    description: str | None = None


@dataclass(frozen=True)
class MasterDefinitionBinding:
    """Maps a repository logical Master component to PSCAD 4.6.2."""

    logical_name: str
    definition: str
    port_map: dict[str, str]
    parameter_map: dict[str, str]
    instances: int = 1


_MASTER_BINDINGS: dict[str, MasterDefinitionBinding] = {
    "master:three_phase_source": MasterDefinitionBinding(
        "master:three_phase_source",
        "source3",
        {"A": "A", "B": "B", "C": "C"},
        {"Amplitude_kV": "Vm", "Frequency_Hz": "F", "Phase_deg": "Ph"},
    ),
    "master:converter_transformer": MasterDefinitionBinding(
        "master:converter_transformer",
        "umec-xfmr-6w5L",
        {
            "HV_A": "A1",
            "HV_B": "B1",
            "HV_C": "C1",
            "LV_A": "A2",
            "LV_B": "B2",
            "LV_C": "C2",
        },
        {"Ratio": "V2", "PhaseShift_deg": "Lead"},
    ),
    "master:ac_filter_branch": MasterDefinitionBinding(
        "master:ac_filter_branch",
        "cfilter",
        {"IN": "A", "OUT": "B"},
        {"Branch_MVAR": "Q", "Tuning_Hz": "f0"},
        instances=3,
    ),
    "master:smoothing_reactor": MasterDefinitionBinding(
        "master:smoothing_reactor",
        "inductor",
        {"IN": "A", "OUT": "B"},
        {"Inductance_mH": "L"},
    ),
    "master:dc_line_section": MasterDefinitionBinding(
        "master:dc_line_section",
        "dc_mac_2w",
        {"IN": "F1", "OUT": "F2"},
        {"Length_km": "D"},
    ),
    "master:ac_meter": MasterDefinitionBinding(
        "master:ac_meter",
        "multimeter",
        {"A": "A", "B": "B"},
        {},
    ),
    "master:dc_meter": MasterDefinitionBinding(
        "master:dc_meter",
        "voltmeter",
        {"IN": "N1", "OUT": "N2"},
        {},
    ),
    "master:ground": MasterDefinitionBinding(
        "master:ground",
        "ground",
        {"GND": "A"},
        {},
    ),
}


def master_definition_binding(logical_name: str) -> MasterDefinitionBinding:
    """Return the audited PSCAD 4.6.2 binding for a logical Master name."""

    try:
        return _MASTER_BINDINGS[logical_name]
    except KeyError as error:
        raise KeyError(
            f"No PSCAD 4.6.2 Master binding for '{logical_name}'."
        ) from error


def _number(value: str) -> int | float:
    numeric = float(value)
    return int(numeric) if numeric.is_integer() else numeric


def _default_value(parameter: ET.Element) -> object:
    value = parameter.find("value")
    raw = (value.text or "").strip() if value is not None else ""
    if not raw:
        return None
    parameter_type = (parameter.get("type") or "").casefold()
    if parameter_type in {"real", "integer", "choice"}:
        try:
            return _number(raw)
        except ValueError:
            return raw
    return raw


def _metadata_from_definition(definition: ET.Element) -> DefinitionMetadata:
    ports = []
    occurrences: dict[str, int] = {}
    for port in definition.findall(".//svg/port"):
        raw_dim = port.get("dim")
        name = str(port.get("name", ""))
        occurrence = occurrences.get(name, 0)
        occurrences[name] = occurrence + 1
        condition = (port.text or "").strip() or None
        ports.append(
            PortMetadata(
                name=name,
                x=int(port.get("x", "0")),
                y=int(port.get("y", "0")),
                dim=int(raw_dim) if raw_dim not in {None, ""} else None,
                type=port.get("type") or port.get("model"),
                model=port.get("model"),
                kind=port.get("kind"),
                page=(port.get("page") or "").strip().casefold()
                in {"1", "true", "yes", "on"},
                mode=port.get("mode"),
                condition=condition,
                occurrence=occurrence,
            )
        )

    ranges: dict[str, object] = {}
    parameters: dict[str, ParameterMetadata] = {}
    for parameter in definition.findall(".//form//parameter"):
        name = parameter.get("name")
        if not name:
            continue
        choices = tuple(
            (choice.text or "").strip().split("=", 1)[0].strip()
            for choice in parameter.findall("choice")
        )
        minimum_raw = parameter.get("min", "").strip()
        maximum_raw = parameter.get("max", "").strip()
        minimum = _number(minimum_raw) if minimum_raw else None
        maximum = _number(maximum_raw) if maximum_raw else None
        if choices:
            ranges[name] = list(choices)
        elif minimum_raw or maximum_raw:
            ranges[name] = (minimum, maximum)
        parameters[name] = ParameterMetadata(
            name=name,
            type=parameter.get("type"),
            unit=parameter.get("unit"),
            minimum=minimum,
            maximum=maximum,
            choices=choices,
            default=_default_value(parameter),
            intent=parameter.get("intent"),
            readonly=(parameter.get("readonly") or "").strip().casefold()
            in {"1", "true", "yes", "on"},
        )

    description_node = definition.find("./paramlist/param[@name='Description']")
    description = (
        description_node.get("value")
        if description_node is not None
        else None
    )
    return DefinitionMetadata(
        tuple(ports),
        ranges,
        parameters,
        str(definition.get("name", "")),
        description,
    )


def read_definition_metadata_matches(
    file_path: str | Path,
    definition_name: str,
) -> tuple[DefinitionMetadata, ...]:
    """Return every exact definition match in source order."""

    root = ET.parse(Path(file_path)).getroot()
    return tuple(
        _metadata_from_definition(definition)
        for definition in root.findall(".//Definition")
        if definition.get("name") == definition_name
    )


def read_definition_metadata(
    file_path: str | Path,
    definition_name: str,
) -> DefinitionMetadata:
    """Return static definition metadata without modifying the PSCAD file."""
    matches = read_definition_metadata_matches(file_path, definition_name)
    if not matches:
        raise KeyError(f"Definition '{definition_name}' was not found in {file_path}.")
    if len(matches) != 1:
        raise KeyError(
            f"Definition '{definition_name}' is ambiguous in {file_path}: "
            f"found {len(matches)} matches."
        )
    return matches[0]
