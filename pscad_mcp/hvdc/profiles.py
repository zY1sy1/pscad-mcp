"""Configuration-driven HVDC semantic profiles."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from ..core.backend.base import BackendError


_BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "lcc_bipolar_generic": {
        "required_assets": ["rectifier", "inverter", "pole"],
        "mappings": [
            {"canonical": "dc_voltage", "aliases": ["Vdc", "VDC", "DC VOLTAGE"], "source_kinds": ["label", "datalabel", "meter"], "unit_family": "voltage", "direction": "measurement", "units": "kV"},
            {"canonical": "dc_current", "aliases": ["Idc", "IDC", "DC CURRENT"], "source_kinds": ["label", "datalabel", "meter"], "unit_family": "current", "direction": "measurement", "units": "kA"},
            {"canonical": "dc_power", "aliases": ["Pdc", "PDC", "DC POWER"], "source_kinds": ["label", "datalabel"], "unit_family": "power", "direction": "measurement", "units": "MW"},
            {"canonical": "ac_voltage_rms", "aliases": ["Vac rms", "AC VOLTAGE RMS"], "source_kinds": ["label", "meter"], "unit_family": "voltage", "direction": "measurement", "units": "kV"},
            {"canonical": "ac_current_rms", "aliases": ["Iac rms", "AC CURRENT RMS"], "source_kinds": ["label", "meter"], "unit_family": "current", "direction": "measurement", "units": "kA"},
            {"canonical": "active_power", "aliases": ["P", "Pactive", "ACTIVE POWER"], "source_kinds": ["label", "meter"], "unit_family": "power", "direction": "measurement", "units": "MW"},
            {"canonical": "reactive_power", "aliases": ["Q", "Qreactive", "REACTIVE POWER"], "source_kinds": ["label", "meter"], "unit_family": "power", "direction": "measurement", "units": "MVAr"},
            {"canonical": "firing_angle", "aliases": ["alpha", "firing angle"], "source_kinds": ["label", "control"], "unit_family": "angle", "direction": "measurement", "units": "deg"},
            {"canonical": "extinction_angle", "aliases": ["gamma", "extinction angle"], "source_kinds": ["label", "control"], "unit_family": "angle", "direction": "measurement", "units": "deg"},
            {"canonical": "commutation_overlap", "aliases": ["mu", "overlap angle", "commutation overlap"], "source_kinds": ["label", "control"], "unit_family": "angle", "direction": "measurement", "units": "deg"},
            {"canonical": "power_order", "aliases": ["power order", "P order"], "source_kinds": ["label", "control"], "unit_family": "power", "direction": "command", "units": "MW"},
            {"canonical": "current_order", "aliases": ["current order", "I order"], "source_kinds": ["label", "control"], "unit_family": "current", "direction": "command", "units": "kA"},
            {"canonical": "voltage_order", "aliases": ["voltage order", "V order"], "source_kinds": ["label", "control"], "unit_family": "voltage", "direction": "command", "units": "kV"},
            {"canonical": "dc_voltage_order", "aliases": ["dc voltage order", "Vdc order"], "source_kinds": ["label", "control"], "unit_family": "voltage", "direction": "command", "units": "kV"},
            {"canonical": "breaker_command", "aliases": ["breaker command", "trip command", "fault command"], "source_kinds": ["label", "control"], "unit_family": "boolean", "direction": "command", "units": None},
            {"canonical": "breaker_status", "aliases": ["breaker status", "breaker state"], "source_kinds": ["label", "measurement"], "unit_family": "boolean", "direction": "measurement", "units": None},
            {"canonical": "protection_trip", "aliases": ["protection trip", "diff trip", "trip"], "source_kinds": ["label", "control"], "unit_family": "boolean", "direction": "measurement", "units": None},
            {"canonical": "fault_command", "aliases": ["fault command", "fault"], "source_kinds": ["label", "control"], "unit_family": "boolean", "direction": "command", "units": None},
            {"canonical": "pll_angle", "aliases": ["pll angle", "theta pll"], "source_kinds": ["label", "control"], "unit_family": "angle", "direction": "measurement", "units": "deg"},
            {"canonical": "pll_frequency", "aliases": ["pll frequency", "f pll"], "source_kinds": ["label", "control"], "unit_family": "frequency", "direction": "measurement", "units": "Hz"},
            {"canonical": "dq_current", "aliases": ["dq current", "id iq"], "source_kinds": ["label", "control"], "unit_family": "current", "direction": "measurement", "units": "kA"},
            {"canonical": "dq_voltage", "aliases": ["dq voltage", "vd vq"], "source_kinds": ["label", "control"], "unit_family": "voltage", "direction": "measurement", "units": "kV"},
        ],
    },
    "vsc_2level_generic": {
        "profile_version": 2,
        "required_assets": ["controller"],
        "mappings": [
            {"canonical": "dc_voltage", "aliases": ["Vdc", "DC voltage"], "source_kinds": ["label", "meter"], "unit_family": "voltage", "direction": "measurement", "units": "kV"},
            {"canonical": "dc_current", "aliases": ["Idc", "DC current"], "source_kinds": ["label", "meter"], "unit_family": "current", "direction": "measurement", "units": "kA"},
            {"canonical": "active_power", "aliases": ["P", "Pactive", "active power"], "source_kinds": ["label", "meter"], "unit_family": "power", "direction": "measurement", "units": "MW"},
            {"canonical": "reactive_power", "aliases": ["Q", "Qreactive", "reactive power"], "source_kinds": ["label", "meter"], "unit_family": "power", "direction": "measurement", "units": "MVAr"},
            {"canonical": "pll_frequency", "aliases": ["PLL frequency", "f pll"], "source_kinds": ["label", "meter"], "unit_family": "frequency", "direction": "measurement", "units": "Hz"},
            {"canonical": "dq_current", "aliases": ["dq current", "Id/Iq"], "source_kinds": ["label", "meter"], "unit_family": "current", "direction": "measurement", "units": "kA"},
            {"canonical": "dq_voltage", "aliases": ["dq voltage", "Vd/Vq"], "source_kinds": ["label", "meter"], "unit_family": "voltage", "direction": "measurement", "units": "kV"},
        ],
        "project_fingerprints": [],
        "command_bindings": [],
        "result_channels": [
            {"canonical": "dc_voltage", "path": "dc_voltage", "units": "kV"},
            {"canonical": "dc_current", "path": "dc_current", "units": "kA"},
            {"canonical": "active_power", "path": "active_power", "units": "MW"},
            {"canonical": "reactive_power", "path": "reactive_power", "units": "MVAr"},
            {"canonical": "pll_frequency", "path": "pll_frequency", "units": "Hz"},
            {"canonical": "dq_current", "path": "dq_current", "units": "kA"},
            {"canonical": "dq_voltage", "path": "dq_voltage", "units": "kV"},
        ],
        "metric_roles": {
            "dc_voltage": "dc_voltage",
            "dc_current": "dc_current",
            "active_power": "active_power",
            "reactive_power": "reactive_power",
            "pll_frequency": "pll_frequency",
            "dq_current": "dq_current",
            "dq_voltage": "dq_voltage",
        },
        "sequences": [],
    },
    "mmc_bipolar_generic": {
        "profile_version": 2,
        "required_assets": ["pole"],
        "mappings": [
            {"canonical": "arm_current", "aliases": ["arm current", "Iarm"], "source_kinds": ["label", "meter"], "unit_family": "current", "direction": "measurement", "units": "kA"},
            {"canonical": "submodule_capacitor_voltage", "aliases": ["SM capacitor voltage", "Vsm"], "source_kinds": ["label", "meter"], "unit_family": "voltage", "direction": "measurement", "units": "kV"},
            {"canonical": "circulating_current", "aliases": ["circulating current", "Icir"], "source_kinds": ["label", "meter"], "unit_family": "current", "direction": "measurement", "units": "kA"},
        ],
        "project_fingerprints": [],
        "command_bindings": [],
        "result_channels": [
            {"canonical": "arm_current", "path": "arm_current", "units": "kA"},
            {"canonical": "submodule_capacitor_voltage", "path": "submodule_capacitor_voltage", "units": "kV"},
            {"canonical": "circulating_current", "path": "circulating_current", "units": "kA"},
        ],
        "metric_roles": {
            "arm_current": "arm_current",
            "submodule_capacitor_voltage": "submodule_capacitor_voltage",
            "circulating_current": "circulating_current",
        },
        "sequences": [],
    },
    "hvdc_breaker_difforder": {
        "extends": "lcc_bipolar_generic",
        "profile_version": 2,
        "required_assets": ["rectifier", "inverter", "pole", "breaker", "dc_line"],
        "mappings": [
            {"canonical": "dc_voltage", "aliases": ["UMC", "VDCL", "VDCp1", "VDCp2", "VDCIp1", "VDCIp2", "VDCRp1", "VDCRp2"], "source_kinds": ["voltmeter"], "unit_family": "voltage", "direction": "measurement", "units": None},
            {"canonical": "dc_current", "aliases": ["IMC"], "source_kinds": ["ammeter"], "unit_family": "current", "direction": "measurement", "units": "kA"},
            {"canonical": "current_order", "aliases": ["Rectifier Current Order"], "source_kinds": ["datalabel", "control"], "unit_family": "current", "direction": "command", "units": None},
            {"canonical": "breaker_command", "aliases": ["BrkOrd1"], "source_kinds": ["datalabel", "control"], "unit_family": "boolean", "direction": "command", "units": None},
            {"canonical": "breaker_status", "aliases": ["BRK1"], "source_kinds": ["datalabel", "measurement"], "unit_family": "boolean", "direction": "measurement", "units": None},
            {"canonical": "protection_trip", "aliases": ["protection trip", "diff trip"], "source_kinds": ["datalabel", "control"], "unit_family": "boolean", "direction": "measurement", "units": None},
        ],
        "project_fingerprints": [],
        "command_bindings": [],
        "result_channels": [
            {"canonical": "dc_voltage_breaker", "path": "loadbreaker_3/UMC", "call_id": 90, "units": "kV", "location": "breaker"},
            {"canonical": "dc_current_breaker", "path": "loadbreaker_3/IMC", "call_id": 83, "units": "kA", "location": "breaker"},
            {"canonical": "breaker_command_observed", "path": "loadbreaker_3/BrkOrd1", "call_id": 78, "units": None, "location": "breaker"},
            {"canonical": "dc_voltage_rectifier_pole1", "path": "Main/VDCRp1", "call_id": 1, "units": "pu", "location": "rectifier_pole1"},
            {"canonical": "dc_voltage_inverter_pole1", "path": "Main/VDCIp1", "call_id": 3, "units": "pu", "location": "inverter_pole1"},
            {"canonical": "dc_voltage_rectifier_pole2", "path": "Main/VDCRp2", "call_id": 6, "units": "pu", "location": "rectifier_pole2"},
            {"canonical": "dc_voltage_inverter_pole2", "path": "Main/VDCIp2", "call_id": 9, "units": "pu", "location": "inverter_pole2"},
        ],
        "metric_roles": {},
        "sequences": [],
    },
}


_PROFILE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SOURCE_KINDS = {"label", "datalabel", "text", "meter", "ammeter", "voltmeter", "multimeter", "graph", "measurement", "control", "parameter"}


def _invalid(message: str, name: str, operation: str = "register_hvdc_profile") -> BackendError:
    return BackendError("INVALID_ARGUMENT", message, "hvdc", operation, {"profile": name})


def _already_exists(name: str, destination: Path) -> BackendError:
    return BackendError(
        "HVDC_PROFILE_ALREADY_EXISTS",
        f"User HVDC profile '{name}' already exists and cannot be overwritten.",
        "hvdc",
        "register_hvdc_profile",
        {"profile": name, "path": str(destination)},
    )


def _validate_name(name: str, operation: str = "register_hvdc_profile") -> None:
    if not isinstance(name, str) or not _PROFILE_NAME.fullmatch(name):
        raise _invalid("Profile names must use lowercase letters, digits, underscores, or hyphens and start with a letter.", str(name), operation)


def _validate_unique_canonicals(items: Any, field: str, name: str) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise _invalid(f"'{field}' must be a list.", name)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise _invalid(f"{field}[{index}] must be an object.", name)
        item = dict(raw)
        canonical = item.get("canonical")
        if not isinstance(canonical, str) or not canonical.strip():
            raise _invalid(f"{field}[{index}] requires a non-empty canonical.", name)
        if canonical in seen:
            raise _invalid(f"Canonical '{canonical}' is duplicated in '{field}'.", name)
        seen.add(canonical)
        result.append(item)
    return result


def _validate_profile_v2(profile: dict[str, Any], name: str) -> None:
    fingerprints = profile.get("project_fingerprints", [])
    if not isinstance(fingerprints, list) or any(not isinstance(item, dict) for item in fingerprints):
        raise _invalid("'project_fingerprints' must be a list of objects.", name)
    for index, fingerprint in enumerate(fingerprints):
        for field in ("project_stem", "pscad_version"):
            value = fingerprint.get(field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise _invalid(
                    f"project_fingerprints[{index}].{field} must be a non-empty string.",
                    name,
                )
        definitions = fingerprint.get("definitions")
        if definitions is not None and (
            not isinstance(definitions, list)
            or any(not isinstance(item, str) or not item.strip() for item in definitions)
        ):
            raise _invalid(
                f"project_fingerprints[{index}].definitions must be a list of non-empty strings.",
                name,
            )
    commands = _validate_unique_canonicals(profile.get("command_bindings", []), "command_bindings", name)
    results = _validate_unique_canonicals(profile.get("result_channels", []), "result_channels", name)
    for item in commands:
        component = item.get("component")
        if not isinstance(component, dict) or not component:
            raise _invalid(f"Command '{item['canonical']}' requires a component selector.", name)
        selector_fields = {"component_id", "canvas", "definition"}
        if not selector_fields & component.keys():
            raise _invalid(f"Command '{item['canonical']}' requires a component selector.", name)
        for field in selector_fields & component.keys():
            value = component[field]
            if not isinstance(value, str) or not value.strip():
                raise _invalid(
                    f"Command '{item['canonical']}' has invalid component.{field}.",
                    name,
                )
        if not isinstance(item.get("parameter_name"), str) or not item["parameter_name"].strip():
            raise _invalid(f"Command '{item['canonical']}' requires parameter_name.", name)
        if not isinstance(item.get("allowed_values"), list) or not item["allowed_values"]:
            raise _invalid(f"Command '{item['canonical']}' requires allowed_values.", name)
        if item.get("semantics") not in {"active_high", "active_low", "open", "close", "enable", "disable"}:
            raise _invalid(f"Command '{item['canonical']}' has invalid semantics.", name)
        if "read_back" in item and not isinstance(item["read_back"], bool):
            raise _invalid(f"Command '{item['canonical']}' has invalid read_back.", name)
    for item in results:
        if not isinstance(item.get("path"), str) or not item["path"].strip():
            raise _invalid(f"Result '{item['canonical']}' requires path.", name)
        if item.get("call_id") is not None and (
            isinstance(item["call_id"], bool)
            or not isinstance(item["call_id"], int)
            or item["call_id"] < 1
        ):
            raise _invalid(f"Result '{item['canonical']}' has invalid call_id.", name)
        if item.get("units") is not None and not isinstance(item["units"], str):
            raise _invalid(f"Result '{item['canonical']}' has invalid units.", name)
        if item.get("location") is not None and (
            not isinstance(item["location"], str) or not item["location"].strip()
        ):
            raise _invalid(f"Result '{item['canonical']}' has invalid location.", name)
    roles = profile.get("metric_roles", {})
    if not isinstance(roles, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in roles.items()
    ):
        raise _invalid("'metric_roles' must map strings to strings.", name)
    sequences = profile.get("sequences", [])
    if not isinstance(sequences, list) or any(not isinstance(item, dict) for item in sequences):
        raise _invalid("'sequences' must be a list of objects.", name)
    if any(not item for item in sequences):
        index = next(index for index, item in enumerate(sequences) if not item)
        raise _invalid(f"sequences[{index}] must not be empty.", name)


def _validate_profile(profile: Any, name: str) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise _invalid("HVDC profile JSON must contain an object.", name)
    profile_version = profile.get("profile_version", 1)
    if isinstance(profile_version, bool) or not isinstance(profile_version, int) or profile_version not in {1, 2}:
        raise _invalid("'profile_version' must be integer 1 or 2.", name)
    if "required_assets" not in profile or "mappings" not in profile:
        raise _invalid("HVDC profiles require 'required_assets' and 'mappings' sections.", name)
    required_assets = profile.get("required_assets", [])
    mappings = profile.get("mappings", [])
    if not isinstance(required_assets, list) or any(not isinstance(item, str) or not item.strip() for item in required_assets):
        raise _invalid("'required_assets' must be a list of non-empty strings.", name)
    if not isinstance(mappings, list):
        raise _invalid("'mappings' must be a list.", name)
    canonicals: set[str] = set()
    for index, mapping in enumerate(mappings):
        if not isinstance(mapping, dict):
            raise _invalid(f"Mapping {index} must be an object.", name)
        canonical = mapping.get("canonical")
        aliases = mapping.get("aliases")
        source_kinds = mapping.get("source_kinds")
        if not isinstance(canonical, str) or not canonical.strip():
            raise _invalid(f"Mapping {index} requires a non-empty 'canonical'.", name)
        if canonical in canonicals:
            raise _invalid(f"Canonical mapping '{canonical}' is duplicated.", name)
        canonicals.add(canonical)
        if not isinstance(aliases, list) or not aliases or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
            raise _invalid(f"Mapping '{canonical}' requires non-empty string aliases.", name)
        if not isinstance(source_kinds, list) or not source_kinds or any(kind not in _SOURCE_KINDS for kind in source_kinds):
            raise _invalid(f"Mapping '{canonical}' has invalid 'source_kinds'.", name)
        direction = mapping.get("direction", "measurement")
        if direction not in {"measurement", "command"}:
            raise _invalid(f"Mapping '{canonical}' has invalid direction '{direction}'.", name)
        if mapping.get("units") is not None and not isinstance(mapping.get("units"), str):
            raise _invalid(f"Mapping '{canonical}' has invalid units.", name)
        if mapping.get("unit_family") is not None and not isinstance(mapping.get("unit_family"), str):
            raise _invalid(f"Mapping '{canonical}' has invalid unit_family.", name)
    parent = profile.get("extends")
    if parent is not None and (not isinstance(parent, str) or not parent.strip() or parent == name):
        raise _invalid("'extends' must name a different profile.", name)
    if profile_version == 2:
        _validate_profile_v2(profile, name)
    return profile


def _workspace_root(workspace_root: str | Path | None) -> Path | None:
    configured = workspace_root or os.getenv("PSCAD_MCP_WORKSPACE")
    return Path(configured).expanduser().resolve() if configured else None


def _profile_directory(workspace_root: str | Path | None, operation: str) -> Path | None:
    root = _workspace_root(workspace_root)
    if root is None:
        return None
    directory = (root / ".pscad-mcp" / "hvdc-profiles").resolve()
    if directory != root and root not in directory.parents:
        raise _invalid("HVDC profile directory escapes the configured workspace.", "", operation)
    return directory


def _profile_path(name: str, workspace_root: str | Path | None, operation: str) -> Path | None:
    _validate_name(name, operation)
    directory = _profile_directory(workspace_root, operation)
    if directory is None:
        return None
    path = (directory / f"{name}.json").resolve()
    if path.parent != directory:
        raise _invalid("HVDC profile path escapes the configured profile directory.", name, operation)
    return path


def _read_profile(path: Path, name: str, operation: str = "register_hvdc_profile") -> dict[str, Any]:
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise _invalid(f"Unable to load profile '{name}': {error}", name, operation) from error
    return _validate_profile(profile, name)


def _merge_canonical_items(base_items: Any, profile_items: Any) -> Any:
    if not isinstance(base_items, list):
        return deepcopy(base_items)
    if not isinstance(profile_items, list):
        return deepcopy(profile_items)
    merged = [deepcopy(item) for item in base_items]
    indexes: dict[str, int] = {}
    for index, item in enumerate(merged):
        canonical = item.get("canonical") if isinstance(item, dict) else None
        if isinstance(canonical, str) and canonical not in indexes:
            indexes[canonical] = index
    for raw in profile_items:
        item = deepcopy(raw)
        canonical = item.get("canonical") if isinstance(item, dict) else None
        if isinstance(canonical, str) and canonical in indexes:
            merged[indexes[canonical]] = item
        else:
            if isinstance(canonical, str):
                indexes[canonical] = len(merged)
            merged.append(item)
    return merged


def _merge_profile(base: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    merged.update(deepcopy(profile))
    by_canonical = {item["canonical"]: deepcopy(item) for item in base.get("mappings", [])}
    by_canonical.update({item["canonical"]: deepcopy(item) for item in profile.get("mappings", [])})
    merged["mappings"] = list(by_canonical.values())
    merged["required_assets"] = sorted(set(base.get("required_assets", [])) | set(profile.get("required_assets", [])))
    if profile.get("profile_version") == 2:
        for field in ("command_bindings", "result_channels"):
            merged[field] = _merge_canonical_items(base.get(field, []), profile.get(field, []))
        base_roles = base.get("metric_roles", {})
        profile_roles = profile.get("metric_roles", {})
        if not isinstance(base_roles, dict):
            merged["metric_roles"] = deepcopy(base_roles)
        elif not isinstance(profile_roles, dict):
            merged["metric_roles"] = deepcopy(profile_roles)
        else:
            merged["metric_roles"] = {**deepcopy(base_roles), **deepcopy(profile_roles)}
    return merged


def list_profiles(workspace_root: str | Path | None = None) -> list[str]:
    names = set(_BUILTIN_PROFILES)
    directory = _profile_directory(workspace_root, "list_hvdc_profiles")
    if directory and directory.is_dir():
        names.update(path.stem for path in directory.glob("*.json") if _PROFILE_NAME.fullmatch(path.stem))
    return sorted(names)


def load_profile(name: str, mapping_file: str | None = None, *, workspace_root: str | Path | None = None) -> dict[str, Any]:
    _validate_name(name, "load_profile")
    if mapping_file:
        path = Path(mapping_file).expanduser().resolve()
        profile = deepcopy(_read_profile(path, name, "load_profile"))
    elif name in _BUILTIN_PROFILES:
        profile = deepcopy(_BUILTIN_PROFILES[name])
    else:
        path = _profile_path(name, workspace_root, "load_profile")
        if path is None or not path.is_file():
            raise BackendError("HVDC_PROFILE_NOT_FOUND", f"HVDC profile '{name}' was not found.", "hvdc", "load_profile", {"profile": name, "available": list_profiles(workspace_root)})
        profile = deepcopy(_read_profile(path, name, "load_profile"))
    parent = profile.get("extends")
    if parent:
        base = load_profile(parent, workspace_root=workspace_root)
        child_version = profile.get("profile_version", 1)
        parent_version = base.get("profile_version", 1)
        if child_version == 1 and parent_version == 2:
            raise _invalid(
                "A profile_version 1 child cannot extend a profile_version 2 parent.",
                name,
                "load_profile",
            )
        merged = _merge_profile(base, profile)
        _validate_profile(merged, name)
        return deepcopy(merged)
    return deepcopy(profile)


def register_profile(name: str, mapping_file: str, *, workspace_root: str | Path | None) -> dict[str, Any]:
    _validate_name(name)
    if name in _BUILTIN_PROFILES:
        raise _invalid(f"Built-in HVDC profile '{name}' cannot be overwritten.", name)
    root = _workspace_root(workspace_root)
    if root is None:
        raise _invalid("A configured workspace is required for user-scoped profile registration.", name)
    destination = _profile_path(name, root, "register_hvdc_profile")
    assert destination is not None
    destination = destination.resolve()
    if destination != root and root not in destination.parents:
        raise _invalid("User profile destination escapes the configured workspace.", name)
    if destination.exists():
        raise _already_exists(name, destination)
    profile = load_profile(name, mapping_file)
    parent = profile.get("extends")
    if parent:
        load_profile(parent, workspace_root=root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(profile, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent, prefix=f".{name}-", suffix=".tmp", delete=False) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        try:
            os.link(temporary_name, destination)
        except FileExistsError as error:
            raise _already_exists(name, destination) from error
    finally:
        if temporary_name and Path(temporary_name).exists():
            Path(temporary_name).unlink()
    return {"profile": name, "registered": True, "mapping_file": str(destination)}
