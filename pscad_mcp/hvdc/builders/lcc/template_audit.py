"""Read-only audit of user-provided LCC PSCX templates."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn
import xml.etree.ElementTree as ET

from ....core.backend.base import BackendError


TEMPLATE_MAX_BYTES = 32 * 1024 * 1024
_FORBIDDEN_XML_DECLARATION = re.compile(
    rb"<!\s*(?:DOCTYPE|ENTITY)\b",
    flags=re.IGNORECASE,
)


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
    try:
        source = Path(path).expanduser().resolve()
    except OSError as error:
        _raise_unreadable_template(error)
    try:
        with source.open("rb") as stream:
            actual_bytes = os.fstat(stream.fileno()).st_size
            if actual_bytes > TEMPLATE_MAX_BYTES:
                raise BackendError(
                    "LCC_TEMPLATE_INCOMPATIBLE",
                    "Template exceeds the audit size limit.",
                    "hvdc",
                    "audit_lcc_template",
                    {
                        "actual_bytes": actual_bytes,
                        "max_bytes": TEMPLATE_MAX_BYTES,
                        "reason": "template_too_large",
                    },
                )
            payload = stream.read(TEMPLATE_MAX_BYTES + 1)
    except BackendError:
        raise
    except OSError as error:
        _raise_unreadable_template(error)
    if len(payload) > TEMPLATE_MAX_BYTES:
        raise BackendError(
            "LCC_TEMPLATE_INCOMPATIBLE",
            "Template exceeds the audit size limit.",
            "hvdc",
            "audit_lcc_template",
            {
                "actual_bytes": len(payload),
                "max_bytes": TEMPLATE_MAX_BYTES,
                "reason": "template_too_large",
            },
        )
    fingerprint = hashlib.sha256(payload).hexdigest()
    if _FORBIDDEN_XML_DECLARATION.search(payload.replace(b"\x00", b"")):
        raise BackendError(
            "LCC_TEMPLATE_INCOMPATIBLE",
            "Template contains a forbidden XML declaration.",
            "hvdc",
            "audit_lcc_template",
            {"reason": "forbidden_xml_declaration"},
        )
    try:
        root = ET.fromstring(payload)
    except (ET.ParseError, LookupError, ValueError) as error:
        raise BackendError(
            "LCC_TEMPLATE_INCOMPATIBLE",
            "Template is not valid PSCX XML.",
            "hvdc",
            "audit_lcc_template",
            {"error_type": type(error).__name__, "reason": "invalid_xml"},
        ) from error
    scope = _main_scope(root)
    components = _component_records(scope)
    roles: dict[str, Any] = {}
    conflicts: list[str] = []
    conflict_reasons: dict[str, str] = {}
    missing: list[str] = []
    legacy_bridges = _exact_components(components, "LCC12PulseBridge")
    rectifiers = _exact_components(components, "RectPole")
    inverters = _exact_components(components, "InverterPole")
    if len(rectifiers) > 1 or len(legacy_bridges) > 1:
        conflicts.append("rectifier_valve_group")
        conflict_reasons["rectifier_valve_group"] = "multiple_exact_component_instances"
    if len(inverters) > 1 or len(legacy_bridges) > 1:
        conflicts.append("inverter_valve_group")
        conflict_reasons["inverter_valve_group"] = "multiple_exact_component_instances"
    rectifier = _single_definition(rectifiers) or _single_definition(legacy_bridges)
    inverter = _single_definition(inverters) or _single_definition(legacy_bridges)
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
    earth_result, earth_conflict = _select_earth_electrode(components, str(source))
    if earth_conflict is not None:
        conflicts.append("earth_electrode")
        conflict_reasons["earth_electrode"] = earth_conflict
    if earth_result is None:
        if earth_conflict is None:
            missing.append("earth_electrode")
    else:
        roles["earth_electrode"] = earth_result
    if conflicts:
        raise BackendError(
            "LCC_TEMPLATE_AMBIGUOUS",
            "Template contains ambiguous role candidates.",
            "hvdc",
            "audit_lcc_template",
            {
                "compatible": False,
                "conflicts": sorted(set(conflicts)),
                "roles": sorted(set(conflicts)),
                "conflict_reasons": conflict_reasons,
            },
        )
    compatible = not missing
    return TemplateAuditReport(compatible, roles, tuple(sorted(set(missing))), tuple(sorted(conflicts)), fingerprint)


def _raise_unreadable_template(error: OSError) -> NoReturn:
    raise BackendError(
        "LCC_TEMPLATE_INCOMPATIBLE",
        "Template could not be read.",
        "hvdc",
        "audit_lcc_template",
        {
            "error_type": type(error).__name__,
            "reason": "template_unreadable",
        },
    ) from error


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


def _integer(value: str, *, field: str) -> int:
    normalized = value.strip()
    try:
        return int(normalized)
    except ValueError as error:
        _raise_invalid_coordinate(field, normalized, error)


def _raise_invalid_coordinate(field: str, value: str, cause: Exception | None = None) -> NoReturn:
    error = BackendError(
        "LCC_TEMPLATE_INCOMPATIBLE",
        "Component coordinate is invalid.",
        "hvdc",
        "audit_lcc_template",
        {
            "field": field,
            "reason": "invalid_component_coordinate",
            "value_length": len(value),
            "value_preview": value[:64],
        },
    )
    if cause is None:
        raise error
    raise error from cause


def _point(element: ET.Element, *, role: str) -> tuple[int, int]:
    x = _attr(element, "x", "left")
    y = _attr(element, "y", "top")
    if x is None or y is None:
        raw = _attr(element, "location", "position")
        if raw:
            parts = raw.replace("(", "").replace(")", "").split(",")
            if len(parts) == 2:
                x, y = parts
            else:
                _raise_invalid_coordinate("location", raw.strip())
    if x is None or y is None or not x.strip() or not y.strip():
        raise BackendError(
            "LCC_TEMPLATE_INCOMPATIBLE",
            "A role component coordinate is missing.",
            "hvdc",
            "audit_lcc_template",
            {"reason": "missing_component_coordinate", "role": role},
        )
    return _integer(x, field="x"), _integer(y, field="y")


def _parameters(element: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    direct_children = list(element)
    parameters = [child for child in direct_children if _name(child.tag) == "param"]
    for child in direct_children:
        if _name(child.tag) == "paramlist":
            parameters.extend(
                parameter for parameter in list(child) if _name(parameter.tag) == "param"
            )
    for parameter in parameters:
        name = _text(_attr(parameter, "name", "key"))
        if name:
            if name == "Name" and name in result:
                raise BackendError(
                    "LCC_TEMPLATE_INCOMPATIBLE",
                    "Component contains duplicate Name parameters.",
                    "hvdc",
                    "audit_lcc_template",
                    {
                        "parameter": "Name",
                        "reason": "duplicate_component_parameter",
                    },
                )
            value = _attr(parameter, "value")
            result[name] = _text(value if value is not None else parameter.text)
    return result


def _main_scope(root: ET.Element) -> ET.Element:
    definitions = _top_level_definitions(root)
    main_definitions = [
        definition
        for definition in definitions
        if _text(_attr(definition, "name", "id")).casefold() == "main"
    ]
    if len(main_definitions) > 1:
        raise BackendError(
            "LCC_TEMPLATE_AMBIGUOUS",
            "Template contains multiple Main definitions.",
            "hvdc",
            "audit_lcc_template",
            {
                "compatible": False,
                "conflict_reasons": {"main_scope": "multiple_main_definitions"},
                "conflicts": ["main_scope"],
                "roles": ["main_scope"],
            },
        )
    if main_definitions:
        return main_definitions[0]
    if len(definitions) > 1:
        raise BackendError(
            "LCC_TEMPLATE_AMBIGUOUS",
            "Template has multiple definitions and no Main definition.",
            "hvdc",
            "audit_lcc_template",
            {
                "compatible": False,
                "conflict_reasons": {
                    "main_scope": "multiple_definitions_without_main"
                },
                "conflicts": ["main_scope"],
                "roles": ["main_scope"],
            },
        )
    return definitions[0] if definitions else root


def _top_level_definitions(root: ET.Element) -> list[ET.Element]:
    if _name(root.tag) == "definition":
        return [root]
    definitions: list[ET.Element] = []

    def visit(element: ET.Element) -> None:
        for child in element:
            if _name(child.tag) == "definition":
                definitions.append(child)
            else:
                visit(child)

    visit(root)
    return definitions


def _component_elements(scope: ET.Element) -> list[ET.Element]:
    components: list[ET.Element] = []

    def visit(element: ET.Element) -> None:
        for child in element:
            child_name = _name(child.tag)
            if child_name == "definition":
                continue
            if child_name in {"user", "component"}:
                components.append(child)
            visit(child)

    visit(scope)
    return components


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
                "element": element,
                "parameters": _parameters(element),
            }
        )
    return records


def _exact_components(components: list[dict[str, Any]], local_name: str) -> list[dict[str, Any]]:
    return [component for component in components if component["local_name"] == local_name]


def _single_definition(components: list[dict[str, Any]]) -> str | None:
    if len(components) == 1:
        return components[0]["definition"]
    return None


def _select_earth_electrode(
    components: list[dict[str, Any]], source: str
) -> tuple[dict[str, Any] | None, str | None]:
    grounds = [component for component in components if component["definition"] == "master:ground"]
    anchors = [
        component
        for component in components
        if component["definition"] == "master:ammeter"
        and component["parameters"].get("Name") == "Ielectrode"
    ]
    if len(anchors) > 1:
        return None, "multiple_exact_ielectrode_anchors"
    if not grounds:
        return None, None
    if not anchors and len(grounds) > 1:
        return None, "multiple_exact_grounds_without_anchor"
    grounds = [
        {
            **component,
            "location": _point(component["element"], role="earth_electrode_ground"),
        }
        for component in grounds
    ]
    selected = grounds[0]
    evidence: dict[str, Any] = {
        "selected": {
            "definition": selected["definition"],
            "location": list(selected["location"]),
        },
        "selection_reason": "single_exact_ground_without_anchor",
    }
    if anchors:
        anchor = {
            **anchors[0],
            "location": _point(
                anchors[0]["element"], role="earth_electrode_anchor"
            ),
        }
        ranked = [
            (_distance_sq(anchor["location"], component["location"]), component)
            for component in grounds
        ]
        ranked.sort(key=lambda item: item[0])
        if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
            return None, "nearest_exact_ground_distance_tie"
        selected = ranked[0][1]
        evidence["anchor"] = {
            "definition": anchor["definition"],
            "location": list(anchor["location"]),
            "marker": {"name": "Name", "value": "Ielectrode"},
        }
        evidence["selected"] = {
            "definition": selected["definition"],
            "location": list(selected["location"]),
        }
        evidence["selection_reason"] = "nearest_exact_ground_to_ielectrode_anchor"
        evidence["distance"] = _distance(anchor["location"], selected["location"])
    return (
        {
            "definition": selected["definition"],
            "confidence": 1.0,
            "source": source,
            "evidence": evidence,
        },
        None,
    )


def _distance_sq(left: tuple[int, int], right: tuple[int, int]) -> int:
    return (left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2


def _distance(left: tuple[int, int], right: tuple[int, int]) -> float:
    return _distance_sq(left, right) ** 0.5
