"""Configuration-driven HVDC semantic profiles."""

from __future__ import annotations

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
    "vsc_2level_generic": {"required_assets": ["controller"], "mappings": []},
    "mmc_bipolar_generic": {"required_assets": ["pole"], "mappings": [{"canonical": "arm_current", "aliases": ["arm current", "Iarm"], "source_kinds": ["label"], "unit_family": "current", "direction": "measurement", "units": "kA"}, {"canonical": "submodule_capacitor_voltage", "aliases": ["SM capacitor voltage", "Vsm"], "source_kinds": ["label"], "unit_family": "voltage", "direction": "measurement", "units": "kV"}]},
    "hvdc_breaker_difforder": {
        "extends": "lcc_bipolar_generic",
        "required_assets": ["rectifier", "inverter", "pole", "breaker", "dc_line"],
        "mappings": [
            {"canonical": "dc_voltage", "aliases": ["UMC", "VDCL", "VDCp1", "VDCp2", "VDCIp1", "VDCIp2", "VDCRp1", "VDCRp2"], "source_kinds": ["voltmeter"], "unit_family": "voltage", "direction": "measurement", "units": None},
            {"canonical": "dc_current", "aliases": ["IMC"], "source_kinds": ["ammeter"], "unit_family": "current", "direction": "measurement", "units": "kA"},
            {"canonical": "current_order", "aliases": ["Rectifier Current Order"], "source_kinds": ["datalabel", "control"], "unit_family": "current", "direction": "command", "units": None},
            {"canonical": "breaker_command", "aliases": ["BrkOrd1"], "source_kinds": ["datalabel", "control"], "unit_family": "boolean", "direction": "command", "units": None},
            {"canonical": "breaker_status", "aliases": ["BRK1"], "source_kinds": ["datalabel", "measurement"], "unit_family": "boolean", "direction": "measurement", "units": None},
            {"canonical": "protection_trip", "aliases": ["protection trip", "diff trip"], "source_kinds": ["datalabel", "control"], "unit_family": "boolean", "direction": "measurement", "units": None},
        ],
    },
}


_PROFILE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SOURCE_KINDS = {"label", "datalabel", "text", "meter", "ammeter", "voltmeter", "multimeter", "graph", "measurement", "control", "parameter"}


def _invalid(message: str, name: str) -> BackendError:
    return BackendError("INVALID_ARGUMENT", message, "hvdc", "register_hvdc_profile", {"profile": name})


def _already_exists(name: str, destination: Path) -> BackendError:
    return BackendError(
        "HVDC_PROFILE_ALREADY_EXISTS",
        f"User HVDC profile '{name}' already exists and cannot be overwritten.",
        "hvdc",
        "register_hvdc_profile",
        {"profile": name, "path": str(destination)},
    )


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not _PROFILE_NAME.fullmatch(name):
        raise _invalid("Profile names must use lowercase letters, digits, underscores, or hyphens and start with a letter.", str(name))


def _validate_profile(profile: Any, name: str) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise _invalid("HVDC profile JSON must contain an object.", name)
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
    return profile


def _workspace_root(workspace_root: str | Path | None) -> Path | None:
    configured = workspace_root or os.getenv("PSCAD_MCP_WORKSPACE")
    return Path(configured).expanduser().resolve() if configured else None


def _profile_path(name: str, workspace_root: str | Path | None) -> Path | None:
    root = _workspace_root(workspace_root)
    return root / ".pscad-mcp" / "hvdc-profiles" / f"{name}.json" if root else None


def _read_profile(path: Path, name: str) -> dict[str, Any]:
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise _invalid(f"Unable to load profile '{name}': {error}", name) from error
    return _validate_profile(profile, name)


def _merge_profile(base: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    merged.update(profile)
    by_canonical = {item["canonical"]: item for item in base.get("mappings", [])}
    by_canonical.update({item["canonical"]: item for item in profile.get("mappings", [])})
    merged["mappings"] = list(by_canonical.values())
    merged["required_assets"] = sorted(set(base.get("required_assets", [])) | set(profile.get("required_assets", [])))
    return merged


def list_profiles(workspace_root: str | Path | None = None) -> list[str]:
    names = set(_BUILTIN_PROFILES)
    root = _workspace_root(workspace_root)
    directory = root / ".pscad-mcp" / "hvdc-profiles" if root else None
    if directory and directory.is_dir():
        names.update(path.stem for path in directory.glob("*.json") if _PROFILE_NAME.fullmatch(path.stem))
    return sorted(names)


def load_profile(name: str, mapping_file: str | None = None, *, workspace_root: str | Path | None = None) -> dict[str, Any]:
    if mapping_file:
        path = Path(mapping_file).expanduser().resolve()
        return _read_profile(path, name)
    if name in _BUILTIN_PROFILES:
        profile = dict(_BUILTIN_PROFILES[name])
    else:
        path = _profile_path(name, workspace_root)
        if path is None or not path.is_file():
            raise BackendError("HVDC_PROFILE_NOT_FOUND", f"HVDC profile '{name}' was not found.", "hvdc", "load_profile", {"profile": name, "available": list_profiles(workspace_root)})
        profile = dict(_read_profile(path, name))
    parent = profile.get("extends")
    if parent:
        base = load_profile(parent, workspace_root=workspace_root)
        return _merge_profile(base, profile)
    return profile


def register_profile(name: str, mapping_file: str, *, workspace_root: str | Path | None) -> dict[str, Any]:
    _validate_name(name)
    if name in _BUILTIN_PROFILES:
        raise _invalid(f"Built-in HVDC profile '{name}' cannot be overwritten.", name)
    root = _workspace_root(workspace_root)
    if root is None:
        raise _invalid("A configured workspace is required for user-scoped profile registration.", name)
    destination = _profile_path(name, root)
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
