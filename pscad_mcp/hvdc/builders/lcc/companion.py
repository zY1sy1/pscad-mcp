"""Physical audit for the repository-authored fixed LCC companion."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from ....core.backend.base import BackendError

LIBRARY_SCOPE = "cigre_lcc_v1"
EXPECTED_DEFINITIONS = {
    "cigre_lcc_v1:LCC12PulseBridge",
    "cigre_lcc_v1:RectifierControl",
    "cigre_lcc_v1:InverterControl",
    "cigre_lcc_v1:Initialization",
    "cigre_lcc_v1:SignalInterface",
}
FORBIDDEN_STRUCTURAL_TAGS = {
    "six_pulse_group",
    "sixpulsegroup",
    "valve",
    "valves",
    "control_block",
    "interface_contract",
    "initialization_contract",
    "gate_interface",
    "dc_series_path",
}
EXPECTED_MASTER_COUNTS = {
    "cigre_lcc_v1:LCC12PulseBridge": {
        "master:g6p200": 2,
        "master:xnode": 8,
        "master:breakout": 2,
        "master:resistor": 6,
        "master:import": 3,
        "master:export": 4,
        "master:consti": 2,
        "master:sumjct": 1,
        "master:unity": 1,
    },
    "cigre_lcc_v1:RectifierControl": {
        "master:import": 4,
        "master:export": 3,
        "master:sumjct": 1,
        "master:mult": 1,
        "master:pi_ctlr": 1,
        "master:hardlimit": 1,
        "master:pgb": 2,
    },
    "cigre_lcc_v1:InverterControl": {
        "master:import": 6,
        "master:export": 3,
        "master:maxmin": 1,
        "master:sumjct": 1,
        "master:mult": 1,
        "master:pi_ctlr": 1,
        "master:hardlimit": 1,
        "master:pgb": 3,
    },
    "cigre_lcc_v1:Initialization": {
        "master:const": 2,
        "master:consti": 2,
        "master:export": 4,
        "master:unity": 2,
        "master:pgb": 2,
    },
    "cigre_lcc_v1:SignalInterface": {
        "master:import": 3,
        "master:export": 3,
        "master:pgb": 3,
    },
}

EXPECTED_OUTPUT_CHANNELS = {
    "cigre_lcc_v1:LCC12PulseBridge": (),
    "cigre_lcc_v1:RectifierControl": ("AO_RECT_Y", "AO_RECT_D"),
    "cigre_lcc_v1:InverterControl": (
        "AO_INV_Y",
        "AO_INV_D",
        "GAMMA_INV",
    ),
    "cigre_lcc_v1:Initialization": ("ENABLE_RECT", "ENABLE_INV"),
    "cigre_lcc_v1:SignalInterface": ("VDC_RECT", "VDC_INV", "IDC"),
}


def _port(kind: str, direction: str) -> dict[str, Any]:
    return {"kind": kind, "dimension": 1, "direction": direction}


EXPECTED_PORTS = {
    "cigre_lcc_v1:LCC12PulseBridge": {
        **{
            name: _port("electrical", "bidirectional")
            for name in (
                "ACY_A",
                "ACY_B",
                "ACY_C",
                "ACD_A",
                "ACD_B",
                "ACD_C",
                "DC_POS",
                "DC_NEG",
            )
        },
        **{
            name: _port("data", "input")
            for name in ("AO_Y", "AO_D", "ENABLE")
        },
        **{
            name: _port("data", "output")
            for name in ("AM_Y", "AM_D", "GM_Y", "GM_D")
        },
    },
    "cigre_lcc_v1:RectifierControl": {
        **{
            name: _port("data", "input")
            for name in ("VDC_MEAS", "IDC_MEAS", "IORDER", "ENABLE")
        },
        **{
            name: _port("data", "output")
            for name in ("AO_Y", "AO_D", "ALPHA")
        },
    },
    "cigre_lcc_v1:InverterControl": {
        **{
            name: _port("data", "input")
            for name in (
                "VDC_MEAS",
                "IDC_MEAS",
                "GM_Y",
                "GM_D",
                "GAMMA_ORDER",
                "ENABLE",
            )
        },
        **{
            name: _port("data", "output")
            for name in ("AO_Y", "AO_D", "GAMMA")
        },
    },
    "cigre_lcc_v1:Initialization": {
        name: _port("data", "output")
        for name in ("IORDER", "GAMMA_ORDER", "ENABLE_RECT", "ENABLE_INV")
    },
    "cigre_lcc_v1:SignalInterface": {
        name: _port("data", "output")
        for name in ("VDC_RECT", "VDC_INV", "IDC")
    },
}

REQUIRED_CONNECTIONS = {
    "cigre_lcc_v1:LCC12PulseBridge": {
        "ACY_TO_Y",
        "ACD_TO_D",
        "DC_SERIES",
        "AO_Y_TO_BRIDGE_Y",
        "AO_D_TO_BRIDGE_D",
        "ENABLE_TO_KB_Y",
        "ENABLE_TO_KB_D",
        "ENABLE_CONVERSION",
        "CB_ZERO_Y",
        "CB_ZERO_D",
    },
    "cigre_lcc_v1:RectifierControl": {
        "CURRENT_ERROR",
        "ENABLE_PRODUCT",
        "PI_TO_LIMIT",
        "AO_Y_OUTPUT",
        "AO_D_OUTPUT",
        "ALPHA_OUTPUT",
        "AO_Y_MONITOR",
        "AO_D_MONITOR",
    },
    "cigre_lcc_v1:InverterControl": {
        "GAMMA_MIN",
        "GAMMA_ERROR",
        "ENABLE_PRODUCT",
        "PI_TO_LIMIT",
        "AO_Y_OUTPUT",
        "AO_D_OUTPUT",
        "GAMMA_FANOUT",
        "AO_Y_MONITOR",
        "AO_D_MONITOR",
    },
    "cigre_lcc_v1:Initialization": {
        "IORDER_OUTPUT",
        "GAMMA_ORDER_OUTPUT",
        "ENABLE_RECT_OUTPUT",
        "ENABLE_INV_OUTPUT",
        "ENABLE_RECT_CONVERSION",
        "ENABLE_INV_CONVERSION",
        "ENABLE_RECT_MONITOR",
        "ENABLE_INV_MONITOR",
    },
    "cigre_lcc_v1:SignalInterface": {
        "VDC_RECT_IMPORT",
        "VDC_INV_IMPORT",
        "IDC_IMPORT",
        "VDC_RECT_MONITOR",
        "VDC_INV_MONITOR",
        "IDC_MONITOR",
    },
}

_ABSOLUTE_PATH = re.compile(
    r"(?:^[A-Za-z]:[\\/]|^\\\\|^/(?:[^/\s]+/)*[^/\s]+)"
)
_SCOPED_NAME = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*):(.+)$")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _attribute(element: ET.Element, name: str) -> str | None:
    wanted = name.casefold()
    for key, value in element.attrib.items():
        if key.casefold() == wanted:
            return value
    return None


def _scoped_name(name: str) -> str:
    normalized = name.strip()
    if ":" in normalized:
        return normalized
    return f"{LIBRARY_SCOPE}:{normalized}"


def _raise_invalid(
    path: Path,
    errors: list[dict[str, Any]],
    *,
    cause: BaseException | None = None,
) -> None:
    error = BackendError(
        "LCC_COMPANION_INVALID",
        "The LCC companion is not a physical PSCAD library.",
        "hvdc",
        "audit_lcc_companion_library",
        {
            "path": str(path),
            "errors": sorted(
                errors,
                key=lambda item: (
                    str(item.get("definition", "")),
                    str(item.get("reason", "")),
                ),
            ),
        },
    )
    if cause is None:
        raise error
    raise error from cause


def _definition_records(
    root: ET.Element,
    errors: list[dict[str, Any]],
) -> dict[str, ET.Element]:
    records: dict[str, ET.Element] = {}
    definitions = next(
        (child for child in root if _local(child.tag) == "definitions"),
        None,
    )
    if definitions is None:
        return records
    for element in definitions:
        if _local(element.tag) != "definition":
            continue
        classid = (_attribute(element, "classid") or "").casefold()
        if classid == "stationdefn":
            continue
        raw_name = (_attribute(element, "name") or "").strip()
        if not raw_name:
            errors.append({"definition": "", "reason": "definition_name_missing"})
            continue
        if raw_name.casefold().startswith("master:"):
            errors.append(
                {
                    "definition": raw_name,
                    "reason": "vendor_definition_body",
                }
            )
            continue
        if raw_name == "Main":
            continue
        name = _scoped_name(raw_name)
        if name in records:
            errors.append({"definition": name, "reason": "duplicate_definition"})
            continue
        records[name] = element
    return records


def _direct_child(element: ET.Element, tag: str) -> ET.Element | None:
    wanted = tag.casefold()
    return next(
        (child for child in element if _local(child.tag) == wanted),
        None,
    )


def _port_contract(element: ET.Element) -> dict[str, Any]:
    model = (_attribute(element, "model") or "").casefold()
    kind = (_attribute(element, "kind") or "").casefold()
    if model == "natural" or kind == "electrical":
        normalized_kind = "electrical"
        direction = "bidirectional"
    elif model == "transfer" or kind in {"data", "signal"}:
        normalized_kind = "data"
        direction = (_attribute(element, "mode") or "").casefold()
    else:
        normalized_kind = kind or model or "unknown"
        direction = (_attribute(element, "mode") or "").casefold()
    raw_dimension = _attribute(element, "dimension") or _attribute(element, "dim")
    try:
        dimension = int(raw_dimension or "1")
    except ValueError:
        dimension = -1
    if dimension == 0:
        dimension = 1
    return {
        "kind": normalized_kind,
        "dimension": dimension,
        "direction": direction,
    }


def _external_ports(
    definition_name: str,
    definition: ET.Element,
    errors: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    svg = _direct_child(definition, "svg")
    if svg is None:
        return {}
    ports: dict[str, dict[str, Any]] = {}
    for element in svg:
        if _local(element.tag) != "port":
            continue
        name = (_attribute(element, "name") or "").strip()
        if not name:
            errors.append(
                {"definition": definition_name, "reason": "port_name_missing"}
            )
            continue
        if name in ports:
            errors.append(
                {
                    "definition": definition_name,
                    "reason": "duplicate_port",
                    "observed": name,
                }
            )
            continue
        ports[name] = _port_contract(element)
    return ports


def _schematic_evidence(
    definition_name: str,
    definition: ET.Element,
    errors: list[dict[str, Any]],
) -> tuple[Counter[str], tuple[str, ...], tuple[str, ...]]:
    schematic = _direct_child(definition, "schematic")
    if schematic is None:
        return Counter(), (), ()
    identifiers: set[str] = set()
    instances: Counter[str] = Counter()
    connections: list[str] = []
    output_channels: list[str] = []
    for element in schematic:
        tag = _local(element.tag)
        identifier = (_attribute(element, "id") or "").strip()
        if identifier:
            if identifier in identifiers:
                errors.append(
                    {
                        "definition": definition_name,
                        "reason": "duplicate_internal_id",
                        "observed": identifier,
                    }
                )
            identifiers.add(identifier)
        if tag == "user":
            scoped = (
                _attribute(element, "defn")
                or _attribute(element, "definition")
                or ""
            ).strip()
            if scoped:
                instances[scoped] += 1
                if scoped == "master:pgb":
                    paramlist = _direct_child(element, "paramlist")
                    name = ""
                    if paramlist is not None:
                        name = next(
                            (
                                (_attribute(param, "value") or "").strip()
                                for param in paramlist
                                if _local(param.tag) == "param"
                                and (_attribute(param, "name") or "").casefold()
                                == "name"
                            ),
                            "",
                        )
                    if not name:
                        errors.append(
                            {
                                "definition": definition_name,
                                "reason": "output_channel_name_missing",
                            }
                        )
                    else:
                        output_channels.append(name)
        elif tag == "wire":
            name = (
                _attribute(element, "lcc_role")
                or _attribute(element, "name")
                or ""
            ).strip()
            if name:
                connections.append(name)
    return (
        instances,
        tuple(sorted(connections)),
        tuple(output_channels),
    )


def _scan_forbidden_content(
    root: ET.Element,
    errors: list[dict[str, Any]],
) -> None:
    seen: set[tuple[str, str]] = set()
    for element in root.iter():
        tag = _local(element.tag)
        if tag in FORBIDDEN_STRUCTURAL_TAGS:
            key = ("structural_only", tag)
            if key not in seen:
                errors.append(
                    {
                        "definition": "",
                        "reason": "structural_only",
                        "observed": tag,
                    }
                )
                seen.add(key)
        values = [*element.attrib.values()]
        if element.text and element.text.strip():
            values.append(element.text.strip())
        for value in values:
            stripped = value.strip()
            if (
                _ABSOLUTE_PATH.search(stripped)
                or PureWindowsPath(stripped).is_absolute()
                or PurePosixPath(stripped).is_absolute()
            ):
                key = ("absolute_path", stripped)
                if key not in seen:
                    errors.append(
                        {
                            "definition": "",
                            "reason": "absolute_path",
                            "observed": stripped,
                        }
                    )
                    seen.add(key)
            match = _SCOPED_NAME.fullmatch(stripped)
            if match and match.group(1) not in {"master", LIBRARY_SCOPE}:
                key = ("foreign_scope", stripped)
                if key not in seen:
                    errors.append(
                        {
                            "definition": "",
                            "reason": "foreign_scope",
                            "observed": stripped,
                        }
                    )
                    seen.add(key)


def audit_companion_library(path: str | Path) -> dict[str, Any]:
    library_path = Path(path).expanduser().resolve()
    try:
        payload = library_path.read_bytes()
        root = ET.fromstring(payload)
    except (OSError, ET.ParseError) as error:
        _raise_invalid(
            library_path,
            [
                {
                    "definition": "",
                    "reason": "parse_failure",
                    "observed": str(error),
                }
            ],
            cause=error,
        )

    errors: list[dict[str, Any]] = []
    _scan_forbidden_content(root, errors)
    target = _attribute(root, "Target")
    if (
        _local(root.tag) != "project"
        or target != "Library"
        or _attribute(root, "name") != LIBRARY_SCOPE
        or _attribute(root, "version") != "4.6.2"
    ):
        errors.append(
            {
                "definition": "",
                "reason": "library_identity",
                "observed": {
                    "tag": _local(root.tag),
                    "name": _attribute(root, "name"),
                    "version": _attribute(root, "version"),
                    "target": target,
                },
            }
        )
    definitions = _definition_records(root, errors)
    if set(definitions) != EXPECTED_DEFINITIONS:
        errors.append(
            {
                "definition": "",
                "reason": "definition_set_mismatch",
                "expected": sorted(EXPECTED_DEFINITIONS),
                "observed": sorted(definitions),
            }
        )

    evidence: dict[str, Any] = {}
    for definition_name in sorted(EXPECTED_DEFINITIONS & set(definitions)):
        definition = definitions[definition_name]
        missing_shape = [
            name
            for name in ("form", "svg", "schematic")
            if _direct_child(definition, name) is None
        ]
        if missing_shape:
            errors.append(
                {
                    "definition": definition_name,
                    "reason": "definition_shape_missing",
                    "observed": missing_shape,
                }
            )
        ports = _external_ports(definition_name, definition, errors)
        expected_ports = EXPECTED_PORTS[definition_name]
        if ports != expected_ports:
            errors.append(
                {
                    "definition": definition_name,
                    "reason": "external_port_mismatch",
                    "expected": expected_ports,
                    "observed": ports,
                }
            )
        instances, connections, output_channels = _schematic_evidence(
            definition_name, definition, errors
        )
        expected_instances = Counter(EXPECTED_MASTER_COUNTS[definition_name])
        if instances != expected_instances:
            errors.append(
                {
                    "definition": definition_name,
                    "reason": "master_instance_count",
                    "expected": dict(expected_instances),
                    "observed": dict(instances),
                }
            )
        missing_connections = sorted(
            REQUIRED_CONNECTIONS[definition_name] - set(connections)
        )
        if missing_connections:
            errors.append(
                {
                    "definition": definition_name,
                    "reason": "internal_connection_missing",
                    "observed": missing_connections,
                }
            )
        expected_outputs = EXPECTED_OUTPUT_CHANNELS[definition_name]
        if output_channels != expected_outputs:
            errors.append(
                {
                    "definition": definition_name,
                    "reason": "output_channel_mismatch",
                    "expected": list(expected_outputs),
                    "observed": list(output_channels),
                }
            )
        evidence[definition_name] = {
            "ports": ports,
            "master_instances": dict(instances),
            "connections": list(connections),
            "output_channels": list(output_channels),
        }

    if errors:
        _raise_invalid(library_path, errors)
    return {
        "valid": True,
        "library": str(library_path),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "scope": LIBRARY_SCOPE,
        "definitions": evidence,
        "effective_valves": 12,
    }


__all__ = ["audit_companion_library"]
