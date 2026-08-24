"""Hash-verified packaged assets for the CIGRE LCC builder."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from ....core.backend.base import BackendError
from .models import LccBlueprint
from .schema import parse_blueprint


_SUPPORTED_NAME = "cigre_lcc_monopole_v1"
_SUPPORTED_PSCAD_VERSION = "4.6.2"
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PARAMETRIC_NAMES = {
    "lcc_monopole_parametric_v1": "monopolar",
    "lcc_bipole_parametric_v1": "bipolar",
}
_PARAMETRIC_NET_ENDPOINTS = {
    "monopolar": {
        "dc_pole": (("rectifier_valve_group", "DCP1"), ("inverter_valve_group", "DCP1")),
        "earth_return": (
            ("rectifier_valve_group", "DCP2"),
            ("inverter_valve_group", "DCP2"),
            ("neutral_bus", "earth"),
            ("earth_electrode", "A"),
        ),
        "metallic_return": (("neutral_bus", "metallic"), ("metallic_return_terminal", "remote")),
    },
    "bipolar": {
        "dc_positive": (("rectifier_positive_pole", "DCP1"), ("inverter_positive_pole", "DCP1")),
        "dc_negative": (("rectifier_negative_pole", "DCP1"), ("inverter_negative_pole", "DCP1")),
        "neutral_bus": (
            ("rectifier_positive_pole", "DCP2"),
            ("inverter_positive_pole", "DCP2"),
            ("rectifier_negative_pole", "DCP2"),
            ("inverter_negative_pole", "DCP2"),
            ("neutral_bus", "rp1"),
            ("neutral_bus", "ip1"),
            ("neutral_bus", "rp2"),
            ("neutral_bus", "ip2"),
        ),
        "earth_return": (("neutral_bus", "earth"), ("earth_electrode", "A")),
        "metallic_return": (("neutral_bus", "metallic"), ("metallic_return_terminal", "remote")),
    },
}
_PARAMETRIC_BLUEPRINT_KEYS = {
    "schema_version", "name", "identity", "catalog_identity",
    "provenance_identity", "contract_kind", "topology",
    "parameter_topology", "poles", "terminals", "required_assets",
    "return_paths", "template_roles", "components", "nets", "outputs",
}
_PARAMETRIC_CATALOG_KEYS = {
    "schema_version", "name", "pscad_version", "identity",
    "provenance_identity", "provenance_sha256", "rating_contract_asset",
    "definitions", "template_role_contracts", "blueprint_hashes",
    "topology_contracts", "logical_parameter_bindings", "template_bindings", "rating_parameters",
    "derived_parameters", "engineering_parameters", "feasibility_relationships",
    "return_contract_assets", "return_asset_requirements",
}
_PARAMETRIC_PROVENANCE_KEYS = {
    "schema_version", "identity", "catalog_structure_contract_asset", "entries",
}


@dataclass(frozen=True)
class LccAssetSet:
    name: str
    schema_version: int
    pscad_version: str
    companion_library: str
    blueprint: LccBlueprint
    catalog: dict[str, Any]
    acceptance: dict[str, Any]
    golden: dict[str, Any]
    provenance: str
    hashes: dict[str, str]
    library_bytes: bytes
    files: dict[str, bytes]
    root: None = None


def _asset_error(code: str, message: str, operation: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", operation, details)


def sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            f"Asset path '{path}' is not a regular file.",
            "load_lcc_asset_set",
            path=str(path),
        )
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            f"Unable to read asset '{path}'.",
            "load_lcc_asset_set",
            path=str(path),
        ) from error
    return digest.hexdigest()


def _read_hashed_file(path: Path) -> tuple[bytes, str]:
    if path.is_symlink() or not path.is_file():
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            f"Asset path '{path}' is not a regular file.",
            "load_lcc_asset_set",
            path=str(path),
        )
    try:
        with path.open("rb") as stream:
            payload = stream.read()
    except OSError as error:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            f"Unable to read asset '{path}'.",
            "load_lcc_asset_set",
            path=str(path),
        ) from error
    return payload, hashlib.sha256(payload).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _manifest_object(root: Path) -> dict[str, Any]:
    path = root / "manifest.json"
    if not path.is_file():
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The LCC asset manifest is missing.",
            "load_lcc_asset_set",
            path=str(path),
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The LCC asset manifest is not valid JSON.",
            "load_lcc_asset_set",
            path=str(path),
        ) from error
    if not isinstance(value, dict):
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The LCC asset manifest must be a JSON object.",
            "load_lcc_asset_set",
        )
    return value


def _relative_child(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "Manifest paths must be non-empty strings.",
            "load_lcc_asset_set",
            path=repr(relative),
        )
    if relative == "manifest.json" or "\\" in relative:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            f"Manifest path '{relative}' is not a canonical relative path.",
            "load_lcc_asset_set",
            path=relative,
        )
    posix = PurePosixPath(relative)
    if posix.is_absolute() or PureWindowsPath(relative).is_absolute() or ".." in posix.parts:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            f"Manifest path '{relative}' escapes the asset root.",
            "load_lcc_asset_set",
            path=relative,
        )
    root_resolved = root.resolve()
    candidate = (root / Path(*posix.parts)).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as error:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            f"Manifest path '{relative}' escapes the asset root.",
            "load_lcc_asset_set",
            path=relative,
        ) from error
    return candidate


def _manifest_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    configured = [key for key in ("hashes", "files") if key in manifest]
    if len(configured) != 1 or not isinstance(manifest[configured[0]], dict):
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The manifest must contain exactly one hashes object.",
            "load_lcc_asset_set",
        )
    hashes: dict[str, str] = {}
    for relative, digest in manifest[configured[0]].items():
        if not isinstance(relative, str) or not isinstance(digest, str) or not _HASH_PATTERN.fullmatch(digest):
            raise _asset_error(
                "LCC_ASSET_MISMATCH",
                "Manifest hashes must be lowercase SHA-256 strings.",
                "load_lcc_asset_set",
                path=repr(relative),
            )
        _relative_child(Path(manifest["__root__"]), relative)
        hashes[relative] = digest
    return hashes


def _json_record(files: dict[str, bytes], relative: str) -> dict[str, Any]:
    try:
        value = json.loads(files[relative].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            f"Asset '{relative}' is not valid UTF-8 JSON.",
            "load_lcc_asset_set",
            path=relative,
        ) from error
    if not isinstance(value, dict):
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            f"Asset '{relative}' must contain a JSON object.",
            "load_lcc_asset_set",
            path=relative,
        )
    return value


def load_asset_set(asset_root: str | Path) -> LccAssetSet:
    """Load an asset directory only after its complete manifest is verified."""

    root = Path(asset_root).expanduser().resolve()
    if not root.is_dir():
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The LCC asset root is not a directory.",
            "load_lcc_asset_set",
            root=str(root),
        )
    manifest = _manifest_object(root)
    schema_version = manifest.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != 1:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The LCC asset manifest schema version must be 1.",
            "load_lcc_asset_set",
            schema_version=schema_version,
        )
    name = manifest.get("name")
    pscad_version = manifest.get("pscad_version")
    companion_library = manifest.get("companion_library")
    if not all(isinstance(value, str) and value.strip() for value in (name, pscad_version, companion_library)):
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The manifest name, PSCAD version, and companion library are required.",
            "load_lcc_asset_set",
        )
    if pscad_version != _SUPPORTED_PSCAD_VERSION:
        raise _asset_error(
            "LCC_VERSION_UNSUPPORTED",
            f"LCC assets require PSCAD {_SUPPORTED_PSCAD_VERSION}.",
            "load_lcc_asset_set",
            requested_version=pscad_version,
            supported_version=_SUPPORTED_PSCAD_VERSION,
        )

    manifest["__root__"] = str(root)
    hashes = _manifest_hashes(manifest)
    actual_files: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise _asset_error(
                "LCC_ASSET_MISMATCH",
                "Symlinks are not allowed in the packaged LCC asset set.",
                "load_lcc_asset_set",
                path=relative,
            )
        if path.is_file() and relative != "manifest.json":
            actual_files.add(relative)
    if actual_files != set(hashes):
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The asset files do not exactly match the manifest.",
            "load_lcc_asset_set",
            missing=sorted(set(hashes) - actual_files),
            unexpected=sorted(actual_files - set(hashes)),
        )

    files: dict[str, bytes] = {}
    for relative, expected in hashes.items():
        path = _relative_child(root, relative)
        payload, observed = _read_hashed_file(path)
        if observed != expected:
            raise _asset_error(
                "LCC_ASSET_MISMATCH",
                f"Asset '{relative}' does not match its manifest hash.",
                "load_lcc_asset_set",
                path=relative,
                expected=expected,
                observed=observed,
            )
        files[relative] = payload

    required = {
        "blueprint.json",
        "catalog-pscad-4.6.2.json",
        "acceptance.json",
        "golden.json",
        "PROVENANCE.md",
        companion_library,
    }
    missing_required = sorted(required - set(files))
    if missing_required:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The asset set is missing required files.",
            "load_lcc_asset_set",
            missing=missing_required,
        )
    try:
        provenance = files["PROVENANCE.md"].decode("utf-8")
    except UnicodeDecodeError as error:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "PROVENANCE.md must be UTF-8 text.",
            "load_lcc_asset_set",
        ) from error
    blueprint_value = _json_record(files, "blueprint.json")
    blueprint = parse_blueprint(blueprint_value)
    if blueprint.name != name:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The blueprint name does not match the manifest.",
            "load_lcc_asset_set",
            manifest_name=name,
            blueprint_name=blueprint.name,
        )
    return LccAssetSet(
        name=name,
        schema_version=schema_version,
        pscad_version=pscad_version,
        companion_library=companion_library,
        blueprint=blueprint,
        catalog=_json_record(files, "catalog-pscad-4.6.2.json"),
        acceptance=_json_record(files, "acceptance.json"),
        golden=_json_record(files, "golden.json"),
        provenance=provenance,
        hashes=dict(hashes),
        library_bytes=bytes(files[companion_library]),
        files=dict(files),
    )


def load_packaged_asset_set(name: str = _SUPPORTED_NAME) -> LccAssetSet:
    if name != _SUPPORTED_NAME:
        raise _asset_error(
            "LCC_BLUEPRINT_NOT_FOUND",
            f"LCC blueprint '{name}' was not found.",
            "load_packaged_lcc_assets",
            blueprint=name,
        )
    resource = resources.files("pscad_mcp").joinpath("assets", "lcc", name)
    if not resource.is_dir():
        raise _asset_error(
            "LCC_BLUEPRINT_NOT_FOUND",
            f"Packaged LCC blueprint '{name}' is not available.",
            "load_packaged_lcc_assets",
            blueprint=name,
        )
    with resources.as_file(resource) as materialized:
        return load_asset_set(materialized)


def _record_ids(values: Any, key: str, field: str) -> list[str]:
    if not isinstance(values, list) or not values:
        raise _asset_error("LCC_BLUEPRINT_INVALID", f"{field} must be a non-empty array.", "load_parametric_blueprint", field=field)
    result: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, dict) or not isinstance(value.get(key), str) or not value[key]:
            raise _asset_error("LCC_BLUEPRINT_INVALID", f"{field} entries require '{key}'.", "load_parametric_blueprint", field=field, index=index)
        result.append(value[key])
    if len(result) != len(set(result)):
        raise _asset_error("LCC_BLUEPRINT_INVALID", f"{field} identities must be unique.", "load_parametric_blueprint", field=field)
    return result


def _text_list(value: Any, field: str, *, nonempty: bool = True) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value) or any(not isinstance(item, str) or not item for item in value):
        raise _asset_error("LCC_BLUEPRINT_INVALID", f"{field} must be an array of non-empty strings.", "load_parametric_blueprint", field=field)
    if len(value) != len(set(value)):
        raise _asset_error("LCC_BLUEPRINT_INVALID", f"{field} values must be unique.", "load_parametric_blueprint", field=field)
    return value


def validate_parametric_catalog_asset(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _asset_error("LCC_ASSET_MISMATCH", "Parametric catalog must be an object.", "load_parametric_catalog")
    if set(value) != _PARAMETRIC_CATALOG_KEYS:
        raise _asset_error("LCC_ASSET_MISMATCH", "Parametric catalog schema fields are not exact.", "load_parametric_catalog")
    if (
        value.get("schema_version") != 1
        or isinstance(value.get("schema_version"), bool)
        or value.get("name") != "lcc_parametric_catalog_v1"
        or value.get("identity") != "lcc_parametric_catalog_v1"
        or value.get("provenance_identity") != "lcc_parametric_provenance_v1"
        or not isinstance(value.get("provenance_sha256"), str)
        or not _HASH_PATTERN.fullmatch(value["provenance_sha256"])
        or value.get("pscad_version") != _SUPPORTED_PSCAD_VERSION
    ):
        raise _asset_error("LCC_ASSET_MISMATCH", "Parametric catalog identity or provenance mismatch.", "load_parametric_catalog")
    hashes = value.get("blueprint_hashes")
    topologies = value.get("topology_contracts")
    bindings = value.get("logical_parameter_bindings")
    template_bindings = value.get("template_bindings")
    if not isinstance(hashes, dict) or set(hashes) != set(_PARAMETRIC_NAMES) or any(not isinstance(item, str) or not _HASH_PATTERN.fullmatch(item) for item in hashes.values()):
        raise _asset_error("LCC_ASSET_MISMATCH", "Parametric blueprint hashes are invalid.", "load_parametric_catalog")
    if not isinstance(topologies, dict) or set(topologies) != set(_PARAMETRIC_NAMES.values()):
        raise _asset_error("LCC_ASSET_MISMATCH", "Parametric topology contracts are invalid.", "load_parametric_catalog")
    if not isinstance(bindings, dict) or not bindings:
        raise _asset_error("LCC_ASSET_MISMATCH", "Parametric logical parameter bindings are missing.", "load_parametric_catalog")
    if not isinstance(template_bindings, list) or not template_bindings:
        raise _asset_error("LCC_ASSET_MISMATCH", "Reviewed template bindings are missing.", "load_parametric_catalog")
    topology_roles: dict[str, set[str]] = {}
    topology_keys = {"blueprint", "template_roles", "component_roles", "net_ids", "required_return_nets", "output_names"}
    for topology, contract in topologies.items():
        expected_blueprint = next(name for name, declared_topology in _PARAMETRIC_NAMES.items() if declared_topology == topology)
        if not isinstance(contract, dict) or set(contract) != topology_keys or contract.get("blueprint") != expected_blueprint:
            raise _asset_error("LCC_ASSET_MISMATCH", "A parametric topology contract has invalid fields.", "load_parametric_catalog", topology=topology)
        for field in topology_keys - {"blueprint"}:
            items = contract.get(field)
            if not isinstance(items, list) or not items or any(not isinstance(item, str) or not item for item in items) or len(items) != len(set(items)):
                raise _asset_error("LCC_ASSET_MISMATCH", "A parametric topology contract list is invalid.", "load_parametric_catalog", topology=topology, field=field)
        if not set(contract["template_roles"]) < set(contract["component_roles"]):
            raise _asset_error("LCC_ASSET_MISMATCH", "Template roles must be a strict subset of topology component roles.", "load_parametric_catalog", topology=topology)
        if not set(contract["required_return_nets"]) <= set(contract["net_ids"]):
            raise _asset_error("LCC_ASSET_MISMATCH", "Required return nets are not declared by the topology.", "load_parametric_catalog", topology=topology)
        topology_roles[topology] = set(contract["template_roles"])
    declared_parameter_names = set(value.get("rating_parameters", {})) | set(value.get("derived_parameters", {})) | set(value.get("engineering_parameters", {}))
    relationships = value.get("feasibility_relationships", {})
    if isinstance(relationships, dict):
        declared_parameter_names.update(
            item["output"]
            for item in relationships.values()
            if isinstance(item, dict) and isinstance(item.get("output"), str)
        )
    if set(bindings) != declared_parameter_names:
        raise _asset_error("LCC_ASSET_MISMATCH", "Logical parameter bindings do not exactly cover derived report parameters.", "load_parametric_catalog")
    for name, binding in bindings.items():
        if (
            not isinstance(name, str)
            or not isinstance(binding, dict)
            or set(binding) != {"logical_parameter", "units", "roles_by_topology", "template_parameter", "binding_status"}
            or binding.get("logical_parameter") != name
            or not isinstance(binding.get("units"), str)
            or not binding["units"]
            or binding.get("template_parameter") is not None
            or binding.get("binding_status") != "unreviewed"
            or not isinstance(binding.get("roles_by_topology"), dict)
            or set(binding["roles_by_topology"]) != set(_PARAMETRIC_NAMES.values())
        ):
            raise _asset_error("LCC_ASSET_MISMATCH", "A logical parameter binding is invalid or falsely authorizes a template write.", "load_parametric_catalog", parameter=name)
        for topology, roles in binding["roles_by_topology"].items():
            if not isinstance(roles, list) or not roles or len(roles) != len(set(roles)) or any(role not in topology_roles[topology] for role in roles):
                raise _asset_error("LCC_ASSET_MISMATCH", "A logical parameter binding references an undeclared template role.", "load_parametric_catalog", parameter=name, topology=topology)
    selectors: set[str] = set()
    for index, binding in enumerate(template_bindings):
        if (
            not isinstance(binding, dict)
            or set(binding) != {"logical_parameter", "role", "selector", "attribute", "units", "binding_status"}
            or not isinstance(binding.get("logical_parameter"), str)
            or binding["logical_parameter"] not in declared_parameter_names
            or not isinstance(binding.get("role"), str)
            or not isinstance(binding.get("selector"), str)
            or len(binding["selector"]) > 512
            or not binding["selector"].startswith("/project/definitions/")
            or ".." in binding["selector"]
            or "|" in binding["selector"]
            or binding.get("attribute") not in {"value", "text"}
            or not isinstance(binding.get("units"), str)
            or not binding["units"]
            or binding.get("binding_status") != "reviewed"
        ):
            raise _asset_error("LCC_ASSET_MISMATCH", "A reviewed template binding is invalid.", "load_parametric_catalog", index=index)
        valid_roles = set().union(*(topology_roles.values())) | {"main_control"}
        if binding["role"] not in valid_roles:
            raise _asset_error("LCC_ASSET_MISMATCH", "A reviewed template binding references an unknown role.", "load_parametric_catalog", index=index)
        if binding["selector"] in selectors:
            raise _asset_error("LCC_ASSET_MISMATCH", "Reviewed template binding selectors must be unique.", "load_parametric_catalog", index=index)
        selectors.add(binding["selector"])
        declared_units = bindings[binding["logical_parameter"]]["units"]
        if binding["units"] != declared_units:
            raise _asset_error("LCC_ASSET_MISMATCH", "A reviewed template binding has inconsistent units.", "load_parametric_catalog", index=index)
    return value


def _provenance_references(value: Any, identity: str) -> set[str]:
    references: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            references.update(_provenance_references(item, identity))
    elif isinstance(value, list):
        for item in value:
            references.update(_provenance_references(item, identity))
    elif isinstance(value, str) and value.startswith(f"{identity}:"):
        references.add(value.split(":", 1)[1])
    return references


def validate_parametric_provenance_asset(value: Any, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate provenance schema, hash, and catalog machine bindings."""

    catalog_value = validate_parametric_catalog_asset(load_parametric_catalog() if catalog is None else catalog)
    if not isinstance(value, dict) or set(value) != _PARAMETRIC_PROVENANCE_KEYS:
        raise _asset_error("LCC_ASSET_MISMATCH", "Parametric provenance schema fields are not exact.", "load_parametric_provenance")
    identity = catalog_value["provenance_identity"]
    entries = value.get("entries")
    if (
        value.get("schema_version") != 1
        or isinstance(value.get("schema_version"), bool)
        or value.get("identity") != identity
        or value.get("catalog_structure_contract_asset") != f"{identity}:catalog_structure_contract"
        or not isinstance(entries, dict)
        or not entries
    ):
        raise _asset_error("LCC_ASSET_MISMATCH", "Parametric provenance identity or structure is invalid.", "load_parametric_provenance")
    allowed_entry_keys = {"classification", "statement", "machine_contract", "limitation", "source_path"}
    for name, entry in entries.items():
        if (
            not isinstance(name, str)
            or not isinstance(entry, dict)
            or not {"classification", "machine_contract"} <= set(entry)
            or not set(entry) <= allowed_entry_keys
            or not isinstance(entry.get("classification"), str)
            or not isinstance(entry.get("machine_contract"), dict)
            or not entry["machine_contract"]
            or not any(isinstance(entry.get(field), str) and entry[field] for field in ("statement", "limitation", "source_path"))
        ):
            raise _asset_error("LCC_ASSET_MISMATCH", "A parametric provenance entry has invalid fields.", "load_parametric_provenance", entry=name)
    references = _provenance_references(catalog_value, identity)
    references.add("catalog_structure_contract")
    if set(entries) != references:
        raise _asset_error("LCC_ASSET_MISMATCH", "Parametric provenance entries do not exactly match catalog references.", "load_parametric_provenance")
    observed_hash = hashlib.sha256(canonical_json(value)).hexdigest()
    if observed_hash != catalog_value["provenance_sha256"]:
        raise _asset_error("LCC_ASSET_MISMATCH", "Parametric provenance does not match its catalog hash.", "load_parametric_provenance", expected=catalog_value["provenance_sha256"], observed=observed_hash)

    expected_machines: dict[str, Any] = {}
    expected_machines["catalog_structure_contract"] = {
        "required_relationships": {
            name: declaration["asset"]
            for name, declaration in catalog_value["feasibility_relationships"].items()
        },
        "required_return_contracts": dict(catalog_value["return_contract_assets"]),
    }
    expected_machines["rating_contract"] = {
        "parameters": {
            name: {"required": declaration["required"]}
            for name, declaration in catalog_value["rating_parameters"].items()
        }
    }
    positive_declaration = catalog_value["rating_parameters"]["rated_power_mw"]["constraints"][0]
    expected_machines["positive_finite"] = {
        "kind": positive_declaration["kind"],
        "value": positive_declaration["value"],
    }
    angle_declaration = catalog_value["engineering_parameters"]["min_firing_angle_deg"]["constraints"][0]
    expected_machines["angle_domain_deg"] = {
        key: angle_declaration[key] for key in ("kind", "minimum", "maximum")
    }
    power = catalog_value["derived_parameters"]["dc_power_mw"]
    expected_machines["dimensional_identity"] = {
        key: power[key] for key in ("formula", "dependencies", "compared_to")
    }
    expected_machines["floating_point_comparison"] = {
        "values": {
            "relative_tolerance": power["relative_tolerance"],
            "absolute_tolerance": power["absolute_tolerance"],
        }
    }
    relationships = catalog_value["feasibility_relationships"]
    expected_machines["strict_order"] = {
        key: relationships["firing_angle_interval"][key]
        for key in ("operator", "left", "right")
    }
    expected_machines["inverter_commutation_identity"] = {
        key: item
        for key, item in relationships["inverter_commutation_interval"].items()
        if key != "asset"
    }
    engineering = catalog_value["engineering_parameters"]
    expected_machines["legacy_catalog_defaults"] = {
        "values": {
            name: declaration["default"]
            for name, declaration in engineering.items()
            if declaration.get("default_asset") == f"{identity}:legacy_catalog_defaults"
        }
    }
    unit_parameters: dict[str, Any] = {}
    for name, declaration in engineering.items():
        if declaration.get("unit_asset") != f"{identity}:unit_conversions":
            continue
        multipliers = dict(declaration["unit_multipliers"])
        if "rad" in multipliers:
            multipliers["rad"] = {"expression": "180 / pi"}
        unit_parameters[name] = {
            "canonical_units": declaration["units"],
            "multipliers": multipliers,
        }
    expected_machines["unit_conversions"] = {"parameters": unit_parameters}
    for topology, asset in catalog_value["return_contract_assets"].items():
        entry_name = asset.split(":", 1)[1]
        requirement = catalog_value["return_asset_requirements"][topology]
        expected_machines[entry_name] = {
            key: requirement[key]
            for key in ("allowed", "required", "mode_requirements")
        }
    if set(expected_machines) != set(entries) or any(
        entries[name]["machine_contract"] != machine
        for name, machine in expected_machines.items()
    ):
        raise _asset_error("LCC_ASSET_MISMATCH", "Parametric provenance machine contracts do not exactly bind every catalog declaration.", "load_parametric_provenance")
    return value


