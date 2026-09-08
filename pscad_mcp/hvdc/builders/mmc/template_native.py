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
from .models import SubmoduleTopology
from .template_audit import _components, _parameters, _template_native_controls

_CONTROL_NAMES = {
    "fault time": "Fault Time",
    "ac fault type": "AC Fault type",
    "dblk t1": "Dblk T1",
    "dblk t2": "Dblk T2",
    "ccsc enable": "CCSC Enable",
    "flt location": "Flt Location",
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


def _station_instance(root: ET.Element) -> ET.Element | None:
    for definition in root.iter():
        if (
            definition.tag.rsplit("}", 1)[-1].casefold() == "definition"
            and (definition.attrib.get("name") or "").rsplit(":", 1)[-1].casefold()
            == "station"
        ):
            for component in _components(definition):
                values = dict(_parameters(component))
                if "TFlt" in values or "FltDur" in values:
                    return component
    return None


def _set_station_parameter(
    root: ET.Element,
    parameter: str,
    value: str,
    bindings: list[dict[str, str]],
) -> None:
    component = _station_instance(root)
    if component is None:
        raise _error(
            "MMC_TEMPLATE_NATIVE_BINDING_MISSING",
            "The template has no Station instance with native fault parameters.",
            parameter=parameter,
        )
    owner = (component.attrib.get("id") or "").strip()
    params = [
        item
        for item in component.iter()
        if item.tag.rsplit("}", 1)[-1].casefold() == "param"
        and item.attrib.get("name") == parameter
    ]
    if len(params) != 1:
        raise _error(
            "MMC_TEMPLATE_NATIVE_BINDING_MISSING",
            "The Station instance has no unique native fault parameter.",
            parameter=parameter,
            owner=owner,
        )
    params[0].set("value", value)
    bindings.append(
        {"owner": owner, "name": parameter, "parameter": parameter, "value": value}
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
        # The official fault switches are driven by Flt_time, which is sourced
        # from the named Fault Time variable.  TFlt is also bound on the
        # Station instance for templates that use it in the pole model.
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
        _set_named_control(root, canonical, _value(raw_value, canonical), bindings)
    if dc_fault_time_s is not None:
        _set_station_parameter(
            root, "TFlt", _value(dc_fault_time_s, "dc_fault_time_s"), bindings
        )
    elif fault_time_s is not None:
        # The official Station instance forwards TFlt to the MMC fault model;
        # binding it alongside Fault Time keeps AC and DC scenarios explicit.
        _set_station_parameter(
            root, "TFlt", _value(fault_time_s, "fault_time_s"), bindings
        )
    if fault_duration_s is not None:
        _set_station_parameter(
            root, "FltDur", _value(fault_duration_s, "fault_duration_s"), bindings
        )

    fault_execution: dict[str, Any] = {}
    if dc_fault_time_s is not None:
        main = next((item for item in root.findall("./definitions/Definition") if item.get("name") == "Main"), None)
        timers = [item for item in _components(main) if item.get("defn") == "master:tfaultn" and dict(_parameters(item)).get("TF") == "Flt_time"] if main is not None else []
        if timers:
            if len(timers) != 1:
                raise _error("MMC_TEMPLATE_NATIVE_BINDING_AMBIGUOUS", "The actual DC fault timer is not unique.")
            duration = _value(fault_duration_s, "fault_duration_s") if fault_duration_s is not None else dict(_parameters(timers[0]))["DF"]
            timer_params = [item for item in timers[0].findall("./paramlist/param") if item.get("name") == "DF"]
            if len(timer_params) != 1:
                raise _error("MMC_TEMPLATE_NATIVE_BINDING_MISSING", "The actual DC fault timer has no unique duration.")
            timer_params[0].set("value", duration)
            bindings.append({"owner": timers[0].get("id"), "name": "DC fault timer", "parameter": "DF", "value": duration})
            _set_named_control(root, "Flt Location", "3", bindings)
            switches = [item for item in _components(main) if item.get("defn") == "master:fault_sw" and dict(_parameters(item)).get("Name") == "DC_flt_2_PN"]
            if len(switches) != 1:
                raise _error("MMC_TEMPLATE_NATIVE_BINDING_MISSING", "The terminal-2 P-N fault branch is not unique.")
            clearing = next((item for item in switches[0].findall("./paramlist/param") if item.get("name") == "OpCur"), None)
            if clearing is None:
                raise _error("MMC_TEMPLATE_NATIVE_BINDING_MISSING", "The imposed fault clearing mode is missing.")
            # Removing an externally imposed fault at a specified EMT time is
            # distinct from modelling a current-zero-only circuit breaker.
            clearing.set("value", "1")
            bindings.append({"owner": switches[0].get("id"), "name": "DC_flt_2_PN", "parameter": "OpCur", "value": "1"})
            fault_execution = {"timer_owner": timers[0].get("id"), "timer_start_signal": "Flt_time", "timer_duration_s": float(duration), "fault_location": 3, "fault_switch_owner": switches[0].get("id"), "fault_switch_signal": "DC_flt_2_PN", "clearing_policy": "imposed_fault_removed_at_scheduled_time", "actual_state_required": "OPENBR"}

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from .fault_channels import _write_new_xml
        _write_new_xml(root, destination_path)
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
        "fault_execution": fault_execution,
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


def evaluate_template_native_dc_fault(
    samples: Mapping[str, Any],
    *,
    fault_current_limit_ka: float,
    topology: SubmoduleTopology | str = SubmoduleTopology.FULL_BRIDGE,
    channel_contract: Mapping[str, Any] | None = None,
    checks_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate frozen, instance-qualified physical evidence without inference."""

    from .fault_channels import REQUIRED_ROLES, verify_output_dataset

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
    samples = samples if isinstance(samples, Mapping) else {}
    channel_contract = channel_contract if channel_contract is not None else {}
    checks_contract = checks_contract if checks_contract is not None else {}
    missing: list[str] = []
    invalid: list[str] = []
    check_results: list[dict[str, Any]] = []
    checks = {name: False for name in ("fault_applied", "negative_voltage_inserted", "blocked", "recovered", "bounded_fault_current")}
    evidence: dict[str, Any] = {"unit_conversions": [], "channels": [], "evidence_kind": samples.get("evidence_kind")}
    identity = samples.get("identity")
    if isinstance(identity, Mapping):
        try:
            verify_output_dataset(identity)
        except BackendError:
            invalid.append("output_identity_changed")
    elif samples.get("evidence_kind") != "synthetic":
        invalid.append("output_identity_missing")
    if not isinstance(channel_contract, Mapping) or channel_contract.get("schema_version") != 1:
        invalid.append("channel_contract_missing")
        channel_contract = {}
    if not isinstance(checks_contract, Mapping) or checks_contract.get("schema_version") != 1:
        invalid.append("checks_contract_missing")
        checks_contract = {}
    bindings = channel_contract.get("channels", [])
    raw_channels = samples.get("channels", [])
    channels = [item for item in raw_channels if isinstance(item, Mapping)] if isinstance(raw_channels, (list, tuple)) else []
    selected: dict[str, list[dict[str, Any]]] = {role: [] for role in REQUIRED_ROLES}
    units = {"fault_active": "1", "blocking_state": "1", "recovery_enable": "1", "v_inserted": "kV", "v_dc": "kV", "v_cap": "kV", "i_dc_fault": "kA", "i_arm": "kA", "p_active": "MW"}
    factors = {("A", "kA"): 0.001, ("V", "kV"): 0.001, ("W", "MW"): 0.000001, ("kW", "MW"): 0.001}
    domain: tuple[float, ...] | None = None
    binding_ids = set()
    for binding in bindings if isinstance(bindings, (list, tuple)) else []:
        if not isinstance(binding, Mapping) or binding.get("role") not in selected:
            invalid.append("invalid_channel_binding")
            continue
        role = binding["role"]
        channel_id = binding.get("channel_id", role)
        selector = binding.get("selector")
        if channel_id in binding_ids:
            invalid.append(f"duplicate_contract_id:{channel_id}")
        binding_ids.add(channel_id)
        if not isinstance(selector, Mapping) or not all(selector.get(key) for key in ("description", "owner_id", "instance_path")):
            invalid.append(f"selector_missing:{channel_id}")
            continue
        matches = [item for item in channels if all(item.get(key) == value for key, value in selector.items() if key in ("description", "group", "owner_id", "instance_path")) and ("channel_id" not in item or item["channel_id"] == channel_id)]
        if len(matches) != 1:
            if matches:
                invalid.append(f"ambiguous_channel:{channel_id}")
            else:
                missing.append(role)
            continue
        channel = matches[0]
        sample = _sample_record(channel)
        if sample is None:
            invalid.append(f"invalid_samples:{channel_id}")
            continue
        times, values = sample
        if domain is None:
            domain = times
        elif domain != times:
            invalid.append(f"time_alignment:{channel_id}")
        if binding.get("dimension") != 1 or channel.get("dimension") != 1:
            invalid.append(f"dimension:{channel_id}")
        if not isinstance(binding.get("signal_source"), Mapping) or binding["signal_source"].get("kind") not in ("physical_measurement", "physical_state", "recovery_control"):
            invalid.append(f"physical_source:{channel_id}")
        for key in ("output_part", "metadata_file", "hash", "metadata_sha256"):
            if not channel.get(key):
                invalid.append(f"source_identity:{channel_id}:{key}")
        if isinstance(identity, Mapping):
            files = list(identity.get("files", {}).values())
            for path_key, hash_key in (("output_part", "hash"), ("metadata_file", "metadata_sha256")):
                members = [item for item in files if item.get("path") == channel.get(path_key) and item.get("sha256") == channel.get(hash_key)]
                if len(members) != 1:
                    invalid.append(f"dataset_membership:{channel_id}:{path_key}")
            call_id = channel.get("call_id")
            if type(call_id) is not int or call_id < 1 or Path(str(channel.get("output_part", ""))).name.casefold() != f"{identity.get('base')}_{(call_id - 1) // 10 + 1:02d}.out".casefold():
                invalid.append(f"dataset_part_mapping:{channel_id}")
            if samples.get("evidence_kind") != "synthetic":
                metadata_members = [item for item in files if item.get("path") == channel.get("compiler_metadata_file") and item.get("sha256") == channel.get("compiler_metadata_sha256")]
                compiled = channel.get("compiled_identity", {})
                actual_compiled = []
                if len(metadata_members) == 1:
                    try:
                        metadata_root = ET.parse(metadata_members[0]["path"]).getroot()
                        actual_compiled = [dict(item.attrib) for item in metadata_root.iter("Analog") if item.get("index") == str(call_id - 1)] if type(call_id) is int else []
                    except (OSError, ET.ParseError):
                        invalid.append(f"compiled_metadata_invalid:{channel_id}")
                if len(actual_compiled) != 1 or actual_compiled[0] != compiled or compiled.get("id") != str(binding["owner_id"]) + ":0" or compiled.get("index") != str(call_id - 1) or compiled.get("unit") != channel.get("units") or compiled.get("dim") != str(binding["dimension"]):
                    invalid.append(f"compiled_metadata_binding:{channel_id}")
        source_units, target_units = channel.get("units"), units[role]
        factor = 1.0 if source_units == target_units else factors.get((source_units, target_units))
        if factor is None or binding.get("units") != target_units:
            invalid.append(f"units:{channel_id}")
            continue
        if factor != 1:
            evidence["unit_conversions"].append({"channel_id": channel_id, "from": source_units, "to": target_units, "factor": factor})
        values = tuple(value * factor for value in values)
        if role in ("fault_active", "blocking_state", "recovery_enable"):
            polarity = binding.get("polarity")
            if not isinstance(polarity, Mapping) or set(polarity) != {"active", "inactive"} or {polarity.get("active"), polarity.get("inactive")} != {0, 1}:
                invalid.append(f"polarity:{channel_id}")
                continue
            if any(abs(value - round(value)) > 1e-9 or round(value) not in (0, 1) for value in values):
                invalid.append(f"binary_state:{channel_id}")
                continue
            values = tuple(float(abs(value - polarity["active"]) <= 1e-9) for value in values)
        source = {key: channel.get(key) for key in ("output_part", "metadata_file", "hash", "metadata_sha256", "instance_path", "owner_id", "call_id")}
        source.update({"channel_id": channel_id, "signal_source": binding["signal_source"], "sample_count": len(times), "time_bounds_s": [times[0], times[-1]], "units": target_units})
        evidence["channels"].append(source)
        selected[role].append({"binding": binding, "values": values, "source": source})
    for role, values in selected.items():
        if not values:
            missing.append(role)
    balance_inputs = [item for item in selected["p_active"] if item["binding"].get("nominal_role") == "power_balance_input"]
    balance_outputs = [item for item in selected["p_active"] if item["binding"].get("nominal_role") == "controlled_active_power"]
    if balance_inputs and not balance_outputs:
        invalid.append("power_balance_source_missing")

    windows: dict[str, tuple[float, float]] = {}
    numbers: dict[str, float] = {}
    try:
        for key in ("output_step_s", "max_timing_error_s", "frequency_hz", "nominal_target_relative_tolerance", "maximum_power_loss_fraction", "arm_rms_stability_relative_tolerance", "arm_peak_limit_ka", "negative_voltage_max_kv", "fault_current_limit_ka", "voltage_recovery_relative_tolerance", "power_recovery_relative_tolerance", "arm_rms_recovery_relative_tolerance", "capacitor_recovery_relative_tolerance", "steady_relative_rms_tolerance", "minimum_operating_fraction", "arm_rms_floor_ka"):
            value = checks_contract[key]
            if isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(key)
            numbers[key] = float(value)
        for key in ("prefault", "fault", "recovery"):
            window = tuple(float(value) for value in checks_contract[key + "_window_s"])
            if len(window) != 2 or not all(math.isfinite(value) for value in window) or window[0] < 0 or window[0] >= window[1]:
                raise ValueError(key)
            windows[key] = window
        if not (windows["prefault"][1] < windows["fault"][0] < windows["fault"][1] < windows["recovery"][0]):
            raise ValueError("window_order")
        if checks_contract.get("time_basis") != "EMTDC" or checks_contract.get("time_units") != "s" or numbers["output_step_s"] <= 0 or numbers["negative_voltage_max_kv"] >= 0 or numbers["fault_current_limit_ka"] != float(fault_current_limit_ka):
            raise ValueError("time_or_physical_contract")
        if any(numbers[key] <= 0 for key in numbers if key != "negative_voltage_max_kv"):
            raise ValueError("positive_limits")
        pre_duration = windows["prefault"][1] - windows["prefault"][0]
        post_duration = windows["recovery"][1] - windows["recovery"][0]
        cycles = pre_duration * numbers["frequency_hz"]
        if abs(pre_duration - post_duration) > 1e-9 or round(cycles) < 2 or abs(cycles - round(cycles)) > 1e-7:
            raise ValueError("equal_complete_cycle_windows")
    except (KeyError, TypeError, ValueError, OverflowError):
        invalid.append("invalid_checks_contract")
    if domain and "invalid_checks_contract" not in invalid:
        step = numbers["output_step_s"]
        if any(right - left > step * 1.01 for left, right in itertools.pairwise(domain)):
            invalid.append("time_gap")
        for key, window in windows.items():
            if domain[0] > window[0] + 1e-9 or domain[-1] < window[1] - 1e-9 or len([value for value in domain if window[0] <= value <= window[1]]) < 2:
                invalid.append(f"missing_window:{key}")

    def add(name: str, passed: bool, expected: Any, observed: Any, window: Any, source: Any) -> None:
        check_results.append({"name": name, "status": "PASS" if passed else "FAIL", "expected": expected, "observed": observed, "window": window, "source": source})

    # Never index mismatched domains or publish metrics as valid after drift.
    if not invalid and not missing and domain is not None:
        indices = {key: [index for index, value in enumerate(domain) if window[0] <= value <= window[1]] for key, window in windows.items()}
        fault_start, fault_end = windows["fault"]
        tol = numbers["max_timing_error_s"]
        fault_ok = []
        active_indices: set[int] = set()
        for channel in selected["fault_active"]:
            values = channel["values"]
            active = [index for index, value in enumerate(values) if value == 1]
            active_indices.update(index for index in active if fault_start <= domain[index] < fault_end)
            rise = domain[active[0]] if active else None
            fall = domain[active[-1] + 1] if active and active[-1] + 1 < len(domain) else None
            interior = [index for index, value in enumerate(domain) if fault_start + tol <= value < fault_end - tol]
            passed = bool(active and interior and rise is not None and fall is not None and abs(rise - fault_start) <= tol and abs(fall - fault_end) <= tol and all(values[index] == 1 for index in interior) and all(values[index] == 0 for index in indices["prefault"] + indices["recovery"]))
            fault_ok.append(passed)
            evidence["fault_time_s"] = rise
            evidence["fault_removal_time_s"] = fall
            add("fault_applied", passed, {"rise_s": fault_start, "fall_s": fault_end, "tolerance_s": tol}, {"rise_s": rise, "fall_s": fall}, windows["fault"], channel["source"])
        checks["fault_applied"] = all(fault_ok)
        negative_ok = []
        for channel in selected["v_inserted"]:
            minimum = min((channel["values"][index] for index in active_indices), default=None)
            passed = minimum is not None and minimum <= numbers["negative_voltage_max_kv"]
            negative_ok.append(passed)
            add("negative_voltage_inserted", passed, {"maximum_kv": numbers["negative_voltage_max_kv"]}, {"minimum_kv": minimum}, windows["fault"], channel["source"])
        checks["negative_voltage_inserted"] = all(negative_ok)
        peaks = []
        for channel in selected["i_dc_fault"]:
            peak = max(abs(value) for value in channel["values"])
            peaks.append(peak)
            add("bounded_fault_current", peak <= numbers["fault_current_limit_ka"], {"maximum_ka": numbers["fault_current_limit_ka"]}, {"peak_ka": peak}, [domain[0], domain[-1]], channel["source"])
        evidence["fault_current_peak_ka"] = max(peaks)
        checks["bounded_fault_current"] = max(peaks) <= numbers["fault_current_limit_ka"]
        blocked_ok, recovery_ok = [], []
        for channel in selected["blocking_state"]:
            passed = any(channel["values"][index] == 1 for index in active_indices)
            blocked_ok.append(passed)
            add("blocked", passed, {"active": 1}, {"blocked_samples": sum(channel["values"][index] for index in active_indices)}, windows["fault"], channel["source"])
            recovered = all(channel["values"][index] == 0 for index in indices["recovery"])
            recovery_ok.append(recovered)
            add("unblocked_after_fault", recovered, {"active": 0}, {"blocked_samples": sum(channel["values"][index] for index in indices["recovery"])}, windows["recovery"], channel["source"])
        checks["blocked"] = all(blocked_ok)
        if balance_inputs:
            for window_name in ("prefault", "recovery"):
                means = [math.fsum(item["values"][index] for index in indices[window_name]) / len(indices[window_name]) for item in balance_inputs + balance_outputs]
                input_mw = math.fsum(means[:len(balance_inputs)])
                output_mw = -math.fsum(means[len(balance_inputs):])
                loss = input_mw - output_mw
                passed = input_mw > 0 and output_mw > 0 and 0 <= loss <= output_mw * numbers["maximum_power_loss_fraction"]
                recovery_ok.append(passed)
                add("active_power_balance_" + window_name, passed, {"maximum_loss_fraction": numbers["maximum_power_loss_fraction"], "controlled_terminal": "T2", "input_terminal": "T1"}, {"input_mw": input_mw, "output_mw": output_mw, "loss_mw": loss}, windows[window_name], [item["source"] for item in balance_inputs + balance_outputs])
        for channel in selected["recovery_enable"]:
            passed = all(channel["values"][index] == 1 for index in indices["recovery"])
            recovery_ok.append(passed)
            add("recovery_enabled", passed, {"active": 1}, {"enabled_samples": sum(channel["values"][index] for index in indices["recovery"])}, windows["recovery"], channel["source"])
        tolerance_keys = {"v_dc": "voltage", "p_active": "power", "i_arm": "arm_rms", "v_cap": "capacitor"}
        for role, tolerance_key in tolerance_keys.items():
            for channel in selected[role]:
                before = [channel["values"][index] for index in indices["prefault"]]
                after = [channel["values"][index] for index in indices["recovery"]]
                rms = lambda values: math.sqrt(math.fsum(value * value for value in values) / len(values))
                pre = rms(before) if role == "i_arm" else math.fsum(before) / len(before)
                post = rms(after) if role == "i_arm" else math.fsum(after) / len(after)
                nominal = channel["binding"].get("nominal")
                input_power = role == "p_active" and channel["binding"].get("nominal_role") == "power_balance_input"
                reference_ok = abs(pre) >= numbers["arm_rms_floor_ka"] if role == "i_arm" else isinstance(nominal, (int, float)) and not isinstance(nominal, bool) and math.isfinite(nominal) and nominal != 0 and pre * nominal > 0 and abs(pre) >= abs(nominal) * numbers["minimum_operating_fraction"] and (input_power or abs(pre - nominal) <= abs(nominal) * numbers["nominal_target_relative_tolerance"])
                def cycle_variation(window_name: str, reference: float, channel=channel, rms=rms) -> float | None:
                    window_start, window_end = windows[window_name]
                    cycle_count = round((window_end - window_start) * numbers["frequency_hz"])
                    bins: list[list[float]] = [[] for _ in range(cycle_count)]
                    for index in indices[window_name]:
                        cycle_index = math.floor((domain[index] - window_start) * numbers["frequency_hz"] + 1e-8)
                        if 0 <= cycle_index < cycle_count:
                            bins[cycle_index].append(channel["values"][index])
                    if any(len(values) < 2 for values in bins):
                        invalid.append("insufficient_cycle_samples:" + channel["source"]["channel_id"])
                        return None
                    return max(abs(rms(values) - reference) / abs(reference) for values in bins) if reference else None
                ripple = cycle_variation("prefault", pre) if role == "i_arm" else rms([value - pre for value in before]) / abs(pre) if pre else None
                stability_limit = numbers["arm_rms_stability_relative_tolerance"] if role == "i_arm" else numbers["steady_relative_rms_tolerance"]
                stable = ripple is not None and ripple <= stability_limit
                reference_ok = bool(reference_ok and stable)
                if role == "i_arm":
                    reference_ok = reference_ok and max(abs(value) for value in before) <= numbers["arm_peak_limit_ka"]
                tolerance = numbers[tolerance_key + "_recovery_relative_tolerance"]
                error = abs(post - pre) / abs(pre) if reference_ok and pre else None
                post_ripple = cycle_variation("recovery", post) if role == "i_arm" else rms([value - post for value in after]) / abs(post) if post else None
                post_stable = post_ripple is not None and post_ripple <= stability_limit
                if role == "i_arm":
                    post_stable = post_stable and max(abs(value) for value in after) <= numbers["arm_peak_limit_ka"]
                elif not input_power:
                    post_stable = post_stable and isinstance(nominal, (int, float)) and not isinstance(nominal, bool) and math.isfinite(nominal) and post * nominal > 0 and abs(post - nominal) <= abs(nominal) * numbers["nominal_target_relative_tolerance"]
                recovered = bool(reference_ok and error is not None and error <= tolerance and post_stable)
                recovery_ok.append(recovered)
                add(f"{role}_operating_point", reference_ok, {"nominal": nominal, "nominal_target_relative_tolerance": numbers["nominal_target_relative_tolerance"], "minimum_operating_fraction": numbers["minimum_operating_fraction"], "arm_rms_floor_ka": numbers["arm_rms_floor_ka"], "arm_peak_limit_ka": numbers["arm_peak_limit_ka"], "maximum_relative_rms_ripple": stability_limit}, {"value": pre, "peak_absolute": max(abs(value) for value in before), "relative_rms_ripple": ripple}, windows["prefault"], channel["source"])
                add(f"{role}_recovery", recovered, {"relative_tolerance": tolerance, "maximum_relative_rms_ripple": stability_limit}, {"before": pre, "after": post, "peak_absolute": max(abs(value) for value in after), "relative_error": error, "after_relative_rms_ripple": post_ripple}, windows["recovery"], channel["source"])
        checks["recovered"] = all(recovery_ok)
    verdict = "INCOMPLETE_ANALYSIS" if missing or invalid else "PASS" if all(checks.values()) else "FAIL"
    return {
        "verdict": verdict,
        "capabilities": SubmoduleTopology.capabilities(selected_topology),
        "checks": checks,
        "check_results": check_results,
        "missing_channels": sorted(set(missing)),
        "invalid_evidence": sorted(set(invalid)),
        "evidence": evidence,
        "evidence_valid": not invalid,
        "checks_contract": dict(checks_contract),
    }


__all__ = [
    "evaluate_template_native_dc_fault",
    "inspect_template_native_controls",
    "materialize_template_native_scenario",
]
