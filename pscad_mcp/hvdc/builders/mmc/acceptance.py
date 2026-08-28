"""Evidence-preserving MMC golden and physical acceptance checks."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..common.records import JsonRecord, freeze
from .electrical import arm_currents, arm_energy, clip_modulation
from .models import MmcAcceptanceCheck


class AcceptanceState(str, Enum):
    OBSERVED = "observed"
    DERIVED = "derived"
    MISSING = "missing"
    INVALID = "invalid"


AVM_LIMITATIONS = (
    "submodule_balance",
    "semiconductor_switching_stress",
    "switching_harmonics",
    "dc_fault_blocking",
)
_DEFAULT_UNITS = {
    "vdc": "kV",
    "p_ac": "MW",
    "q_ac": "MVAr",
    "arm_current": "kA",
}


@dataclass(frozen=True)
class SampleEvidence(JsonRecord):
    channel: str
    state: str
    units: str | None = None
    time: tuple[float, ...] = ()
    values: tuple[float, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class CheckResult(JsonRecord):
    name: str
    state: str
    passed: bool
    observed: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed", freeze(self.observed))
        object.__setattr__(self, "expected", freeze(self.expected))


@dataclass(frozen=True)
class MmcAcceptanceReport(JsonRecord):
    verdict: str
    checks: tuple[CheckResult, ...]
    limitations: tuple[dict[str, Any], ...]
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "checks", tuple(self.checks))
        object.__setattr__(self, "limitations", tuple(freeze(item) for item in self.limitations))
        object.__setattr__(self, "evidence", freeze(self.evidence))


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _record_result(name: str, state: AcceptanceState, passed: bool, *, required: bool = True, observed: Mapping[str, Any] | None = None, expected: Mapping[str, Any] | None = None, reason: str | None = None) -> CheckResult:
    return CheckResult(name, state.value, passed, dict(observed or {}), dict(expected or {}), reason, required)


def normalize_samples(samples: Mapping[str, Any] | Sequence[Mapping[str, Any]], expected_units: Mapping[str, str] | None = None) -> dict[str, SampleEvidence]:
    """Normalize samples without filling absent values or extrapolating them."""

    if isinstance(samples, Mapping) and isinstance(samples.get("channels"), Mapping):
        samples = samples["channels"]
    records: list[tuple[str, Any]] = []
    if isinstance(samples, Mapping):
        records = list(samples.items())
    elif isinstance(samples, Sequence) and not isinstance(samples, (str, bytes, bytearray)):
        for item in samples:
            if not isinstance(item, Mapping) or not isinstance(item.get("channel"), str):
                continue
            records.append((item["channel"], item))
    result: dict[str, SampleEvidence] = {}
    expected_units = dict(expected_units or {})
    for channel, raw in records:
        if channel in result:
            result[channel] = SampleEvidence(channel, AcceptanceState.INVALID.value, reason="ambiguous duplicate channel")
            continue
        if not isinstance(channel, str) or not isinstance(raw, Mapping):
            result[str(channel)] = SampleEvidence(str(channel), AcceptanceState.INVALID.value, reason="sample must be an object")
            continue
        units = raw.get("units")
        times = raw.get("time")
        values = raw.get("values")
        if not times or not values:
            result[channel] = SampleEvidence(channel, AcceptanceState.MISSING.value, units if isinstance(units, str) else None, reason="samples are missing or empty")
            continue
        if not isinstance(units, str) or (channel in expected_units and units != expected_units[channel]) or (channel in _DEFAULT_UNITS and units != _DEFAULT_UNITS[channel] and channel not in expected_units):
            result[channel] = SampleEvidence(channel, AcceptanceState.INVALID.value, units if isinstance(units, str) else None, reason="units do not match the declared selector")
            continue
        if not isinstance(times, Sequence) or isinstance(times, (str, bytes, bytearray)) or not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)) or len(times) != len(values):
            result[channel] = SampleEvidence(channel, AcceptanceState.INVALID.value, units, reason="time and values must be aligned arrays")
            continue
        time_values = tuple(float(value) for value in times) if all(_finite(value) for value in times) else ()
        value_values = tuple(float(value) for value in values) if all(_finite(value) for value in values) else ()
        if not time_values or not value_values:
            result[channel] = SampleEvidence(channel, AcceptanceState.INVALID.value, units, reason="time and values must be finite")
            continue
        if any(right <= left for left, right in zip(time_values, time_values[1:])):
            result[channel] = SampleEvidence(channel, AcceptanceState.INVALID.value, units, time_values, value_values, "time must be strictly increasing")
            continue
        result[channel] = SampleEvidence(channel, AcceptanceState.OBSERVED.value, units, time_values, value_values)
    return result


def _window(sample: SampleEvidence, start: float, end: float) -> bool:
    return bool(sample.time) and _finite(start) and _finite(end) and start <= end and sample.time[0] <= start and sample.time[-1] >= end


def compare_golden(observed: Mapping[str, Any], golden: Mapping[str, Any], *, scale_floor: float = 1.0, nrmse_max: float = 0.05, max_error_max: float = 0.1) -> CheckResult:
    """Compare aligned finite channels without interpolation or extrapolation."""

    if not isinstance(golden, Mapping):
        return _record_result("golden", AcceptanceState.INVALID, False, reason="golden evidence must be an object")
    source = golden.get("source")
    if isinstance(source, Mapping):
        if source.get("builder_generated") is True:
            return _record_result("golden", AcceptanceState.INVALID, False, reason="builder-generated golden data cannot be an acceptance reference")
        status = source.get("status")
        if isinstance(status, str) and any(token in status.lower() for token in ("required", "missing", "unavailable", "pending")):
            return _record_result("golden", AcceptanceState.MISSING, False, reason="independently reviewed golden reference is unavailable")
    obs = normalize_samples(observed)
    ref = normalize_samples(golden)
    if not ref:
        return _record_result("golden", AcceptanceState.MISSING, False, reason="golden contains no reviewed waveform channels")
    if not _finite(scale_floor) or float(scale_floor) <= 0:
        return _record_result("golden", AcceptanceState.INVALID, False, reason="scale_floor must be positive and finite")
    golden_channels = golden.get("channels") if isinstance(golden.get("channels"), Mapping) else golden
    metrics: dict[str, Any] = {}
    for channel, reference in ref.items():
        actual = obs.get(channel)
        if actual is None or actual.state == AcceptanceState.MISSING.value or reference.state == AcceptanceState.MISSING.value:
            return _record_result("golden", AcceptanceState.MISSING, False, reason=f"channel {channel} is missing")
        if actual.state != AcceptanceState.OBSERVED.value or reference.state != AcceptanceState.OBSERVED.value:
            return _record_result("golden", AcceptanceState.INVALID, False, reason=f"channel {channel} is invalid")
        if actual.units != reference.units or actual.time != reference.time:
            return _record_result("golden", AcceptanceState.INVALID, False, reason=f"channel {channel} is not unit-aligned")
        errors = [left - right for left, right in zip(actual.values, reference.values)]
        channel_reference = golden_channels.get(channel, {}) if isinstance(golden_channels, Mapping) else {}
        if not isinstance(channel_reference, Mapping):
            channel_reference = {}
        channel_scale_floor = channel_reference.get("scale_floor", scale_floor)
        channel_nrmse_max = channel_reference.get("nrmse_max", nrmse_max)
        channel_max_error_max = channel_reference.get("max_error_max", max_error_max)
        if not all(_finite(value) and float(value) > 0 for value in (channel_scale_floor, channel_nrmse_max, channel_max_error_max)):
            return _record_result("golden", AcceptanceState.INVALID, False, reason=f"golden limits for channel {channel} are invalid")
        scale = max(float(channel_scale_floor), max((abs(value) for value in reference.values), default=0.0))
        nrmse = math.sqrt(sum(error * error for error in errors) / len(errors)) / scale
        maximum = max((abs(error) for error in errors), default=0.0) / scale
        metrics[channel] = {
            "nrmse": nrmse,
            "max_normalized_error": maximum,
            "scale_floor": float(channel_scale_floor),
            "nrmse_max": float(channel_nrmse_max),
            "max_error_max": float(channel_max_error_max),
        }
    passed = all(value["nrmse"] <= value["nrmse_max"] and value["max_normalized_error"] <= value["max_error_max"] for value in metrics.values())
    return _record_result("golden", AcceptanceState.DERIVED, passed, observed=metrics, expected={"nrmse_max": nrmse_max, "max_error_max": max_error_max})


def arm_current_check(i_dc: float, i_phase: float, i_circulating: float, upper: float, lower: float, tolerance: float = 1e-9) -> CheckResult:
    try:
        expected_upper, expected_lower = arm_currents(i_dc, i_phase, i_circulating)
        passed = abs(float(upper) - expected_upper) <= tolerance and abs(float(lower) - expected_lower) <= tolerance
    except Exception:
        return _record_result("arm_current_equation", AcceptanceState.INVALID, False, reason="arm current evidence is invalid")
    return _record_result("arm_current_equation", AcceptanceState.DERIVED, passed, observed={"upper": upper, "lower": lower}, expected={"upper": expected_upper, "lower": expected_lower})


def energy_consistency_check(energy_j: float, capacitance_f: float, capacitor_voltage_v: float, tolerance: float = 1e-9) -> CheckResult:
    try:
        expected = arm_energy(capacitance_f, capacitor_voltage_v)
        passed = _finite(energy_j) and float(energy_j) >= 0 and abs(float(energy_j) - expected) <= tolerance * max(1.0, abs(expected))
    except Exception:
        return _record_result("energy_consistency", AcceptanceState.INVALID, False, reason="energy evidence is invalid")
    return _record_result("energy_consistency", AcceptanceState.DERIVED, passed, observed={"energy_j": energy_j}, expected={"energy_j": expected})


def modulation_check(unclipped: float, clipped: float, margin: float, saturation_duration_s: float, tolerance: float = 1e-9) -> CheckResult:
    try:
        expected_unclipped, expected_clipped, expected_margin, saturated = clip_modulation(unclipped)
        passed = abs(float(clipped) - expected_clipped) <= tolerance and abs(float(margin) - expected_margin) <= tolerance and _finite(saturation_duration_s) and float(saturation_duration_s) >= 0 and ((float(unclipped) > 1 or float(unclipped) < 0) == saturated)
    except Exception:
        return _record_result("modulation", AcceptanceState.INVALID, False, reason="modulation evidence is invalid")
    return _record_result("modulation", AcceptanceState.DERIVED, passed, observed={"unclipped": unclipped, "clipped": clipped, "margin": margin, "saturation_duration_s": saturation_duration_s}, expected={"clipped": expected_clipped, "margin": expected_margin})


def dc_link_check(
    positive_kv: float,
    negative_kv: float,
    nominal_vdc_kv: float,
    *,
    voltage_tolerance_kv: float = 1e-6,
    symmetry_tolerance_kv: float = 1e-6,
) -> CheckResult:
    """Check positive/negative pole polarity, pole-to-pole magnitude, and symmetry."""

    values = (positive_kv, negative_kv, nominal_vdc_kv, voltage_tolerance_kv, symmetry_tolerance_kv)
    passed = all(_finite(value) for value in values)
    if passed:
        positive = float(positive_kv)
        negative = float(negative_kv)
        nominal = float(nominal_vdc_kv)
        voltage_tolerance = float(voltage_tolerance_kv)
        symmetry_tolerance = float(symmetry_tolerance_kv)
        pole_to_pole = positive - negative
        symmetry_error = positive + negative
        passed = (
            nominal > 0
            and voltage_tolerance >= 0
            and symmetry_tolerance >= 0
            and positive > 0
            and negative < 0
            and abs(pole_to_pole - nominal) <= voltage_tolerance
            and abs(symmetry_error) <= symmetry_tolerance
        )
    else:
        pole_to_pole = symmetry_error = None
    return _record_result(
        "dc_link",
        AcceptanceState.DERIVED if passed or all(_finite(value) for value in values) else AcceptanceState.INVALID,
        passed,
        observed={"positive_kv": positive_kv, "negative_kv": negative_kv, "pole_to_pole_kv": pole_to_pole, "symmetry_error_kv": symmetry_error},
        expected={"nominal_vdc_kv": nominal_vdc_kv, "voltage_tolerance_kv": voltage_tolerance_kv, "symmetry_tolerance_kv": symmetry_tolerance_kv},
    )


def dc_power_check(dc_voltage_kv: float, dc_current_ka: float, requested_power_mw: float, tolerance_mw: float = 1e-6) -> CheckResult:
    """Check signed DC power using kV*kA=MW and preserve current direction."""

    values = (dc_voltage_kv, dc_current_ka, requested_power_mw, tolerance_mw)
    valid = all(_finite(value) for value in values)
    computed = float(dc_voltage_kv) * float(dc_current_ka) if valid else None
    passed = valid and float(dc_voltage_kv) > 0 and float(tolerance_mw) >= 0 and abs(computed - float(requested_power_mw)) <= float(tolerance_mw) * max(1.0, abs(float(requested_power_mw)))
    return _record_result(
        "dc_power",
        AcceptanceState.DERIVED if valid else AcceptanceState.INVALID,
        passed,
        observed={"dc_power_mw": computed, "dc_voltage_kv": dc_voltage_kv, "dc_current_ka": dc_current_ka},
        expected={"requested_power_mw": requested_power_mw, "tolerance_mw": tolerance_mw},
    )


def ac_power_tracking_check(
    active_power_mw: float,
    reactive_power_mvar: float,
    active_command_mw: float,
    reactive_command_mvar: float,
    active_tolerance_mw: float = 1e-6,
    reactive_tolerance_mvar: float = 1e-6,
) -> CheckResult:
    """Check AC P/Q tracking independently of the DC terminal balance."""

    values = (active_power_mw, reactive_power_mvar, active_command_mw, reactive_command_mvar, active_tolerance_mw, reactive_tolerance_mvar)
    valid = all(_finite(value) for value in values)
    passed = valid and float(active_tolerance_mw) >= 0 and float(reactive_tolerance_mvar) >= 0 and abs(float(active_power_mw) - float(active_command_mw)) <= float(active_tolerance_mw) and abs(float(reactive_power_mvar) - float(reactive_command_mvar)) <= float(reactive_tolerance_mvar)
    return _record_result(
        "ac_power_tracking",
        AcceptanceState.DERIVED if valid else AcceptanceState.INVALID,
        passed,
        observed={"active_power_mw": active_power_mw, "reactive_power_mvar": reactive_power_mvar},
        expected={"active_command_mw": active_command_mw, "reactive_command_mvar": reactive_command_mvar, "active_tolerance_mw": active_tolerance_mw, "reactive_tolerance_mvar": reactive_tolerance_mvar},
    )


def station_energy_check(arm_energies_j: Sequence[float], total_energy_j: float, minimum_energy_j: float = 0.0, tolerance: float = 1e-9) -> CheckResult:
    """Check arm-energy positivity and the station total-energy identity."""

    try:
        energies = tuple(float(value) for value in arm_energies_j)
    except (TypeError, ValueError, OverflowError):
        energies = ()
    valid = bool(energies) and all(_finite(value) for value in energies + (total_energy_j, minimum_energy_j, tolerance))
    total = sum(energies) if valid else None
    passed = valid and float(minimum_energy_j) >= 0 and float(tolerance) >= 0 and all(value >= float(minimum_energy_j) for value in energies) and abs(total - float(total_energy_j)) <= float(tolerance) * max(1.0, abs(float(total_energy_j)))
    return _record_result(
        "station_energy",
        AcceptanceState.DERIVED if valid else AcceptanceState.INVALID,
        passed,
        observed={"arm_energies_j": list(energies), "sum_energy_j": total},
        expected={"total_energy_j": total_energy_j, "minimum_energy_j": minimum_energy_j},
    )


def energy_profile_check(energy_values_j: Sequence[float], ripple_fraction_limit: float, *, minimum_energy_j: float = 0.0) -> CheckResult:
    """Check finite positive energy samples and peak-to-peak ripple fraction."""

    try:
        values = tuple(float(value) for value in energy_values_j)
    except (TypeError, ValueError, OverflowError):
        values = ()
    valid = bool(values) and all(_finite(value) for value in values + (ripple_fraction_limit, minimum_energy_j))
    mean = sum(values) / len(values) if valid else None
    ripple = (max(values) - min(values)) / max(1.0, abs(mean)) if valid else None
    passed = valid and float(ripple_fraction_limit) >= 0 and float(minimum_energy_j) >= 0 and all(value >= float(minimum_energy_j) for value in values) and ripple <= float(ripple_fraction_limit)
    return _record_result(
        "energy_ripple",
        AcceptanceState.DERIVED if valid else AcceptanceState.INVALID,
        passed,
        observed={"minimum_j": min(values) if values else None, "maximum_j": max(values) if values else None, "ripple_fraction": ripple},
        expected={"ripple_fraction_limit": ripple_fraction_limit, "minimum_energy_j": minimum_energy_j},
    )


def capacitance_consistency_check(energy_j: float, capacitance_f: float, capacitor_voltage_v: float, tolerance: float = 1e-9) -> CheckResult:
    """Check ``W=0.5*C_eq*V_cap_eq²`` with an explicit capacitance contract."""

    try:
        expected = arm_energy(capacitance_f, capacitor_voltage_v)
        valid = all(_finite(value) for value in (energy_j, capacitance_f, capacitor_voltage_v, tolerance))
        passed = valid and float(energy_j) >= 0 and float(tolerance) >= 0 and abs(float(energy_j) - expected) <= float(tolerance) * max(1.0, abs(expected))
    except Exception:
        expected = None
        valid = False
        passed = False
    return _record_result(
        "capacitance_consistency",
        AcceptanceState.DERIVED if valid else AcceptanceState.INVALID,
        passed,
        observed={"energy_j": energy_j, "capacitance_f": capacitance_f, "capacitor_voltage_v": capacitor_voltage_v},
        expected={"energy_j": expected, "tolerance": tolerance},
    )


def power_balance_check(ac_power_mw: float, dc_power_mw: float, loss_mw: float, tolerance: float = 1e-6) -> CheckResult:
    passed = all(_finite(value) for value in (ac_power_mw, dc_power_mw, loss_mw)) and abs(float(ac_power_mw) - float(dc_power_mw) - float(loss_mw)) <= tolerance * max(1.0, abs(float(ac_power_mw)), abs(float(dc_power_mw)))
    return _record_result("power_balance", AcceptanceState.DERIVED, passed, observed={"ac_power_mw": ac_power_mw, "dc_power_mw": dc_power_mw, "loss_mw": loss_mw}, reason=None if passed else "AC/DC power and loss balance is outside tolerance")


def phase_kcl_check(i_phase: float, upper: float, lower: float, i_dc: float, i_circulating: float, tolerance: float = 1e-9) -> CheckResult:
    try:
        expected_upper, expected_lower = arm_currents(i_dc, i_phase, i_circulating)
        passed = abs(float(upper) - expected_upper) <= tolerance and abs(float(lower) - expected_lower) <= tolerance
    except Exception:
        passed = False
        expected_upper = expected_lower = None
    return _record_result("phase_kcl", AcceptanceState.DERIVED if expected_upper is not None else AcceptanceState.INVALID, passed, observed={"upper": upper, "lower": lower}, expected={"upper": expected_upper, "lower": expected_lower})


def circulating_current_check(rms: float, second_harmonic: float, rms_limit: float, second_harmonic_limit: float) -> CheckResult:
    passed = all(_finite(value) and float(value) >= 0 for value in (rms, second_harmonic, rms_limit, second_harmonic_limit)) and float(rms) <= float(rms_limit) and float(second_harmonic) <= float(second_harmonic_limit)
    return _record_result("circulating_current", AcceptanceState.DERIVED, passed, observed={"rms": rms, "second_harmonic": second_harmonic}, expected={"rms_limit": rms_limit, "second_harmonic_limit": second_harmonic_limit})


def pll_check(
    locked: bool,
    frequency_hz: float,
    nominal_hz: float,
    frequency_tolerance_hz: float,
    integrator_abs: float,
    integrator_limit: float,
    *,
    dq_error: float | None = None,
    dq_error_limit: float | None = None,
    control_limit_duration_s: float = 0.0,
    control_limit_duration_max_s: float | None = None,
) -> CheckResult:
    """Check PLL lock, frequency/dq tracking, integrator, and limit duration."""

    numeric = (frequency_hz, nominal_hz, frequency_tolerance_hz, integrator_abs, integrator_limit, control_limit_duration_s)
    optional = (dq_error, dq_error_limit, control_limit_duration_max_s)
    valid = isinstance(locked, bool) and all(_finite(value) for value in numeric) and all(value is None or _finite(value) for value in optional)
    passed = valid and locked and float(frequency_tolerance_hz) >= 0 and float(integrator_abs) >= 0 and float(integrator_limit) >= 0 and float(control_limit_duration_s) >= 0 and abs(float(frequency_hz) - float(nominal_hz)) <= float(frequency_tolerance_hz) and float(integrator_abs) <= float(integrator_limit)
    if passed and dq_error is not None:
        passed = dq_error_limit is not None and float(dq_error_limit) >= 0 and abs(float(dq_error)) <= float(dq_error_limit)
    if passed and control_limit_duration_max_s is not None:
        passed = float(control_limit_duration_max_s) >= 0 and float(control_limit_duration_s) <= float(control_limit_duration_max_s)
    return _record_result(
        "pll",
        AcceptanceState.DERIVED if valid else AcceptanceState.INVALID,
        passed,
        observed={"locked": locked, "frequency_hz": frequency_hz, "integrator_abs": integrator_abs, "dq_error": dq_error, "control_limit_duration_s": control_limit_duration_s},
        expected={"nominal_hz": nominal_hz, "frequency_tolerance_hz": frequency_tolerance_hz, "integrator_limit": integrator_limit, "dq_error_limit": dq_error_limit, "control_limit_duration_max_s": control_limit_duration_max_s},
    )


def precharge_check(
    current: float,
    current_limit: float,
    ready: bool,
    *,
    energy_converged: bool | None = None,
    deblocked: bool = False,
    protection_active: bool = False,
) -> CheckResult:
    """Check bounded precharge, energy convergence, and deblock ordering."""

    valid = isinstance(ready, bool) and isinstance(deblocked, bool) and isinstance(protection_active, bool) and (energy_converged is None or isinstance(energy_converged, bool)) and _finite(current) and _finite(current_limit)
    passed = valid and ready and not deblocked and not protection_active and float(current) >= 0 and float(current_limit) >= 0 and float(current) <= float(current_limit) and (energy_converged is None or energy_converged)
    return _record_result(
        "precharge",
        AcceptanceState.DERIVED if valid else AcceptanceState.INVALID,
        passed,
        observed={"current": current, "ready": ready, "energy_converged": energy_converged, "deblocked": deblocked, "protection_active": protection_active},
        expected={"current_limit": current_limit, "energy_converged": True, "deblocked": False, "protection_active": False},
    )


def reversal_check(power_order: Sequence[float], measured_power: Sequence[float], *, zero_cross_index: int, max_overshoot: float) -> CheckResult:
    try:
        orders = tuple(float(value) for value in power_order)
        measured = tuple(float(value) for value in measured_power)
        passed = len(orders) == len(measured) and 0 < zero_cross_index < len(measured) and orders[0] > 0 and orders[-1] < 0 and measured[zero_cross_index - 1] >= 0 and measured[zero_cross_index] <= max_overshoot and measured[-1] < 0 and _finite(max_overshoot) and max_overshoot >= 0
    except (TypeError, ValueError, OverflowError):
        passed = False
    return _record_result("reversal", AcceptanceState.DERIVED, passed, observed={"zero_cross_index": zero_cross_index}, expected={"max_overshoot": max_overshoot})


def reverse_steady_check(power_samples: Sequence[float], current_samples: Sequence[float], *, power_limit: float, current_limit: float) -> CheckResult:
    """Check negative-power/current direction and bounded reverse steady state."""

    try:
        power = tuple(float(value) for value in power_samples)
        current = tuple(float(value) for value in current_samples)
        valid = bool(power) and len(power) == len(current) and all(_finite(value) for value in power + current + (power_limit, current_limit))
        passed = valid and float(power_limit) >= 0 and float(current_limit) >= 0 and all(value < 0 and abs(value) <= float(power_limit) for value in power) and all(value < 0 and abs(value) <= float(current_limit) for value in current)
    except (TypeError, ValueError, OverflowError):
        valid = False
        passed = False
        power = current = ()
    return _record_result(
        "reverse_steady",
        AcceptanceState.DERIVED if valid else AcceptanceState.INVALID,
        passed,
        observed={"power_samples": list(power), "current_samples": list(current)},
        expected={"power_limit": power_limit, "current_limit": current_limit},
    )


def _physical_contract_result(physical_checks: Sequence[CheckResult]) -> CheckResult:
    """Require independently computed physical evidence before a PASS verdict."""

    if not physical_checks:
        return _record_result(
            "physical_contract",
            AcceptanceState.MISSING,
            False,
            reason="independent physical acceptance evidence is required",
        )
    if any(not isinstance(check, CheckResult) for check in physical_checks):
        return _record_result(
            "physical_contract",
            AcceptanceState.INVALID,
            False,
            reason="physical evidence must contain CheckResult records",
        )
    names = [check.name for check in physical_checks]
    if any(not isinstance(name, str) or not name.strip() for name in names):
        return _record_result(
            "physical_contract",
            AcceptanceState.INVALID,
            False,
            reason="physical evidence check names must be non-empty strings",
        )
    if len(set(names)) != len(names) or "physical_contract" in names:
        return _record_result(
            "physical_contract",
            AcceptanceState.INVALID,
            False,
            reason="physical evidence check names must be unique",
        )
    if any(not isinstance(check.passed, bool) for check in physical_checks):
        return _record_result(
            "physical_contract",
            AcceptanceState.INVALID,
            False,
            reason="physical evidence pass flags must be boolean",
        )
    missing = [check.name for check in physical_checks if check.state == AcceptanceState.MISSING.value]
    if missing:
        return _record_result(
            "physical_contract",
            AcceptanceState.MISSING,
            False,
            observed={"check_count": len(physical_checks), "checks": names, "missing": missing},
            expected={"all_required_checks_observed": True},
            reason="one or more physical checks have missing evidence",
        )
    invalid = [
        check.name
        for check in physical_checks
        if check.state not in {AcceptanceState.OBSERVED.value, AcceptanceState.DERIVED.value}
    ]
    if invalid:
        return _record_result(
            "physical_contract",
            AcceptanceState.INVALID,
            False,
            observed={"check_count": len(physical_checks), "checks": names, "invalid": invalid},
            expected={"allowed_states": [AcceptanceState.OBSERVED.value, AcceptanceState.DERIVED.value]},
            reason="physical checks must be observed or derived",
        )
    failed = [check.name for check in physical_checks if check.required and not check.passed]
    if failed:
        return _record_result(
            "physical_contract",
            AcceptanceState.DERIVED,
            False,
            observed={"check_count": len(physical_checks), "checks": names, "failed_required": failed},
            expected={"all_required_checks_passed": True},
            reason="one or more required physical checks failed",
        )
    return _record_result(
        "physical_contract",
        AcceptanceState.DERIVED,
        True,
        observed={"check_count": len(physical_checks), "checks": names},
        expected={"all_required_checks_passed": True},
    )


def evaluate_acceptance(samples: Mapping[str, Any] | Sequence[Mapping[str, Any]], checks: Sequence[MmcAcceptanceCheck], *, golden: Mapping[str, Any] | None = None, physical_checks: Sequence[CheckResult] = ()) -> MmcAcceptanceReport:
    """Evaluate windows, reviewed golden data, and independent physical checks."""

    required_units: dict[str, str] = {}
    for check in checks:
        channels = check.expected.get("channels", ()) if isinstance(check.expected, Mapping) else ()
        if isinstance(channels, Sequence) and not isinstance(channels, (str, bytes, bytearray)):
            for channel in channels:
                if isinstance(channel, str):
                    required_units[channel] = check.units
    normalized = normalize_samples(samples, required_units)
    results: list[CheckResult] = []
    required_names = ("precharge_ready", "forward_steady", "power_reversal", "reverse_steady")
    if tuple(check.name for check in checks) != required_names:
        results.append(_record_result("acceptance_contract", AcceptanceState.INVALID, False, reason="the fixed acceptance contract requires four named windows"))
    for check in checks:
        channels = check.expected.get("channels", ()) if isinstance(check.expected, Mapping) else ()
        channels = tuple(channels) if isinstance(channels, Sequence) and not isinstance(channels, (str, bytes, bytearray)) else ()
        channel_results = [normalized.get(channel) for channel in channels if isinstance(channel, str)]
        if not channel_results or any(sample is None or sample.state == AcceptanceState.MISSING.value for sample in channel_results):
            results.append(_record_result(check.name, AcceptanceState.MISSING, not check.required, required=check.required, expected=check.expected, reason="required channel is missing; no zero was substituted"))
            continue
        if any(sample.state != AcceptanceState.OBSERVED.value for sample in channel_results):
            results.append(_record_result(check.name, AcceptanceState.INVALID, not check.required, required=check.required, expected=check.expected, reason="required channel is invalid"))
            continue
        if any(not _window(sample, *check.comparison_window) for sample in channel_results):
            results.append(_record_result(check.name, AcceptanceState.MISSING, not check.required, required=check.required, expected=check.expected, reason="required window is outside observed samples; no extrapolation was used"))
            continue
        times = {sample.time for sample in channel_results}
        if len(times) != 1:
            results.append(_record_result(check.name, AcceptanceState.INVALID, not check.required, required=check.required, expected=check.expected, reason="required channels are not aligned"))
            continue
        results.append(_record_result(check.name, AcceptanceState.OBSERVED, True, required=check.required, observed={"channels": list(channels), "window": list(check.comparison_window)}, expected=check.expected))
    physical_contract = _physical_contract_result(physical_checks)
    results.extend(physical_checks)
    results.append(physical_contract)
    if golden is None:
        results.append(_record_result("golden", AcceptanceState.MISSING, False, reason="an independently reviewed golden reference is required before acceptance can pass"))
    else:
        if not isinstance(golden, Mapping):
            golden_result = _record_result("golden", AcceptanceState.INVALID, False, reason="golden evidence must be an object")
        elif isinstance(golden.get("source"), Mapping) and golden["source"].get("builder_generated") is True:
            golden_result = _record_result("golden", AcceptanceState.INVALID, False, reason="builder-generated golden data cannot be an acceptance reference")
        else:
            golden_result = compare_golden(samples if isinstance(samples, Mapping) else {}, golden)
        results.append(golden_result)
    limitations = tuple({"name": limitation, "state": "not_modeled", "passed": False} for limitation in AVM_LIMITATIONS)
    required_results = [result for result in results if result.required]
    if any(not result.passed for result in required_results):
        verdict = "INCOMPLETE_ANALYSIS" if any(result.state in {AcceptanceState.MISSING.value, AcceptanceState.INVALID.value} for result in required_results if not result.passed) else "ACCEPTANCE_FAILED"
    else:
        verdict = "PASS"
    return MmcAcceptanceReport(verdict, tuple(results), limitations, {"zero_fill": False, "extrapolation": False})


run_acceptance = evaluate_acceptance


__all__ = [
    "AcceptanceState",
    "AVM_LIMITATIONS",
    "CheckResult",
    "MmcAcceptanceReport",
    "SampleEvidence",
    "ac_power_tracking_check",
    "arm_current_check",
    "capacitance_consistency_check",
    "circulating_current_check",
    "compare_golden",
    "dc_link_check",
    "dc_power_check",
    "energy_consistency_check",
    "energy_profile_check",
    "evaluate_acceptance",
    "modulation_check",
    "normalize_samples",
    "phase_kcl_check",
    "pll_check",
    "power_balance_check",
    "precharge_check",
    "reverse_steady_check",
    "reversal_check",
    "run_acceptance",
    "station_energy_check",
]