def validate_parametric_blueprint_asset(value: Any, name: str, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate one immutable template-role topology asset and its catalog hash."""
    if name not in _PARAMETRIC_NAMES:
        raise _asset_error("LCC_BLUEPRINT_NOT_FOUND", f"Parametric blueprint '{name}' was not found.", "load_parametric_blueprint", blueprint=name)
    catalog_value = validate_parametric_catalog_asset(load_parametric_catalog() if catalog is None else catalog)
    if not isinstance(value, dict) or set(value) != _PARAMETRIC_BLUEPRINT_KEYS:
        raise _asset_error("LCC_BLUEPRINT_INVALID", "Parametric blueprint schema fields are not exact.", "load_parametric_blueprint", blueprint=name)
    topology = _PARAMETRIC_NAMES[name]
    contract = catalog_value["topology_contracts"].get(topology)
    if not isinstance(contract, dict):
        raise _asset_error("LCC_BLUEPRINT_INVALID", "Parametric topology contract is missing.", "load_parametric_blueprint", blueprint=name)
    expected_scalars = {
        "schema_version": 1,
        "name": name,
        "identity": name,
        "catalog_identity": catalog_value["identity"],
        "provenance_identity": catalog_value["provenance_identity"],
        "contract_kind": "template_role_topology",
        "topology": "lcc",
        "parameter_topology": topology,
        "poles": 1 if topology == "monopolar" else 2,
        "terminals": 2 if topology == "monopolar" else 3,
    }
    if any(type(value.get(field)) is not type(expected) or value.get(field) != expected for field, expected in expected_scalars.items()):
        raise _asset_error("LCC_BLUEPRINT_INVALID", "Parametric blueprint identity or topology is invalid.", "load_parametric_blueprint", blueprint=name)
    required_assets = _text_list(value.get("required_assets"), "required_assets")
    returns = _text_list(value.get("return_paths"), "return_paths")
    roles = _text_list(value.get("template_roles"), "template_roles")
    component_ids = _record_ids(value.get("components"), "logical_id", "components")
    net_ids = _record_ids(value.get("nets"), "logical_id", "nets")
    output_names = _record_ids(value.get("outputs"), "name", "outputs")
    expected_required = ["positive_pole", "earth_return"] if topology == "monopolar" else ["positive_pole", "negative_pole", "neutral_bus", "earth_return", "metallic_return"]
    exact_contract = (
        required_assets == expected_required
        and returns == ["earth_return", "metallic_return"]
        and roles == contract.get("template_roles")
        and component_ids == contract.get("component_roles")
        and net_ids == contract.get("net_ids")
        and output_names == contract.get("output_names")
        and set(contract.get("required_return_nets", ())) <= set(net_ids)
    )
    if not exact_contract:
        raise _asset_error("LCC_BLUEPRINT_INVALID", "Parametric blueprint roles, nets, outputs, or return evidence do not match the catalog.", "load_parametric_blueprint", blueprint=name)
    component_map = {item["logical_id"]: item for item in value["components"]}
    for component in value["components"]:
        kind = component.get("kind")
        required_keys = {"logical_id", "kind", "ports"}
        if kind == "template_role":
            required_keys |= {"template_role", "contract_identity", "discriminator"}
        if set(component) != required_keys or not isinstance(component.get("ports"), list) or not component["ports"]:
            raise _asset_error("LCC_BLUEPRINT_INVALID", "Parametric component role contract is invalid.", "load_parametric_blueprint", logical_id=component.get("logical_id"))
        if kind == "template_role" and component.get("template_role") not in roles:
            raise _asset_error("LCC_BLUEPRINT_INVALID", "A component has an undeclared template role.", "load_parametric_blueprint", logical_id=component.get("logical_id"))
        if kind not in {"template_role", "logical_junction", "logical_terminal"}:
            raise _asset_error("LCC_BLUEPRINT_INVALID", "A component kind is not authorized by the topology contract.", "load_parametric_blueprint", logical_id=component.get("logical_id"))
    for net in value["nets"]:
        if set(net) != {"logical_id", "kind", "endpoints", "evidence"} or net.get("evidence") != "template_connectivity_required" or not isinstance(net.get("endpoints"), list) or len(net["endpoints"]) < 2:
            raise _asset_error("LCC_BLUEPRINT_INVALID", "Parametric net evidence is invalid.", "load_parametric_blueprint", logical_id=net.get("logical_id"))
        for endpoint in net["endpoints"]:
            if not isinstance(endpoint, dict) or set(endpoint) != {"role", "port"} or endpoint.get("role") not in component_map or endpoint.get("port") not in component_map[endpoint["role"]]["ports"]:
                raise _asset_error("LCC_BLUEPRINT_INVALID", "Parametric net endpoint is not declared by a role contract.", "load_parametric_blueprint", logical_id=net.get("logical_id"))
        observed_endpoints = tuple(
            (endpoint["role"], endpoint["port"])
            for endpoint in net["endpoints"]
        )
        if observed_endpoints != _PARAMETRIC_NET_ENDPOINTS[topology][net["logical_id"]]:
            raise _asset_error("LCC_BLUEPRINT_INVALID", "Parametric net endpoints do not match the exact pole and return contract.", "load_parametric_blueprint", logical_id=net.get("logical_id"))
    for output in value["outputs"]:
        if set(output) != {"name", "role", "quantity", "pole", "terminal", "units"} or output.get("role") not in roles or any(not isinstance(output.get(field), str) or not output[field] for field in ("name", "role", "quantity", "pole", "terminal", "units")):
            raise _asset_error("LCC_BLUEPRINT_INVALID", "Parametric output contract is invalid.", "load_parametric_blueprint", output=output.get("name"))
    observed_hash = hashlib.sha256(canonical_json(value)).hexdigest()
    if observed_hash != catalog_value["blueprint_hashes"][name]:
        raise _asset_error("LCC_ASSET_MISMATCH", "Parametric blueprint does not match its catalog hash.", "load_parametric_blueprint", blueprint=name, expected=catalog_value["blueprint_hashes"][name], observed=observed_hash)
    return value


def load_parametric_blueprint(name: str) -> dict[str, Any]:
    """Load a hash-verified template-role topology contract without mutation."""
    if name not in _PARAMETRIC_NAMES:
        raise _asset_error("LCC_BLUEPRINT_NOT_FOUND", f"Parametric blueprint '{name}' was not found.", "load_parametric_blueprint", blueprint=name)
    resource = resources.files("pscad_mcp").joinpath("assets", "lcc", name, "blueprint.json")
    if not resource.is_file():
        raise _asset_error("LCC_BLUEPRINT_NOT_FOUND", f"Parametric blueprint '{name}' is not available.", "load_parametric_blueprint", blueprint=name)
    try:
        value = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _asset_error("LCC_ASSET_MISMATCH", "Parametric blueprint is not valid JSON.", "load_parametric_blueprint", blueprint=name) from error
    return validate_parametric_blueprint_asset(value, name)


def load_parametric_catalog() -> dict[str, Any]:
    resource = resources.files("pscad_mcp").joinpath("assets", "lcc", "lcc_parametric_catalog_v1.json")
    if not resource.is_file():
        raise _asset_error("LCC_ASSET_MISMATCH", "Parametric catalog is not available.", "load_parametric_catalog")
    try:
        value = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _asset_error("LCC_ASSET_MISMATCH", "Parametric catalog is not valid JSON.", "load_parametric_catalog") from error
    return validate_parametric_catalog_asset(value)


def load_parametric_provenance() -> dict[str, Any]:
    resource = resources.files("pscad_mcp").joinpath(
        "assets", "lcc", "lcc_bipole_parametric_v1", "provenance-parametric-v1.json"
    )
    if not resource.is_file():
        raise _asset_error("LCC_ASSET_MISMATCH", "Parametric provenance is not available.", "load_parametric_provenance")
    try:
        value = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _asset_error("LCC_ASSET_MISMATCH", "Parametric provenance is not valid JSON.", "load_parametric_provenance") from error
    return validate_parametric_provenance_asset(value)


def materialize_library(asset_set: LccAssetSet, workspace_root: str | Path) -> Path:
    """Atomically copy the verified companion library into a workspace."""

    workspace = Path(workspace_root).expanduser().resolve()
    library_relative = asset_set.companion_library
    expected = asset_set.hashes.get(library_relative)
    if expected is None:
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            "The companion library is not covered by the asset manifest.",
            "materialize_lcc_library",
            library=library_relative,
        )
    target = workspace / ".pscad-mcp" / "libraries" / Path(library_relative).name
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            f"Workspace library target '{target}' is not a regular file.",
            "materialize_lcc_library",
            path=str(target),
        )
    if target.is_file():
        observed = sha256_file(target)
        if observed == expected:
            return target
        raise _asset_error(
            "LCC_ASSET_MISMATCH",
            f"Workspace library '{target}' differs from the verified asset.",
            "materialize_lcc_library",
            path=str(target),
            expected=expected,
            observed=observed,
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(asset_set.library_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        if sha256_file(temporary) != expected:
            raise _asset_error(
                "LCC_ASSET_MISMATCH",
                "The materialized library failed hash verification.",
                "materialize_lcc_library",
                path=str(temporary),
            )
        try:
            # A hard-link install is exclusive on the same filesystem and
            # therefore does not replace a file created by a racing process.
            os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink() or not target.is_file():
                raise _asset_error(
                    "LCC_ASSET_MISMATCH",
                    f"Workspace library target '{target}' is not a regular file.",
                    "materialize_lcc_library",
                    path=str(target),
                )
            observed = sha256_file(target)
            if observed != expected:
                raise _asset_error(
                    "LCC_ASSET_MISMATCH",
                    f"Workspace library '{target}' differs from the verified asset.",
                    "materialize_lcc_library",
                    path=str(target),
                    expected=expected,
                    observed=observed,
                )
        except OSError as error:
            raise _asset_error(
                "LCC_ASSET_MISMATCH",
                "The verified library could not be installed without replacing a concurrent target.",
                "materialize_lcc_library",
                path=str(target),
            ) from error
        else:
            temporary.unlink()
            temporary = None
        return target
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
