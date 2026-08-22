"""Read-only, catalog-bound audit of user-provided LCC PSCX templates."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn
import xml.etree.ElementTree as ET

from ....core.backend.base import BackendError


TEMPLATE_MAX_BYTES = 32 * 1024 * 1024
_FORBIDDEN_XML_DECLARATION = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
_AUTHORITATIVE_CONTRACT_SHA256 = "70c0340cab292cf7f4625a9153721bd4a80aa0c3ddcbff3292029795ea55433d"
_NAMESPACE_MAX_CHARS = 128
_DEFINITION_MAX_CHARS = 256
_ROLE_TEXT_MAX_CHARS = 64
_COORDINATE_ABS_MAX = 10_000_000


@dataclass(frozen=True)
class TemplateAuditReport:
    compatible: bool
    roles: dict[str, Any]
    missing_contracts: tuple[str, ...]
    conflicts: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "compatible": self.compatible,
            "roles": self.roles,
            "missing_contracts": list(self.missing_contracts),
            "conflicts": list(self.conflicts),
            "fingerprint": self.fingerprint,
        }


def audit_lcc_template(
    path: str | Path, catalog: dict[str, Any] | None = None
) -> TemplateAuditReport:
    """Audit one immutable snapshot and authorize roles only through the v1 catalog."""

    contracts = _validated_contracts(catalog)
    source, payload = _read_template_once(path)
    fingerprint = hashlib.sha256(payload).hexdigest()
    root = _parse_template(payload)
    if root.tag != "project":
        raise BackendError(
            "LCC_TEMPLATE_INCOMPATIBLE",
            "Template root must be an unnamespaced PSCAD project element.",
            "hvdc",
            "audit_lcc_template",
            {"reason": "invalid_project_root"},
        )

    namespace = _bounded_role_text(
        _attr(root, contracts["project_namespace_attribute"]),
        field="namespace",
        maximum=_NAMESPACE_MAX_CHARS,
    )
    definitions = _definition_index(root)
    main = _main_scope(root)
    components = _component_records(main)
    roles: dict[str, Any] = {}
    missing: list[str] = []

    pole_contracts = contracts["pole_definitions"]
    validated_definitions: dict[str, tuple[str, dict[str, Any]] | None] = {}
    for family, contract in pole_contracts.items():
        definition = _single_validated_definition(definitions, contract)
        if definition is None or not namespace:
            missing.append(f"{family}_pole_definition")
            validated_definitions[family] = None
        else:
            full_scope = f"{namespace}:{contract['local_name']}"
            validated_definitions[family] = (full_scope, contract)

    rectifiers = _scoped_instances(components, validated_definitions["rectifier"])
    inverters = _scoped_instances(components, validated_definitions["inverter"])
    _assign_pole_roles(
        roles, missing, rectifiers, inverters, contracts["instance_discriminator"]
    )
    if "rectifier_pole_definition" in missing:
        missing = [item for item in missing if item != "rectifier_valve_group"]
    if "inverter_pole_definition" in missing:
        missing = [item for item in missing if item != "inverter_valve_group"]

    earth_result, earth_conflict = _select_earth_electrode(
        components, contracts["earth_electrode"]
    )
    if earth_conflict is not None:
        _raise_ambiguous("earth_electrode", earth_conflict)
    if earth_result is None:
        missing.append("earth_electrode")
    else:
        roles["earth_electrode"] = earth_result

    return TemplateAuditReport(
        compatible=not missing,
        roles=roles,
        missing_contracts=tuple(sorted(set(missing))),
        conflicts=(),
        fingerprint=fingerprint,
    )


def _validated_contracts(catalog: dict[str, Any] | None) -> dict[str, Any]:
    if catalog is None:
        from .assets import load_parametric_catalog

        catalog = load_parametric_catalog()
    try:
        contracts = catalog["template_role_contracts"]
        encoded = json.dumps(
            contracts, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        valid = (
            catalog.get("identity") == "lcc_parametric_catalog_v1"
            and catalog.get("schema_version") == 1
            and isinstance(contracts, dict)
            and contracts.get("schema_version") == 1
            and contracts.get("authoritative") is True
            and hashlib.sha256(encoded).hexdigest() == _AUTHORITATIVE_CONTRACT_SHA256
        )
    except (KeyError, TypeError, ValueError, UnicodeError):
        valid = False
    if not valid:
        raise BackendError(
            "LCC_ASSET_MISMATCH",
            "Parametric catalog template role contracts are invalid.",
            "hvdc",
            "audit_lcc_template",
            {"reason": "invalid_template_role_contracts"},
        )
    return contracts


def _read_template_once(path: str | Path) -> tuple[Path, bytes]:
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
                    {"actual_bytes": actual_bytes, "max_bytes": TEMPLATE_MAX_BYTES, "reason": "template_too_large"},
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
            {"actual_bytes": len(payload), "max_bytes": TEMPLATE_MAX_BYTES, "reason": "template_too_large"},
        )
    return source, payload


def _parse_template(payload: bytes) -> ET.Element:
    if _FORBIDDEN_XML_DECLARATION.search(payload.replace(b"\x00", b"")):
        raise BackendError(
            "LCC_TEMPLATE_INCOMPATIBLE", "Template contains a forbidden XML declaration.",
            "hvdc", "audit_lcc_template", {"reason": "forbidden_xml_declaration"},
        )
    try:
        return ET.fromstring(payload)
    except (ET.ParseError, LookupError, ValueError) as error:
        raise BackendError(
            "LCC_TEMPLATE_INCOMPATIBLE", "Template is not valid PSCX XML.",
            "hvdc", "audit_lcc_template",
            {"error_type": type(error).__name__, "reason": "invalid_xml"},
        ) from error


def _raise_unreadable_template(error: OSError) -> NoReturn:
    raise BackendError(
        "LCC_TEMPLATE_INCOMPATIBLE", "Template could not be read.",
        "hvdc", "audit_lcc_template",
        {"error_type": type(error).__name__, "reason": "template_unreadable"},
    ) from error


def _attr(element: ET.Element, *names: str) -> str | None:
    wanted = {name.casefold() for name in names}
    for key, value in element.attrib.items():
        if key.casefold() in wanted:
            return value
    return None


def _text(value: str | None) -> str:
    return (value or "").strip()


def _bounded_role_text(
    value: str | None, *, field: str, maximum: int = _ROLE_TEXT_MAX_CHARS
) -> str:
    normalized = _text(value)
    if len(normalized) > maximum:
        raise BackendError(
            "LCC_TEMPLATE_INCOMPATIBLE",
            "Template role text exceeds its fixed limit.",
            "hvdc",
            "audit_lcc_template",
            {
                "reason": "role_text_too_long",
                "field": field,
                "actual_length": len(normalized),
                "max_length": maximum,
            },
        )
    return normalized


def _definition_index(root: ET.Element) -> dict[str, list[ET.Element]]:
    result: dict[str, list[ET.Element]] = {}
    for definition in _top_level_definitions(root):
        name = _bounded_role_text(_attr(definition, "name", "id"), field="definition_name")
        result.setdefault(name, []).append(definition)
    return result


def _single_validated_definition(
    definitions: dict[str, list[ET.Element]], contract: dict[str, Any]
) -> ET.Element | None:
    candidates = definitions.get(contract["local_name"], [])
    if len(candidates) != 1:
        return None
    definition = candidates[0]
    if not _form_contract_matches(definition, contract["form_parameters"]):
        return None
    if not _port_contract_matches(definition, contract["ports"]):
        return None
    counts = Counter(component["definition"] for component in _component_records(definition))
    if any(counts[name] < rule["minimum"] for name, rule in contract["internal_components"].items()):
        return None
    return definition


def _form_contract_matches(definition: ET.Element, expected: dict[str, Any]) -> bool:
    found: dict[str, list[ET.Element]] = {}
    for child in definition:
        if child.tag != "form":
            continue
        for element in child.iter():
            if element.tag == "parameter":
                found.setdefault(_text(_attr(element, "name")), []).append(element)
    for name, contract in expected.items():
        candidates = found.get(name, [])
        if len(candidates) != 1 or _text(_attr(candidates[0], "type")) != contract["type"]:
            return False
    return True


def _port_contract_matches(definition: ET.Element, expected: dict[str, Any]) -> bool:
    found: dict[str, list[ET.Element]] = {}
    for child in definition:
        if child.tag != "svg":
            continue
        for element in child.iter():
            if element.tag == "port":
                found.setdefault(_text(_attr(element, "name")), []).append(element)
    for name, contract in expected.items():
        candidates = found.get(name, [])
        if len(candidates) != 1:
            return False
        port = candidates[0]
        for field, value in contract.items():
            actual = _text(_attr(port, field))
            if field == "dim":
                if actual != str(value):
                    return False
            elif actual != value:
                return False
    return True


def _scoped_instances(
    components: list[dict[str, Any]], validated: tuple[str, dict[str, Any]] | None
) -> list[dict[str, Any]]:
    if validated is None:
        return []
    full_scope, contract = validated
    return [
        {**component, "contract": contract}
        for component in components
        if component["definition"] == full_scope
    ]


def _assign_pole_roles(
    roles: dict[str, Any],
    missing: list[str],
    rectifiers: list[dict[str, Any]],
    inverters: list[dict[str, Any]],
    discriminator: dict[str, Any],
) -> None:
    counts = (len(rectifiers), len(inverters))
    if counts == (1, 1):
        roles["rectifier_valve_group"] = _pole_evidence(rectifiers[0], discriminator)
        roles["inverter_valve_group"] = _pole_evidence(inverters[0], discriminator)
        return
    if counts == (2, 2):
        expected = discriminator["bipole_roles"]
        parameter = discriminator["parameter"]
        records = rectifiers + inverters
        markers = [component["parameters"].get(parameter) for component in records]
        if any(marker not in expected for marker in markers):
            missing.append("bipole_pole_discriminators")
            return
        if len(set(markers)) != 4:
            _raise_ambiguous("pole_instances", "duplicate_or_missing_bipole_discriminator")
        for component, marker in zip(records, markers, strict=True):
            family = "rectifier" if component in rectifiers else "inverter"
            if not marker.startswith("R" if family == "rectifier" else "I"):
                missing.append("bipole_pole_discriminators")
                roles.clear()
                return
            roles[expected[marker]] = _pole_evidence(component, discriminator)
        return
    if len(rectifiers) == 0:
        missing.append("rectifier_valve_group")
    if len(inverters) == 0:
        missing.append("inverter_valve_group")
    if len(rectifiers) > 0 and len(inverters) > 0:
        _raise_ambiguous("pole_instances", "unsupported_pole_instance_cardinality")


def _pole_evidence(component: dict[str, Any], discriminator: dict[str, Any]) -> dict[str, Any]:
    parameter = discriminator["parameter"]
    evidence: dict[str, Any] = {
        "definition": component["definition"],
        "location": list(_point(component["element"], role="pole_instance")),
        "discriminator": {"name": parameter, "value": component["parameters"].get(parameter, "")},
        "validated_contract": component["contract"]["contract_identity"],
    }
    instance_id = _bounded_role_text(
        _attr(component["element"], "id"), field="instance_id"
    )
    if instance_id:
        evidence["instance_id"] = instance_id
    return evidence


def _raise_ambiguous(role: str, reason: str) -> NoReturn:
    raise BackendError(
        "LCC_TEMPLATE_AMBIGUOUS", "Template contains ambiguous role candidates.",
        "hvdc", "audit_lcc_template",
        {"compatible": False, "conflicts": [role], "roles": [role], "conflict_reasons": {role: reason}},
    )


def _integer(value: str, *, field: str) -> int:
    normalized = value.strip()
    try:
        number = int(normalized)
    except ValueError as error:
        _raise_invalid_coordinate(field, normalized, error)
    if abs(number) > _COORDINATE_ABS_MAX:
        _raise_invalid_coordinate(field, normalized)
    return number


def _raise_invalid_coordinate(field: str, value: str, cause: Exception | None = None) -> NoReturn:
    error = BackendError(
        "LCC_TEMPLATE_INCOMPATIBLE", "Component coordinate is invalid.",
        "hvdc", "audit_lcc_template",
        {"field": field, "reason": "invalid_component_coordinate", "value_length": len(value), "value_preview": value[:64]},
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
            "LCC_TEMPLATE_INCOMPATIBLE", "A role component coordinate is missing.",
            "hvdc", "audit_lcc_template", {"reason": "missing_component_coordinate", "role": role},
        )
    return _integer(x, field="x"), _integer(y, field="y")


def _parameters(element: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    direct_children = list(element)
    parameters = [child for child in direct_children if child.tag == "param"]
    for child in direct_children:
        if child.tag == "paramlist":
            parameters.extend(parameter for parameter in list(child) if parameter.tag == "param")
    for parameter in parameters:
        name = _text(_attr(parameter, "name", "key"))
        if name in {"Des", "Name"}:
            if name in result:
                raise BackendError(
                    "LCC_TEMPLATE_INCOMPATIBLE", "Component contains duplicate parameters.",
                    "hvdc", "audit_lcc_template", {"parameter": name[:64], "reason": "duplicate_component_parameter"},
                )
            value = _attr(parameter, "value")
            result[name] = _bounded_role_text(
                value if value is not None else parameter.text,
                field=name,
            )
    return result


def _main_scope(root: ET.Element) -> ET.Element:
    definitions = _top_level_definitions(root)
    main_definitions = [definition for definition in definitions if _text(_attr(definition, "name", "id")).casefold() == "main"]
    if len(main_definitions) > 1:
        _raise_ambiguous("main_scope", "multiple_main_definitions")
    if main_definitions:
        return main_definitions[0]
    if len(definitions) > 1:
        _raise_ambiguous("main_scope", "multiple_definitions_without_main")
    return definitions[0] if definitions else root


def _top_level_definitions(root: ET.Element) -> list[ET.Element]:
    containers = [child for child in root if child.tag == "definitions"]
    if len(containers) != 1:
        return []
    return [child for child in containers[0] if child.tag == "Definition"]


def _component_elements(scope: ET.Element) -> list[ET.Element]:
    schematics = [child for child in scope if child.tag == "schematic"]
    if len(schematics) != 1:
        return []
    return [child for child in schematics[0] if child.tag == "User"]


def _component_records(scope: ET.Element) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for element in _component_elements(scope):
        definition = _bounded_role_text(
            _attr(element, "definition", "defn", "type"),
            field="definition",
            maximum=_DEFINITION_MAX_CHARS,
        )
        if definition:
            records.append({"definition": definition, "element": element, "parameters": _parameters(element)})
    return records


def _select_earth_electrode(
    components: list[dict[str, Any]], contract: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    grounds = [component for component in components if component["definition"] == contract["ground_definition"]]
    anchors = [
        component for component in components
        if component["definition"] == contract["anchor_definition"]
        and component["parameters"].get(contract["anchor_parameter"]) == contract["anchor_value"]
    ]
    if len(anchors) > 1:
        return None, "multiple_exact_ielectrode_anchors"
    if not grounds:
        return None, None
    if not anchors and len(grounds) > 1:
        return None, "multiple_exact_grounds_without_anchor"
    if not anchors and contract["no_anchor_fallback"] != "single_exact_ground":
        return None, None
    located = [{**component, "location": _point(component["element"], role="earth_electrode_ground")} for component in grounds]
    selected = located[0]
    evidence: dict[str, Any] = {
        "selected": _component_location_evidence(selected),
        "selection_reason": "single_exact_ground_without_anchor",
        "validated_contract": contract["contract_identity"],
    }
    if anchors:
        anchor = {**anchors[0], "location": _point(anchors[0]["element"], role="earth_electrode_anchor")}
        ranked = sorted((_distance_sq(anchor["location"], item["location"]), item) for item in located)
        if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
            return None, "nearest_exact_ground_distance_tie"
        selected = ranked[0][1]
        evidence.update({
            "anchor": {**_component_location_evidence(anchor), "marker": {"name": contract["anchor_parameter"], "value": contract["anchor_value"]}},
            "selected": _component_location_evidence(selected),
            "selection_reason": "nearest_exact_ground_to_ielectrode_anchor",
            "distance": _distance(anchor["location"], selected["location"]),
        })
    return ({"definition": selected["definition"], "evidence": evidence}, None)


def _component_location_evidence(component: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"definition": component["definition"], "location": list(component["location"])}
    instance_id = _bounded_role_text(
        _attr(component["element"], "id"), field="instance_id"
    )
    if instance_id:
        result["instance_id"] = instance_id
    return result


def _distance_sq(left: tuple[int, int], right: tuple[int, int]) -> int:
    return (left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2


def _distance(left: tuple[int, int], right: tuple[int, int]) -> float:
    return _distance_sq(left, right) ** 0.5
