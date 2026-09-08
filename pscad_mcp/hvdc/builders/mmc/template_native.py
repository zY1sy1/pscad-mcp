"""Safe materialization of scenarios supported by an audited MMC template.

PSCAD 4.6.2's legacy Automation Library cannot schedule arbitrary writes from
an EMTDC simulation clock.  Some official templates contain their own
``time-sig``/``tfaultn`` logic, however.  This module prepares a *derived
scenario copy* by binding those controls before the project is loaded.  It
never edits the audited source and does not claim a live scheduler capability.
"""

from __future__ import annotations

import hashlib
import itertools
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ....core.backend.base import BackendError
from .acceptance import evaluate_dc_fault_blocking
from .models import SubmoduleTopology
from .template_audit import _components, _parameters, _template_native_controls

_CONTROL_NAMES = {
    "fault time": "Fault Time",
    "ac fault type": "AC Fault type",
    "dblk t1": "Dblk T1",
    "dblk t2": "Dblk T2",
    "ccsc enable": "CCSC Enable",
}


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", "materialize_mmc_template_scenario", details)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _value(value: Any, field: str) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise _error(
                "MMC_TEMPLATE_NATIVE_BINDING_INVALID",
                "Native control values must be finite.",
                field=field,
                value=value,
            )
        return format(value, ".15g")
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise _error(
        "MMC_TEMPLATE_NATIVE_BINDING_INVALID",
        "Native control values must be scalar values.",
        field=field,
        value=value,
    )


def inspect_template_native_controls(project: str | Path) -> dict[str, object]:
    """Return the static, read-only native-control contract for a PSCX file."""

    raw_path = Path(project).expanduser()
    if raw_path.is_symlink():
        raise _error(
            "MMC_TEMPLATE_NOT_FOUND",
            "The native-control source project is not a regular file.",
            project=str(raw_path),
        )
    path = raw_path.resolve()
    if path.is_symlink() or not path.is_file():
        raise _error(
            "MMC_TEMPLATE_NOT_FOUND",
            "The native-control source project is not a regular file.",
            project=str(path),
        )
    try:
        root = ET.parse(path).getroot()
        result = _template_native_controls(root)
    except (OSError, ET.ParseError) as error:
        raise _error(
            "MMC_TEMPLATE_INVALID",
            "The native-control source project could not be parsed.",
            project=str(path),
        ) from error
    return dict(result)


def _named_components(root: ET.Element) -> dict[str, list[ET.Element]]:
    result: dict[str, list[ET.Element]] = {}
    for component in _components(root):
        values = dict(_parameters(component))
        name = values.get("Name", "").strip()
        if name:
            result.setdefault(name.casefold(), []).append(component)
    return result


def _set_named_control(
    root: ET.Element,
    name: str,
    value: str,
    bindings: list[dict[str, str]],
) -> None:
    matches = _named_components(root).get(name.casefold(), [])
    if len(matches) != 1:
        raise _error(
            "MMC_TEMPLATE_NATIVE_BINDING_MISSING"
            if not matches
            else "MMC_TEMPLATE_NATIVE_BINDING_AMBIGUOUS",
            "The requested native control is not uniquely declared in the template.",
            control=name,
            matches=len(matches),
        )
    component = matches[0]
    owner = (component.attrib.get("id") or "").strip()
    params = [
        item
        for item in component.iter()
        if item.tag.rsplit("}", 1)[-1].casefold() == "param"
        and item.attrib.get("name") == "Value"
    ]
    if len(params) != 1:
        raise _error(
            "MMC_TEMPLATE_NATIVE_BINDING_MISSING",
            "The native control has no unique Value parameter.",
            control=name,
            owner=owner,
        )
    params[0].set("value", value)
    bindings.append(
        {"owner": owner, "name": name, "parameter": "Value", "value": value}
    )


def _seconds(value: Any, field: str, *, positive: bool = False) -> str:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
        or positive and value == 0
    ):
        raise _error(
            "MMC_TEMPLATE_NATIVE_BINDING_INVALID",
            "Fault times must be finite and nonnegative; duration must be positive.",
            field=field,
        )
    return _value(value, field)


