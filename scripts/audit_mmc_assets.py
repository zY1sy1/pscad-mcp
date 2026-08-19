"""Audit and safely materialize the repository-authored MMC AVM asset set."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


_ALLOWED_SCOPES = {"master", "cigre_mmc_avm_v1"}
_ABSOLUTE = re.compile(r"(?:^[A-Za-z]:[\\/]|^\\\\|(?:[A-Za-z]:[\\/])|(?:^|[\s=\"'])/[A-Za-z0-9_.-]+/)")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _text(value: str | None) -> str:
    return (value or "").strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _error(reason: str, **details: Any) -> dict[str, Any]:
    return {"reason": reason, **details}


def _library_path(root: Path) -> Path:
    candidates = sorted((root / "library").glob("*.pslx"))
    if len(candidates) != 1:
        raise ValueError("asset root must contain exactly one library/*.pslx file")
    return candidates[0]


def _port_contract(definition: ET.Element) -> list[dict[str, Any]]:
    ports: list[dict[str, Any]] = []
    for element in definition.iter():
        if _local(element.tag) != "port":
            continue
        item = {"name": _text(element.attrib.get("name"))}
        for key in ("kind", "dimension"):
            if key in element.attrib:
                item[key] = element.attrib[key]
        ports.append(item)
    return ports


def audit_asset_root(asset_root: str | Path) -> dict[str, Any]:
    """Return a JSON-safe audit report for a fixed MMC asset root."""

    root = Path(asset_root).expanduser().resolve()
    result: dict[str, Any] = {
        "valid": False,
        "asset_root": str(root),
        "pscad_version": None,
        "library": None,
        "manifest_files": [],
        "definitions": [],
        "foreign_scopes": [],
        "absolute_paths": [],
        "errors": [],
        "warnings": [],
    }
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be an object")
        manifest_files = manifest.get("files")
        if not isinstance(manifest_files, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in manifest_files.items()):
            raise ValueError("manifest.files must be a string-to-string mapping")
        result["manifest_files"] = sorted(manifest_files)
        result["pscad_version"] = manifest.get("pscad_version")
        if manifest.get("schema_version") != 1:
            result["errors"].append(_error("manifest_schema_invalid"))
        if result["pscad_version"] != "4.6.2":
            result["errors"].append(_error("version_unsupported", observed=result["pscad_version"], required="4.6.2"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        result["errors"].append(_error("manifest_missing_or_invalid", message=str(error)))
        return result

    expected_files = set(result["manifest_files"])
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    for relative in sorted(actual_files - expected_files):
        result["errors"].append(_error("unexpected_file", path=relative))
    for relative in sorted(expected_files - actual_files):
        result["errors"].append(_error("manifest_file_missing", path=relative))
    for relative in sorted(expected_files & actual_files):
        observed = _sha256(root / Path(relative))
        if observed != json.loads(manifest_path.read_text(encoding="utf-8"))["files"][relative]:
            result["errors"].append(_error("manifest_hash_mismatch", path=relative, observed=observed))

    try:
        library = _library_path(root)
        result["library"] = library.relative_to(root).as_posix()
        tree = ET.parse(library)
        xml_root = tree.getroot()
    except (OSError, ET.ParseError, ValueError) as error:
        result["errors"].append(_error("library_parse_failure", message=str(error)))
        return result

    try:
        catalog_path = root / "catalog-pscad-4.6.2.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        catalog_definitions = catalog["definitions"]
        if catalog.get("pscad_version") != "4.6.2":
            result["errors"].append(_error("catalog_version_unsupported", observed=catalog.get("pscad_version")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        catalog_definitions = {}
        result["errors"].append(_error("catalog_missing_or_invalid", message=str(error)))

    definitions: dict[str, ET.Element] = {}
    foreign_scopes: set[str] = set()
    absolute_paths: set[str] = set()
    for element in xml_root.iter():
        name = _text(element.attrib.get("name") or element.attrib.get("scoped_name"))
        if _local(element.tag) == "definition" and name:
            if name in definitions:
                result["errors"].append(_error("duplicate_definition", definition=name))
            definitions[name] = element
            lowered = name.casefold()
            if "complete" in lowered or "two_terminal" in lowered or "full_link" in lowered:
                result["errors"].append(_error("opaque_topology", definition=name))
        for value in element.attrib.values():
            if _ABSOLUTE.search(value):
                absolute_paths.add(value)
            if ":" in value and not value.casefold().startswith(("http:", "https:")):
                scope = value.split(":", 1)[0]
                if scope not in _ALLOWED_SCOPES:
                    foreign_scopes.add(scope)

    result["definitions"] = sorted(definitions)
    result["foreign_scopes"] = sorted(foreign_scopes)
    result["absolute_paths"] = sorted(absolute_paths)
    if foreign_scopes:
        result["errors"].append(_error("foreign_scope", observed=sorted(foreign_scopes)))
    if absolute_paths:
        result["errors"].append(_error("absolute_path", observed=sorted(absolute_paths)))

    expected_definitions = set(catalog_definitions) if isinstance(catalog_definitions, dict) else set()
    if set(definitions) != expected_definitions:
        result["errors"].append(_error("custom_definition_set_mismatch", expected=sorted(expected_definitions), observed=sorted(definitions)))
    for name in sorted(expected_definitions & set(definitions)):
        expected_ports = catalog_definitions[name].get("ports", []) if isinstance(catalog_definitions[name], dict) else []
        if expected_ports and _port_contract(definitions[name]) != expected_ports:
            result["errors"].append(_error("port_drift", definition=name, expected=expected_ports, observed=_port_contract(definitions[name])))

    provenance_path = root / "PROVENANCE.md"
    try:
        provenance = provenance_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        result["errors"].append(_error("provenance_missing_or_invalid", message=str(error)))
    else:
        required_terms = ("public source", "original derivation", "avm limitations")
        missing_terms = [term for term in required_terms if term.casefold() not in provenance.casefold()]
        if missing_terms:
            result["errors"].append(_error("provenance_incomplete", missing=missing_terms))

    result["valid"] = not result["errors"]
    return result


def materialize_library(asset_root: str | Path, destination: str | Path) -> Path:
    """Atomically copy a validated companion library to ``destination``."""

    report = audit_asset_root(asset_root)
    if not report["valid"]:
        raise ValueError(f"MMC asset audit failed: {report['errors']}")
    source = Path(asset_root).expanduser().resolve() / report["library"]
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-root", required=True)
    args = parser.parse_args()
    report = audit_asset_root(args.asset_root)
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
