"""Auditable engineering evidence derived from fixed LCC dynamic traces."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from statistics import median
from typing import Any


@dataclass(frozen=True)
class Trace:
    path: str
    units: str
    time: Sequence[float]
    values: Sequence[float]


class _DynamicEvidenceError(Exception):
    """Private normalization error translated into a FAIL evidence check."""

    def __init__(self, reason: str, selector: str | None = None) -> None:
        self.reason = reason
        self.selector = selector
        super().__init__(reason, selector)


def _records(value: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = value.get("channels")
    if isinstance(raw, Mapping):
        records: list[Mapping[str, Any]] = []
        for name, item in raw.items():
            if isinstance(item, Mapping):
                records.append({"path": name, **dict(item)})
            else:
                records.append({"path": name})
        return records
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        return [item for item in raw if isinstance(item, Mapping)]
    return []


def normalize_exact_channels(
    value: Mapping[str, Any], required: Sequence[Mapping[str, Any]]
) -> dict[str, Trace]:
    """Normalize exact path/unit channel declarations into immutable traces."""

    if not isinstance(value, Mapping):
        raise _DynamicEvidenceError("channels_not_mapping")
    by_path: dict[str, list[Mapping[str, Any]]] = {}
    for record in _records(value):
        path = record.get("path")
        if isinstance(path, str):
            by_path.setdefault(path, []).append(record)

    traces: dict[str, Trace] = {}
    for declaration in required:
        if not isinstance(declaration, Mapping):
            raise _DynamicEvidenceError("invalid_required_channel")
        path = str(declaration.get("path", ""))
        matches = by_path.get(path, [])
        if len(matches) != 1:
            raise _DynamicEvidenceError("selector_count", path)
        record = matches[0]
        expected_units = declaration.get("units")
        units = record.get("units", record.get("unit"))
        if units != expected_units:
            raise _DynamicEvidenceError("unit_mismatch", path)
        domain = record.get("domain", record.get("time"))
        samples = record.get("values", record.get("samples"))
        if (
            not isinstance(domain, Sequence)
            or isinstance(domain, (str, bytes, bytearray))
            or not isinstance(samples, Sequence)
            or isinstance(samples, (str, bytes, bytearray))
        ):
            raise _DynamicEvidenceError("invalid_trace", path)
        normalized: list[tuple[float, ...]] = []
        for sequence in (domain, samples):
            if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in sequence):
                raise _DynamicEvidenceError("invalid_trace", path)
            try:
                converted = tuple(float(item) for item in sequence)
            except (TypeError, ValueError, OverflowError) as error:
                raise _DynamicEvidenceError("invalid_trace", path) from error
            if not all(math.isfinite(item) for item in converted):
                raise _DynamicEvidenceError("invalid_trace", path)
            normalized.append(converted)
        times, values = normalized
        if (
            not times
            or len(times) != len(values)
            or any(right <= left for left, right in pairwise(times))
        ):
            raise _DynamicEvidenceError("invalid_trace", path)
        traces[path] = Trace(path, str(units), times, values)
    return traces


def _window(trace: Trace, start: float, end: float) -> list[float]:
    return [value for time, value in zip(trace.time, trace.values) if start <= time < end]


def _window_inclusive(trace: Trace, start: float, end: float) -> list[float]:
    return [value for time, value in zip(trace.time, trace.values) if start <= time <= end]


def _safe_required(contract: Any) -> list[Mapping[str, Any]]:
    if not isinstance(contract, Mapping):
        return []
    required = contract.get("required_channels", [])
    if not isinstance(required, Sequence) or isinstance(required, (str, bytes, bytearray)):
        return []
    return [item for item in required if isinstance(item, Mapping)]


def _finite_number(value: Any, name: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _DynamicEvidenceError(f"invalid_{name}")
    number = float(value)
    if not math.isfinite(number):
        raise _DynamicEvidenceError(f"invalid_{name}")
    if positive and number <= 0.0:
        raise _DynamicEvidenceError(f"invalid_{name}")
    if nonnegative and number < 0.0:
        raise _DynamicEvidenceError(f"invalid_{name}")
    return number


def _validate_contract(contract: Any, output_step_s: Any) -> None:
    if not isinstance(contract, Mapping):
        raise _DynamicEvidenceError("invalid_contract")

    required = contract.get("required_channels")
    if not isinstance(required, Sequence) or isinstance(required, (str, bytes, bytearray)) or not required:
        raise _DynamicEvidenceError("invalid_required_channels")
    required_identity: dict[str, str] = {}
    for declaration in required:
        if (
            not isinstance(declaration, Mapping)
            or not isinstance(declaration.get("path"), str)
            or not declaration.get("path")
            or not declaration["path"].strip()
            or not isinstance(declaration.get("units"), str)
            or not declaration.get("units")
            or not declaration["units"].strip()
        ):
            raise _DynamicEvidenceError("invalid_required_channel")
        path = declaration["path"]
        if path in required_identity:
            raise _DynamicEvidenceError("duplicate_required_channel", path)
        required_identity[path] = declaration["units"]

    event = contract.get("event")
    if not isinstance(event, Mapping):
        raise _DynamicEvidenceError("invalid_event")
    _finite_number(event.get("time_s"), "event_time_s", nonnegative=True)
    _finite_number(event.get("duration_s"), "event_duration_s", positive=True)
    event_recovery_window = _finite_number(event.get("recovery_window_s"), "event_recovery_window_s", positive=True)

    disturbance = contract.get("disturbance")
    if not isinstance(disturbance, Mapping):
        raise _DynamicEvidenceError("invalid_disturbance")
    inactive_max = _finite_number(disturbance.get("inactive_max"), "inactive_max", nonnegative=True)
    active_min = _finite_number(disturbance.get("active_min"), "active_min", nonnegative=True)
    if active_min <= inactive_max:
        raise _DynamicEvidenceError("invalid_disturbance_thresholds")
    _finite_number(disturbance.get("maximum_edge_error_s"), "maximum_edge_error_s", nonnegative=True)

    failure = contract.get("failure_indication")
    if (
        not isinstance(failure, Mapping)
        or not isinstance(failure.get("channel"), str)
        or not isinstance(failure.get("units"), str)
        or not failure.get("channel")
        or not failure.get("units")
        or not failure["channel"].strip()
        or not failure["units"].strip()
        or required_identity.get(failure["channel"]) != failure["units"]
    ):
        raise _DynamicEvidenceError("invalid_failure_indication")
    _finite_number(failure.get("minimum_drop_rad"), "minimum_drop_rad", positive=True)

    bounded = contract.get("bounded_dc_response")
    if (
        not isinstance(bounded, Mapping)
        or not isinstance(bounded.get("channel"), str)
        or not isinstance(bounded.get("units"), str)
        or not bounded.get("channel")
        or not bounded.get("units")
        or not bounded["channel"].strip()
        or not bounded["units"].strip()
        or required_identity.get(bounded["channel"]) != bounded["units"]
    ):
        raise _DynamicEvidenceError("invalid_bounded_dc_response")
    _finite_number(bounded.get("prefault_window_s"), "prefault_window_s", positive=True)
    _finite_number(bounded.get("minimum_prefault_magnitude_ka"), "minimum_prefault_magnitude_ka", positive=True)
    _finite_number(bounded.get("maximum_peak_to_prefault_ratio"), "maximum_peak_to_prefault_ratio", positive=True)

    recovery = contract.get("recovery")
    if not isinstance(recovery, Mapping):
        raise _DynamicEvidenceError("invalid_recovery")
    recovery_window = _finite_number(recovery.get("window_s"), "recovery_window_s", positive=True)
    output_step = _finite_number(output_step_s, "output_step", positive=True)
    consistency_tolerance = max(1e-12, output_step * 1e-9)
    if not math.isclose(event_recovery_window, recovery_window, rel_tol=0.0, abs_tol=consistency_tolerance):
        raise _DynamicEvidenceError("recovery_window_mismatch")
    minimum_hold = _finite_number(recovery.get("minimum_hold_s"), "minimum_hold_s", positive=True)
    if minimum_hold > recovery_window:
        raise _DynamicEvidenceError("invalid_recovery_hold")
    recovery_channels = recovery.get("channels")
    if not isinstance(recovery_channels, Sequence) or isinstance(recovery_channels, (str, bytes, bytearray)) or not recovery_channels:
        raise _DynamicEvidenceError("invalid_recovery_channels")
    for declaration in recovery_channels:
        if (
            not isinstance(declaration, Mapping)
            or not isinstance(declaration.get("path"), str)
            or not isinstance(declaration.get("units"), str)
            or not declaration.get("path")
            or not declaration.get("units")
            or not declaration["path"].strip()
            or not declaration["units"].strip()
            or required_identity.get(declaration["path"]) != declaration["units"]
        ):
            raise _DynamicEvidenceError("invalid_recovery_channel")
        _finite_number(declaration.get("relative_band"), "relative_band", nonnegative=True)
        _finite_number(declaration.get("absolute_floor"), "absolute_floor", nonnegative=True)



def _edge_crossing_time(trace: Trace, threshold: float, *, rising: bool) -> float:
    for left_time, right_time, left_value, right_value in zip(
        trace.time, trace.time[1:], trace.values, trace.values[1:]
    ):
        if rising:
            crossed = left_value < threshold <= right_value
        else:
            crossed = left_value >= threshold > right_value
        if not crossed:
            continue
        delta = right_value - left_value
        if delta == 0.0:
            return float(left_time)
        fraction = (threshold - left_value) / delta
        return float(left_time + fraction * (right_time - left_time))
    return math.nan


def _check(
    outcome: str,
    selectors: Sequence[str],
    units: Mapping[str, str],
    window_s: tuple[float, float],
    sample_count: int,
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "selectors": list(selectors),
        "units": dict(units),
        "window_s": [float(window_s[0]), float(window_s[1])],
        "sample_count": int(sample_count),
        "metrics": dict(metrics),
    }


def _incomplete_checks(
    contract: Any, reason: str, end: float, observed_end: float
) -> dict[str, dict[str, Any]]:
    required = _safe_required(contract)
    units = {str(item.get("path")): str(item.get("units")) for item in required}
    selectors = list(units)
    checks = {}
    for name in ("disturbance", "failure_indication", "bounded_dc_response", "recovery"):
        checks[name] = _check(
            "INCOMPLETE_ANALYSIS",
            selectors,
            units,
            (0.0, end),
            0,
            {"reason": reason, "required_end_s": end, "observed_end_s": observed_end},
        )
    return checks


def _failed_checks(contract: Any, error: _DynamicEvidenceError) -> dict[str, dict[str, Any]]:
    required = _safe_required(contract)
    units = {str(item.get("path")): str(item.get("units")) for item in required}
    selectors = list(units)
    metrics = {"reason": error.reason}
    if error.selector:
        metrics["selector"] = error.selector
    return {
        name: _check("FAIL", selectors, units, (0.0, 0.0), 0, metrics)
        for name in ("disturbance", "failure_indication", "bounded_dc_response", "recovery")
    }


def derive_fixed_lcc_dynamic_evidence(
    raw_channels: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    output_step_s: float = 0.00005,
) -> dict[str, Any]:
    """Derive four fixed-contract checks from raw traces only."""

    try:
        _validate_contract(contract, output_step_s)
        required = contract["required_channels"]
        traces = normalize_exact_channels(raw_channels, required)
        event = contract["event"]
        event_time = float(event["time_s"])
        duration = float(event["duration_s"])
        recovery_window = float(event["recovery_window_s"])
        clear_time = event_time + duration
        domain_end = clear_time + recovery_window
        bound = contract["bounded_dc_response"]
        bounded_prefault_window = float(bound["prefault_window_s"])
        prefault_window = max(0.1, bounded_prefault_window)
        prefault_start = event_time - prefault_window
        if any(trace.time[0] > prefault_start or trace.time[-1] < domain_end for trace in traces.values()):
            observed_start = max(trace.time[0] for trace in traces.values())
            observed_end = min(trace.time[-1] for trace in traces.values())
            checks = _incomplete_checks(contract, "insufficient_time_coverage", domain_end, observed_end)
            for check in checks.values():
                check["metrics"]["required_start_s"] = prefault_start
                check["metrics"]["observed_start_s"] = observed_start
            return {"engineering_verdict": "INCOMPLETE_ANALYSIS", "checks": checks}

        edge_tolerance = max(float(contract["disturbance"]["maximum_edge_error_s"]), 2.0 * output_step_s)
        disturbance_trace = traces["Fault/LCC Fault Active"]
        disturbance_prefault_start = event_time - 0.1
        pre_fault = _window(disturbance_trace, disturbance_prefault_start, event_time)
        event_fault = _window(disturbance_trace, event_time, clear_time)
        post_fault = _window_inclusive(disturbance_trace, clear_time, clear_time + 0.1)
        active_min = float(contract["disturbance"]["active_min"])
        inactive_max = float(contract["disturbance"]["inactive_max"])
        first_active = _edge_crossing_time(disturbance_trace, active_min, rising=True)
        last_active = _edge_crossing_time(disturbance_trace, active_min, rising=False)
        rise_error = abs(first_active - event_time) if math.isfinite(first_active) else math.inf
        fall_error = abs(last_active - clear_time) if math.isfinite(last_active) else math.inf
        disturbance_pass = bool(pre_fault and event_fault and post_fault) and (
            max(pre_fault) <= inactive_max
            and min(event_fault) >= active_min
            and max(post_fault) <= inactive_max
            and rise_error <= edge_tolerance
            and fall_error <= edge_tolerance
        )
        disturbance = _check(
            "PASS" if disturbance_pass else "FAIL",
            [disturbance_trace.path],
            {disturbance_trace.path: disturbance_trace.units},
            (disturbance_prefault_start, clear_time + 0.1),
            len(pre_fault) + len(event_fault) + len(post_fault),
            {
                "prefault_max": max(pre_fault) if pre_fault else math.nan,
                "event_min": min(event_fault) if event_fault else math.nan,
                "postclear_max": max(post_fault) if post_fault else math.nan,
                "measured_rise_s": first_active,
                "measured_fall_s": last_active,
                "rise_edge_error_s": rise_error,
                "fall_edge_error_s": fall_error,
                "edge_tolerance_s": edge_tolerance,
            },
        )

        gamma = traces[contract["failure_indication"]["channel"]]
        gamma_pre = _window(gamma, disturbance_prefault_start, event_time)
        gamma_event = _window(gamma, event_time, clear_time)
        gamma_baseline = median(gamma_pre) if gamma_pre else math.nan
        gamma_min = min(gamma_event) if gamma_event else math.nan
        gamma_drop = gamma_baseline - gamma_min if gamma_pre and gamma_event else math.nan
        minimum_drop = float(contract["failure_indication"]["minimum_drop_rad"])
        failure = _check(
            "PASS" if math.isfinite(gamma_drop) and gamma_drop >= minimum_drop else "FAIL",
            [gamma.path],
            {gamma.path: gamma.units},
            (disturbance_prefault_start, clear_time),
            len(gamma_pre) + len(gamma_event),
            {"prefault_median_rad": gamma_baseline, "event_min_rad": gamma_min, "drop_rad": gamma_drop, "minimum_drop_rad": minimum_drop},
        )

        idc = traces[contract["bounded_dc_response"]["channel"]]
        idc_prefault_start = event_time - bounded_prefault_window
        idc_pre = _window(idc, idc_prefault_start, event_time)
        idc_response = _window_inclusive(idc, event_time, domain_end)
        idc_baseline = median(idc_pre) if idc_pre else math.nan
        idc_peak = max((abs(value) for value in idc_response), default=math.nan)
        idc_ratio = idc_peak / abs(idc_baseline) if math.isfinite(idc_baseline) and idc_baseline else math.nan
        bound = contract["bounded_dc_response"]
        minimum_prefault = float(bound["minimum_prefault_magnitude_ka"])
        maximum_ratio = float(bound["maximum_peak_to_prefault_ratio"])
        bounded_pass = (
            math.isfinite(idc_ratio)
            and abs(idc_baseline) >= minimum_prefault
            and idc_ratio <= maximum_ratio
        )
        bounded = _check(
            "PASS" if bounded_pass else "FAIL",
            [idc.path],
            {idc.path: idc.units},
            (idc_prefault_start, domain_end),
            len(idc_pre) + len(idc_response),
            {"prefault_median_ka": idc_baseline, "peak_abs_ka": idc_peak, "peak_to_prefault_ratio": idc_ratio, "maximum_ratio": maximum_ratio, "minimum_prefault_magnitude_ka": minimum_prefault},
        )

        recovery_decl = contract["recovery"]
        recovery_start = domain_end - float(recovery_decl["minimum_hold_s"])
        recovery_selectors: list[str] = []
        recovery_units: dict[str, str] = {}
        recovery_metrics: dict[str, Any] = {"channels": {}}
        recovery_pass = True
        recovery_count = 0
        for declaration in recovery_decl["channels"]:
            path = str(declaration["path"])
            trace = traces[path]
            recovery_selectors.append(path)
            recovery_units[path] = trace.units
            prefault_values = _window(trace, disturbance_prefault_start, event_time)
            recovery_values = _window_inclusive(trace, recovery_start, domain_end)
            baseline = median(prefault_values) if prefault_values else math.nan
            band = max(abs(baseline) * float(declaration["relative_band"]), float(declaration["absolute_floor"]))
            max_deviation = max((abs(value - baseline) for value in recovery_values), default=math.inf)
            channel_pass = bool(recovery_values) and math.isfinite(baseline) and max_deviation <= band
            recovery_pass = recovery_pass and channel_pass
            recovery_count += len(recovery_values)
            recovery_metrics["channels"][path] = {"prefault_median": baseline, "band": band, "max_deviation": max_deviation, "sample_count": len(recovery_values)}
        recovery = _check("PASS" if recovery_pass else "FAIL", recovery_selectors, recovery_units, (recovery_start, domain_end), recovery_count, recovery_metrics)

        checks = {"disturbance": disturbance, "failure_indication": failure, "bounded_dc_response": bounded, "recovery": recovery}
        verdict = "PASS" if all(check["outcome"] == "PASS" for check in checks.values()) else "FAIL"
        return {"engineering_verdict": verdict, "checks": checks}
    except _DynamicEvidenceError as error:
        return {"engineering_verdict": "FAIL", "checks": _failed_checks(contract, error)}
    except (KeyError, TypeError, ValueError, OverflowError, IndexError, AttributeError) as error:
        dynamic_error = _DynamicEvidenceError("invalid_contract")
        dynamic_error.__cause__ = error
        return {"engineering_verdict": "FAIL", "checks": _failed_checks(contract, dynamic_error)}
