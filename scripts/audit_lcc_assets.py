"""Audit the repository-authored CIGRE LCC companion library."""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from pscad_mcp.hvdc.builders.lcc.validator import validate_companion_library


_EXPECTED = {
    "cigre_lcc_v1:LCC12PulseBridge",
    "cigre_lcc_v1:RectifierControl",
    "cigre_lcc_v1:InverterControl",
    "cigre_lcc_v1:SignalInterface",
    "cigre_lcc_v1:Initialization",
}
_ABSOLUTE = re.compile(r"(?:^[A-Za-z]:[\\/]|^\\\\|(?:[A-Za-z]:[\\/])|(?:^|[\s=\"'])/[A-Za-z0-9_.-]+/)")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _text(value: str | None) -> str:
    return (value or "").strip()


def _library_path(root: Path) -> Path:
    candidates = sorted((root / "library").glob("*.pslx"))
    if len(candidates) != 1:
        raise ValueError("asset root must contain exactly one library/*.pslx file")
    return candidates[0]


def audit_asset_root(asset_root: str | Path) -> dict[str, Any]:
    root = Path(asset_root).expanduser().resolve()
    result: dict[str, Any] = {
        "valid": False,
        "asset_root": str(root),
        "library": None,
        "definitions": [],
        "valve_count": 0,
        "foreign_scopes": [],
        "absolute_paths": [],
        "errors": [],
        "warnings": [],
    }
    try:
        library = _library_path(root)
        result["library"] = str(library.relative_to(root).as_posix())
        tree = ET.parse(library)
        xml_root = tree.getroot()
    except (OSError, ET.ParseError, ValueError) as error:
        result["errors"].append({"reason": "library_parse_failure", "message": str(error)})
        return result

    definitions = []
    foreign_scopes: set[str] = set()
    absolute_paths: set[str] = set()
    for element in xml_root.iter():
        name = _text(element.attrib.get("name") or element.attrib.get("scoped_name"))
        if _local(element.tag) == "definition" and name:
            definitions.append(name)
        for value in element.attrib.values():
            if _ABSOLUTE.search(value):
                absolute_paths.add(value)
            if ":" in value:
                scope = value.split(":", 1)[0]
                if scope not in {"master", "cigre_lcc_v1"}:
                    foreign_scopes.add(scope)

    result["definitions"] = sorted(definitions)
    result["foreign_scopes"] = sorted(foreign_scopes)
    result["absolute_paths"] = sorted(absolute_paths)
    structure = validate_companion_library(library)
    result["errors"].extend(structure.get("errors", []))
    result["valve_count"] = sum(1 for element in xml_root.iter() if _local(element.tag) == "valve")
    if set(definitions) != _EXPECTED:
        result["errors"].append({"reason": "custom_definition_set_mismatch", "expected": sorted(_EXPECTED), "observed": sorted(definitions)})
    if foreign_scopes:
        result["errors"].append({"reason": "foreign_scope", "observed": sorted(foreign_scopes)})
    if absolute_paths:
        result["errors"].append({"reason": "absolute_path", "observed": sorted(absolute_paths)})

    provenance_path = root / "PROVENANCE.md"
    try:
        provenance = provenance_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        result["errors"].append({"reason": "provenance_missing_or_invalid", "message": str(error)})
    else:
        required_terms = ("Szechtman", "Wess", "Thio", "Electra", "table", "figure", "equation")
        missing_terms = [term for term in required_terms if term.casefold() not in provenance.casefold()]
        if missing_terms:
            result["errors"].append({"reason": "provenance_incomplete", "missing": missing_terms})
        if "C:\\PSCADFiles\\Breaker" in provenance or "Breaker" in provenance and "not" not in provenance.casefold():
            result["errors"].append({"reason": "unapproved_local_project_source"})

    result["valid"] = not result["errors"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-root", required=True)
    args = parser.parse_args()
    report = audit_asset_root(args.asset_root)
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