def _bind_fault_timer(
    root: ET.Element,
    duration: str | None,
    bindings: list[dict[str, str]],
) -> None:
    main_definitions = [
        node for node in root.iter()
        if node.tag.rsplit("}", 1)[-1].casefold() == "definition"
        and (node.get("name") or "").rsplit(":", 1)[-1] == "Main"
    ]
    matches = [
        component for main in main_definitions for component in _components(main)
        if (component.get("defn") or component.get("definition")) == "master:tfaultn"
        and dict(_parameters(component)).get("TF") == "Flt_time"
    ]
    if len(main_definitions) != 1 or len(matches) != 1:
        raise _error(
            "MMC_TEMPLATE_NATIVE_BINDING_AMBIGUOUS"
            if len(main_definitions) > 1 or len(matches) > 1
            else "MMC_TEMPLATE_NATIVE_BINDING_MISSING",
            "The Main canvas must contain one fault timer driven by Flt_time.",
            matches=len(matches),
        )
    component = matches[0]
    owner = (component.attrib.get("id") or "").strip()
    params = [
        item
        for item in component.iter()
        if item.tag.rsplit("}", 1)[-1].casefold() == "param"
        and item.attrib.get("name") == "DF"
    ]
    if not owner or len(params) != 1:
        raise _error(
            "MMC_TEMPLATE_NATIVE_BINDING_MISSING",
            "The active fault timer has no unique duration parameter or owner.",
            parameter="DF",
            owner=owner,
        )
    if duration is not None:
        params[0].set("value", duration)
        bindings.append(
            {"owner": owner, "name": "Fault Duration", "parameter": "DF", "value": duration}
        )


def materialize_template_native_scenario(
    source: str | Path,
    destination: str | Path,
    *,
    controls: Mapping[str, Any] | None = None,
    fault_time_s: float | None = None,
    fault_duration_s: float | None = None,
    ac_fault_type: int | None = None,
    dc_fault_time_s: float | None = None,
) -> dict[str, object]:
    """Create a scenario copy with pre-programmed template-native controls."""

    raw_source = Path(source).expanduser()
    raw_destination = Path(destination).expanduser()
    if raw_source.is_symlink() or raw_destination.is_symlink():
        raise _error(
            "MMC_TEMPLATE_NOT_FOUND" if raw_source.is_symlink() else "MMC_BUILD_CONFLICT",
            "Native scenario source and destination must be regular paths.",
            source=str(raw_source),
            destination=str(raw_destination),
        )
    source_path = raw_source.resolve()
    destination_path = raw_destination.resolve()
    if source_path == destination_path:
        raise _error(
            "MMC_BUILD_CONFLICT",
            "A native scenario must be written to a distinct derived copy.",
            source=str(source_path),
            destination=str(destination_path),
        )
    if source_path.is_symlink() or not source_path.is_file():
        raise _error(
            "MMC_TEMPLATE_NOT_FOUND",
            "The native scenario source is not a regular file.",
            source=str(source_path),
        )
    if destination_path.exists() or destination_path.is_symlink():
        raise _error(
            "MMC_BUILD_CONFLICT",
            "The native scenario destination already exists.",
            destination=str(destination_path),
        )

    for field, value in (("fault_time_s", fault_time_s), ("dc_fault_time_s", dc_fault_time_s)):
        if value is not None:
            _seconds(value, field)
    duration = (
        _seconds(fault_duration_s, "fault_duration_s", positive=True)
        if fault_duration_s is not None else None
    )

    requested: dict[str, Any] = dict(controls or {})
    for key, value in (
        ("Fault Time", fault_time_s),
        ("AC Fault type", ac_fault_type),
        ("Dblk T1", requested.pop("Dblk T1", None)),
        ("Dblk T2", requested.pop("Dblk T2", None)),
    ):
        if value is not None:
            requested[key] = value
    unknown = [
        name
        for name in requested
        if not isinstance(name, str) or name.casefold() not in _CONTROL_NAMES
    ]
    if unknown:
        raise _error(
            "MMC_TEMPLATE_NATIVE_BINDING_MISSING",
            "The requested native control is not in the audited contract.",
            controls=unknown,
        )
    if dc_fault_time_s is not None and fault_time_s is not None:
        raise _error(
            "MMC_TEMPLATE_NATIVE_BINDING_INVALID",
            "Specify either fault_time_s or dc_fault_time_s, not both.",
        )
    if dc_fault_time_s is not None:
        # The Main timer uses Flt_time; the unused Station wrapper does not
        # control the duration of the simulated fault switches.
        requested.setdefault("Fault Time", dc_fault_time_s)

    try:
        root = ET.parse(source_path).getroot()
    except (OSError, ET.ParseError) as error:
        raise _error(
            "MMC_TEMPLATE_INVALID",
            "The native scenario source could not be parsed.",
            source=str(source_path),
        ) from error

    bindings: list[dict[str, str]] = []
    for raw_name, raw_value in requested.items():
        canonical = _CONTROL_NAMES[raw_name.casefold()]
        if canonical == "Fault Time":
            _seconds(raw_value, canonical)
        _set_named_control(root, canonical, _value(raw_value, canonical), bindings)
    if duration is not None or any(name.casefold() == "fault time" for name in requested):
        _bind_fault_timer(root, duration, bindings)

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        ET.ElementTree(root).write(
            destination_path,
            encoding="utf-8",
            xml_declaration=False,
        )
    except OSError as error:
        raise _error(
            "MMC_TEMPLATE_NATIVE_WRITE_FAILED",
            "The native scenario copy could not be written.",
            destination=str(destination_path),
        ) from error

    try:
        observed = inspect_template_native_controls(destination_path)
        destination_hash = _sha256(destination_path)
        source_hash = _sha256(source_path)
    except (BackendError, OSError) as error:
        destination_path.unlink(missing_ok=True)
        if isinstance(error, BackendError):
            raise
        raise _error(
            "MMC_TEMPLATE_NATIVE_WRITE_FAILED",
            "The native scenario copy could not be verified.",
            destination=str(destination_path),
        ) from error
    return {
        "source": str(source_path),
        "destination": str(destination_path),
        "source_sha256": source_hash,
        "destination_sha256": destination_hash,
        "timing_basis": "template_embedded_emt",
        "bindings": bindings,
        "controls": observed,
    }


