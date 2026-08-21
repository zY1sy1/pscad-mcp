"""Read-only audit of user-provided LCC PSCX templates."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from ....core.backend.base import BackendError


@dataclass(frozen=True)
class TemplateAuditReport:
    compatible: bool
    roles: dict[str, Any]
    missing_contracts: tuple[str, ...]
    conflicts: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {"compatible": self.compatible, "roles": self.roles, "missing_contracts": list(self.missing_contracts), "conflicts": list(self.conflicts), "fingerprint": self.fingerprint}


def audit_lcc_template(path: str | Path, catalog: dict[str, Any] | None = None) -> TemplateAuditReport:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise BackendError("LCC_TEMPLATE_INCOMPATIBLE", "Template file does not exist.", "hvdc", "audit_lcc_template", {"path": str(source)})
    payload = source.read_bytes()
    fingerprint = hashlib.sha256(payload).hexdigest()
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise BackendError("LCC_TEMPLATE_INCOMPATIBLE", "Template is not valid PSCX XML.", "hvdc", "audit_lcc_template", {}) from error
    scope = _main_scope(root)
    components = _component_records(scope)
    roles: dict[str, Any] = {}
    conflicts: list[str] = []
    missing: list[str] = []
    rectifier = _unique_definition(components, "RectPole") or _unique_definition(components, "LCC12PulseBridge")
    inverter = _unique_definition(components, "InverterPole") or _unique_definition(components, "LCC12PulseBridge")
    if rectifier is None:
        missing.append("rectifier_valve_group")
    else:
        roles["rectifier_valve_group"] = {
            "definition": rectifier,
            "confidence": 1.0,
            "source": str(source),
        }
    if inverter is None:
        missing.append("inverter_valve_group")
    else:
        roles["inverter_valve_group"] = {
            "definition": inverter,
            "confidence": 1.0,
            "source": str(source),
        }
    earth_result = _select_earth_electrode(components, str(source))
    if earth_result is None:
        missing.append("earth_electrode")
    else:
        roles["earth_electrode"] = earth_result
    if conflicts:
        raise BackendError("LCC_TEMPLATE_AMBIGUOUS", "Template contains ambiguous role candidates.", "hvdc", "audit_lcc_template", {"roles": conflicts})
    compatible = not missing
    return TemplateAuditReport(compatible, roles, tuple(sorted(set(missing))), tuple(sorted(conflicts)), fingerprint)


def _name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _attr(element: ET.Element, *names: str) -> str | None:
    wanted = {name.casefold() for name in names}
    for key, value in element.attrib.items():
        if key.casefold() in wanted:
            return value
    return None


def _text(value: str | None) -> str:
    return (value or "").strip()


def _integer(value: str | None, default: int | None = None) -> int:
    if value is None or not value.strip():
        if default is not None:
            return default
        raise BackendError("LCC_TEMPLATE_INCOMPATIBLE", "Component coordinates are missing.", "hvdc", "audit_lcc_template", {})
    return int(value.strip())


def _point(element: ET.Element) -> tuple[int, int]:
    x = _attr(element, "x", "left")
    y = _attr(element, "y", "top")
    if x is None or y is None:
        raw = _attr(element, "location", "position")
        if raw:
            parts = raw.replace("(", "").replace(")", "").split(",")
            if len(parts) == 2:
                x, y = parts
    return _integer(x, 0), _integer(y, 0)


def _parameters(element: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for child in element.iter():
        if _name(child.tag) not in {"param", "parameter"}:
            continue
        name = _text(_attr(child, "name", "key"))
        if not name:
            continue
        value = _attr(child, "value")
        result[name] = _text(value if value is not None else child.text)
    return result


def _main_scope(root: ET.Element) -> ET.Element:
    scopes = [
        element
        for element in root.iter()
        if _name(element.tag) in {"definition", "canvas", "schematic"}
        and _text(_attr(element, "name", "id")).casefold() == "main"
    ]
    return scopes[0] if scopes else root


def _component_elements(scope: ET.Element) -> list[ET.Element]:
    return [
        element
        for element in scope.iter()
        if _name(element.tag) == "user" or _name(element.tag) == "component"
    ]


def _component_records(scope: ET.Element) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for element in _component_elements(scope):
        definition = _text(_attr(element, "definition", "defn", "type"))
        if not definition:
            continue
        records.append(
            {
                "definition": definition,
                "local_name": definition.rsplit(":", 1)[-1],
                "location": _point(element),
                "parameters": _parameters(element),
            }
        )
    return records


def _unique_definition(components: list[dict[str, Any]], local_name: str) -> str | None:
    matches = sorted({component["definition"] for component in components if component["local_name"] == local_name})
    if len(matches) == 1:
        return matches[0]
    return None


def _select_earth_electrode(components: list[dict[str, Any]], source: str) -> dict[str, Any] | None:
    grounds = [component for component in components if component["local_name"] == "ground" and component["definition"] == "master:ground"]
    anchors = [
        component
        for component in components
        if component["local_name"] == "ammeter" and component["parameters"].get("Name") == "Ielectrode"
    ]
    if not grounds:
        return None
    selected = grounds[0]
    evidence: dict[str, Any] = {
        "selected": {
            "definition": selected["definition"],
            "location": list(selected["location"]),
        }
    }
    if anchors:
        anchor = anchors[0]
        selected = min(grounds, key=lambda component: _distance_sq(anchor["location"], component["location"]))
        evidence["anchor"] = {
            "definition": anchor["definition"],
            "location": list(anchor["location"]),
            "parameters": dict(anchor["parameters"]),
        }
        evidence["selected"] = {
            "definition": selected["definition"],
            "location": list(selected["location"]),
        }
        evidence["distance"] = _distance(anchor["location"], selected["location"])
    return {
        "definition": selected["definition"],
        "confidence": 1.0,
        "source": source,
        "evidence": evidence,
    }


def _distance_sq(left: tuple[int, int], right: tuple[int, int]) -> int:
    return (left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2


def _distance(left: tuple[int, int], right: tuple[int, int]) -> float:
    return _distance_sq(left, right) ** 0.5
