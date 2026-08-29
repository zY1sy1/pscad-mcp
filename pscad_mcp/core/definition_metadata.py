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
    model: str | None = None
    kind: str | None = None
    page: bool = False


@dataclass(frozen=True)
class DefinitionMetadata:
    ports: tuple[PortMetadata, ...]
    parameter_ranges: dict[str, object]


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


def read_definition_metadata(
    file_path: str | Path,
    definition_name: str,
) -> DefinitionMetadata:
    """Return static definition metadata without modifying the PSCAD file."""
    root = ET.parse(Path(file_path)).getroot()
    definition = root.find(f".//Definition[@name='{definition_name}']")
    if definition is None:
        raise KeyError(f"Definition '{definition_name}' was not found in {file_path}.")

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
                model=port.get("model"),
                kind=port.get("kind"),
                page=(port.get("page") or "").strip().casefold()
                in {"1", "true", "yes", "on"},
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