def _sample_record(value: Mapping[str, Any]) -> tuple[tuple[float, ...], tuple[float, ...]] | None:
    raw_time = value.get("time", value.get("domain"))
    raw_values = value.get("values")
    if (
        not isinstance(raw_time, (list, tuple))
        or not isinstance(raw_values, (list, tuple))
        or not raw_time
        or len(raw_time) != len(raw_values)
    ):
        return None
    try:
        times = tuple(float(item) for item in raw_time)
        values = tuple(float(item) for item in raw_values)
    except (TypeError, ValueError, OverflowError):
        return None
    if (
        not all(math.isfinite(item) for item in times + values)
        or any(right <= left for left, right in itertools.pairwise(times))
    ):
        return None
    return times, values


def _find_sample(
    channels: list[Mapping[str, Any]],
    tokens: tuple[str, ...],
    *,
    prefer_activity: bool = False,
    selector: str | None = None,
    role: str,
    invalid: list[str],
) -> tuple[Mapping[str, Any], tuple[float, ...], tuple[float, ...]] | None:
    matches: list[tuple[Mapping[str, Any], tuple[float, ...], tuple[float, ...]]] = []
    matched_count = 0
    for channel in channels:
        text = " ".join(
            str(channel.get(key, "")) for key in ("path", "description", "name")
        ).casefold()
        if (
            channel.get("path") != selector if selector is not None
            else not any(token in text for token in tokens)
        ):
            continue
        matched_count += 1
        sample = _sample_record(channel)
        if sample is not None:
            matches.append((channel, sample[0], sample[1]))
        else:
            invalid.append(f"samples:{role}")
    if matched_count > 1:
        invalid.append(f"ambiguous:{role}")
        if not prefer_activity:
            return None
    if not matches:
        return None
    if not prefer_activity:
        return matches[0]
    return max(matches, key=lambda item: max((abs(value) for value in item[2]), default=0.0))


