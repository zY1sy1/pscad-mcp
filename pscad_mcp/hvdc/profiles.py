"""Configuration-driven HVDC semantic profiles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.backend.base import BackendError


_BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "lcc_bipolar_generic": {
        "required_assets": ["rectifier", "inverter", "pole"],
        "mappings": [
            {"canonical": "dc_voltage", "aliases": ["Vdc", "VDC", "DC VOLTAGE"], "source_kinds": ["label", "datalabel"], "unit_family": "voltage", "direction": "measurement", "units": "kV"},
            {"canonical": "dc_current", "aliases": ["Idc", "IDC", "DC CURRENT"], "source_kinds": ["label", "datalabel"], "unit_family": "current", "direction": "measurement", "units": "kA"},
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
    "hvdc_breaker_difforder": {"extends": "lcc_bipolar_generic", "required_assets": ["rectifier", "inverter", "pole", "breaker", "dc_line"]},
}


def list_profiles() -> list[str]:
    return sorted(_BUILTIN_PROFILES)


def load_profile(name: str, mapping_file: str | None = None) -> dict[str, Any]:
    if mapping_file:
        path = Path(mapping_file).expanduser().resolve()
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BackendError("HVDC_PROFILE_NOT_FOUND", f"Unable to load profile '{name}': {error}", "hvdc", "load_profile", {"profile": name}) from error
    try:
        profile = dict(_BUILTIN_PROFILES[name])
    except KeyError as error:
        raise BackendError("HVDC_PROFILE_NOT_FOUND", f"HVDC profile '{name}' was not found.", "hvdc", "load_profile", {"profile": name, "available": list_profiles()}) from error
    parent = profile.get("extends")
    if parent:
        base = load_profile(parent)
        merged = dict(base)
        merged.update(profile)
        merged["mappings"] = list(base.get("mappings", [])) + list(profile.get("mappings", []))
        merged["required_assets"] = sorted(set(base.get("required_assets", [])) | set(profile.get("required_assets", [])))
        return merged
    return profile


def register_profile(name: str, mapping_file: str) -> dict[str, Any]:
    profile = load_profile(name, mapping_file)
    _BUILTIN_PROFILES[name] = profile
    return {"profile": name, "registered": True, "mapping_file": str(Path(mapping_file).resolve())}
