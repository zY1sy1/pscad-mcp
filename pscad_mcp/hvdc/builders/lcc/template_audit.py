"""Read-only audit of user-provided LCC PSCX templates."""

from __future__ import annotations

import hashlib
import json
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
    text = " ".join(root.itertext())
    definitions = [elem.attrib.get("definition", "") for elem in root.iter() if elem.attrib.get("definition")]
    roles: dict[str, Any] = {}
    candidates = {
        "rectifier_valve_group": "cigre_lcc_v1:LCC12PulseBridge",
        "inverter_valve_group": "cigre_lcc_v1:LCC12PulseBridge",
        "earth_electrode": "master:ground",
    }
    conflicts: list[str] = []
    missing: list[str] = []
    for role, definition in candidates.items():
        matches = [item for item in definitions if item == definition]
        if role == "earth_electrode":
            matches = [item for item in definitions if item == definition or "earth" in item.casefold() or "ground" in item.casefold()]
        if len(matches) == 1:
            roles[role] = {"definition": matches[0], "confidence": 1.0, "source": str(source)}
        elif len(matches) == 0:
            missing.append(role)
        else:
            conflicts.append(role)
    if "LCC12PulseBridge" not in text and not any("LCC12PulseBridge" in item for item in definitions):
        missing.append("rectifier_valve_group")
    if conflicts:
        raise BackendError("LCC_TEMPLATE_AMBIGUOUS", "Template contains ambiguous role candidates.", "hvdc", "audit_lcc_template", {"roles": conflicts})
    compatible = not missing
    return TemplateAuditReport(compatible, roles, tuple(sorted(set(missing))), tuple(sorted(conflicts)), fingerprint)