def evaluate_template_native_dc_fault(
    samples: Mapping[str, Any],
    *,
    fault_current_limit_ka: float,
    topology: SubmoduleTopology | str = SubmoduleTopology.FULL_BRIDGE,
    channel_selectors: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluate explicit waveform evidence from a template-native DC fault.

    The evaluator is deliberately conservative.  It requires a channel that
    exposes negative inserted voltage; structural knowledge that a component
    is a full bridge cannot substitute for that waveform evidence.
    """

    selected_topology = SubmoduleTopology(topology)
    if selected_topology is SubmoduleTopology.HALF_BRIDGE:
        return {
            "verdict": "NOT_APPLICABLE",
            "capabilities": SubmoduleTopology.capabilities(selected_topology),
            "checks": {},
            "missing_channels": [],
            "invalid_evidence": [],
            "evidence": {},
            "reason": "half_bridge does not claim intrinsic DC-fault blocking",
        }
    raw_channels = samples.get("channels") if isinstance(samples, Mapping) else None
    channels = [item for item in raw_channels if isinstance(item, Mapping)] if isinstance(raw_channels, (list, tuple)) else []
    missing: list[str] = []
    invalid: list[str] = []
    try:
        valid_limit = not isinstance(fault_current_limit_ka, bool) and math.isfinite(float(fault_current_limit_ka)) and float(fault_current_limit_ka) >= 0
    except (TypeError, ValueError, OverflowError):
        valid_limit = False
    if not valid_limit:
        invalid.append("fault_current_limit_ka")
    roles = {"fault_applied", "fault_current", "blocked", "negative_voltage_inserted"}
    selectors = dict(channel_selectors) if isinstance(channel_selectors, Mapping) else {}
    if channel_selectors is not None and not isinstance(channel_selectors, Mapping):
        invalid.append("channel_selectors")
    if set(selectors) - roles or any(not isinstance(value, str) or not value.strip() for value in selectors.values()):
        invalid.append("channel_selectors")
    fault = _find_sample(
        channels,
        ("fault mode", "dc fault active", "fault_active"),
        prefer_activity=True,
        selector=selectors.get("fault_applied"), role="fault_applied", invalid=invalid,
    )
    current = _find_sample(channels, ("dc fault current", "fault current"), selector=selectors.get("fault_current"), role="fault_current", invalid=invalid)
    blocked = _find_sample(channels, ("de-blocking", "block status", "blocked", "blocking_state"), selector=selectors.get("blocked"), role="blocked", invalid=invalid)
    inserted = _find_sample(channels, ("v_inserted", "inserted voltage", "negative insertion"), selector=selectors.get("negative_voltage_inserted"), role="negative_voltage_inserted", invalid=invalid)
    selected = (
        ("fault_applied", fault),
        ("fault_current", current),
        ("blocked", blocked),
        ("negative_voltage_inserted", inserted),
    )
    for name, sample in selected:
        if sample is None:
            missing.append(name)
        elif name in {"fault_applied", "blocked"}:
            if sample[0].get("units") != "1":
                invalid.append(f"units:{name}")
            if any(value not in (0.0, 1.0) for value in sample[2]):
                invalid.append(f"binary:{name}")
    if fault is not None and current is not None and fault[1] != current[1]:
        invalid.append("time_alignment")
    if fault is not None and blocked is not None and fault[1] != blocked[1]:
        invalid.append("time_alignment")
    if fault is not None and inserted is not None and fault[1] != inserted[1]:
        invalid.append("time_alignment")

    checks = {
        "fault_applied": False,
        "negative_voltage_inserted": False,
        "blocked": False,
        "recovered": False,
        "bounded_fault_current": False,
    }
    evidence: dict[str, Any] = {
        "selected_channels": {
            name: {key: sample[0][key] for key in ("path", "call_id", "description", "units", "group") if key in sample[0]}
            for name, sample in selected if sample is not None
        }
    }
    fault_indices: list[int] = []
    if fault is not None:
        fault_times, fault_values = fault[1], fault[2]
        fault_indices = [index for index, value in enumerate(fault_values) if abs(value) > 1e-9]
        checks["fault_applied"] = bool(fault_indices)
        evidence["fault_time_s"] = fault_times[fault_indices[0]] if fault_indices else None
    if current is not None:
        unit = current[0].get("units")
        scale = {"kA": 1.0, "A": 0.001}.get(unit) if isinstance(unit, str) else None
        if scale is None:
            invalid.append("units:fault_current")
        else:
            peak = max(abs(value) * scale for value in current[2])
            evidence["fault_current_peak_ka"] = peak
            try:
                limit = float(fault_current_limit_ka)
                checks["bounded_fault_current"] = not isinstance(fault_current_limit_ka, bool) and math.isfinite(limit) and limit >= 0 and math.isfinite(peak) and peak <= limit
            except (TypeError, ValueError, OverflowError):
                checks["bounded_fault_current"] = False
    if inserted is not None:
        unit = inserted[0].get("units")
        scale = {"kV": 1.0, "V": 0.001}.get(unit) if isinstance(unit, str) else None
        if scale is None:
            invalid.append("units:negative_voltage_inserted")
        elif fault_indices:
            values = inserted[2]
            checks["negative_voltage_inserted"] = any(values[index] * scale < -1e-9 for index in fault_indices if index < len(values))
    if blocked is not None and fault_indices:
        values = blocked[2]
        identity = " ".join(str(blocked[0].get(key, "")) for key in ("path", "description", "name")).casefold()
        active = 0 if "de-blocking" in identity else 1
        evidence["blocking_active_value"] = active
        checks["blocked"] = any(values[index] == active for index in fault_indices if index < len(values))
        last_fault = fault_indices[-1]
        checks["recovered"] = any(value == 1 - active for value in values[last_fault + 1 :])
    if missing or invalid:
        verdict = "INCOMPLETE_ANALYSIS"
    else:
        summary = {
            "fault_applied": checks["fault_applied"],
            "negative_voltage_inserted": checks["negative_voltage_inserted"],
            "fault_current_peak_ka": evidence.get("fault_current_peak_ka"),
            "fault_current_limit_ka": fault_current_limit_ka,
            "blocked": checks["blocked"],
            "recovered": checks["recovered"],
        }
        verdict = evaluate_dc_fault_blocking(
            summary, topology=selected_topology
        )["verdict"]
    return {
        "verdict": verdict,
        "capabilities": SubmoduleTopology.capabilities(selected_topology),
        "checks": checks,
        "missing_channels": missing,
        "invalid_evidence": sorted(set(invalid)),
        "evidence": evidence,
    }


__all__ = [
    "evaluate_template_native_dc_fault",
    "inspect_template_native_controls",
    "materialize_template_native_scenario",
]
