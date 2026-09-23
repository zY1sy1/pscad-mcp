"""Measured steady control and capacitor envelopes for the native dq path."""

from __future__ import annotations

import math
from statistics import fmean


LIMITS = {
    "pll_frequency_deviation_hz": 0.2,
    "pll_phase_error_rad": math.radians(2.0),
    "current_tracking_rms_pu": 0.05,
    "current_tracking_peak_pu": 0.10,
    "insertion_margin": 0.05,
    "capacitor_voltage_deviation_pu": 0.10,
    "station_energy_mean_deviation_pu": 0.05,
    "steady_limit_duration_s": 0.0,
}


def evaluate_native_dq_controls(trace: dict, parameters: dict, windows: dict) -> dict:
    result = {"scope": "native_dq_steady_controls_and_storage", "status": "FAIL", "model_accepted": False,
              "limits": dict(LIMITS), "checks": {}, "windows": {}}
    required = {"time"}
    for s in ("P", "V"):
        required.update(s + "_" + n for n in (
            "PLL_FREQUENCY", "PLL_ERROR", "PLL_LOCKED", "PLL_LIMITED", "PLL_INTEGRATOR", "BLOCK",
            "ID_MEASURED", "IQ_MEASURED", "ID_REFERENCE", "IQ_REFERENCE", "ID_INTEGRATOR", "IQ_INTEGRATOR",
            "LIMIT_ACTIVE", "LIMIT_DURATION",
        ))
        for p in "ABC":
            for q in ("UPPER", "LOWER"):
                required.update((f"{s}_{p}_{q}_VCAP", f"{s}_{p}_{q}_W", f"{s}_M_{p}_{q}_RAW"))
    time = trace.get("time", ())
    if not required <= trace.keys():
        result["missing_channels"] = sorted(required - trace.keys())
        return result
    if len(time) < 2 or any(len(trace[n]) != len(time) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in trace[n]) for n in required) or any(b <= a for a, b in zip(time, time[1:])):
        result["error"] = "Control evidence is nonfinite or unaligned"
        return result
    if not windows:
        result["error"] = "Operating windows are required"
        return result
    power = parameters["active_power_order_mw"]
    reactive = parameters["reactive_power_order_mvar"]
    vdc = parameters["vdc_order_kv"]
    frequency = parameters["frequency_hz"]
    capacitance = parameters["arm"]["C_eq_F"]
    station_energy_target = 0.75 * capacitance * vdc**2
    for name, (start, end) in windows.items():
        indexes = [i for i, instant in enumerate(time) if start <= instant <= end]
        if len(indexes) < 2 or time[0] > start or time[-1] < end:
            result["error"] = "A declared control window is incomplete"
            return result
        result["windows"][name] = window = {}
        for s, parameter_name in (("P", "station_p_valve_voltage_kv"), ("V", "station_vdc_valve_voltage_kv")):
            current_base = math.sqrt(2.0) * math.hypot(power, reactive) / (math.sqrt(3.0) * parameters[parameter_name])
            if current_base <= 0 or station_energy_target <= 0:
                raise ValueError("Control envelope ratings must be positive")
            values = lambda suffix: [trace[s + "_" + suffix][i] for i in indexes]
            metrics = {
                "pll_frequency_max_deviation_hz": max(abs(v - frequency) for v in values("PLL_FREQUENCY")),
                "pll_phase_max_error_rad": max(abs(v) for v in values("PLL_ERROR")),
                "pll_integrator_max_rad_per_s": max(abs(v) for v in values("PLL_INTEGRATOR")),
                "limit_duration_increment_s": max(values("LIMIT_DURATION")) - min(values("LIMIT_DURATION")),
            }
            checks = {
                "pll_locked": all(v >= 0.5 for v in values("PLL_LOCKED")),
                "pll_frequency": metrics["pll_frequency_max_deviation_hz"] <= LIMITS["pll_frequency_deviation_hz"],
                "pll_phase": metrics["pll_phase_max_error_rad"] <= LIMITS["pll_phase_error_rad"],
                "pll_integrator": metrics["pll_integrator_max_rad_per_s"] <= 2 * math.pi * 5.0,
                "pll_unlimited": all(v < 0.5 for v in values("PLL_LIMITED")),
                "deblocked": all(v < 0.5 for v in values("BLOCK")),
                "no_steady_saturation": all(v < 0.5 for v in values("LIMIT_ACTIVE")) and metrics["limit_duration_increment_s"] <= LIMITS["steady_limit_duration_s"],
            }
            for axis in ("D", "Q"):
                error = [trace[f"{s}_I{axis}_MEASURED"][i] - trace[f"{s}_I{axis}_REFERENCE"][i] for i in indexes]
                metrics[axis + "_tracking_rms_pu"] = math.sqrt(fmean(x*x for x in error)) / current_base
                metrics[axis + "_tracking_peak_pu"] = max(abs(x) for x in error) / current_base
                checks[axis + "_current_tracking"] = metrics[axis + "_tracking_rms_pu"] <= LIMITS["current_tracking_rms_pu"] and metrics[axis + "_tracking_peak_pu"] <= LIMITS["current_tracking_peak_pu"]
                checks[axis + "_integrator"] = max(abs(x) for x in values(f"I{axis}_INTEGRATOR")) <= 0.5 * vdc
            arms = [f"{s}_{p}_{q}" for p in "ABC" for q in ("UPPER", "LOWER")]
            metrics["minimum_insertion_margin"] = min(min(trace[f"{s}_M_{p}_{q}_RAW"][i], 1 - trace[f"{s}_M_{p}_{q}_RAW"][i]) for p in "ABC" for q in ("UPPER", "LOWER") for i in indexes)
            metrics["capacitor_voltage_max_deviation_pu"] = max(abs(2 * trace[arm + "_VCAP"][i] / vdc - 1) for arm in arms for i in indexes)
            mean_energy = fmean(sum(trace[arm + "_W"][i] for arm in arms) for i in indexes)
            metrics["station_energy_mean_deviation_pu"] = abs(mean_energy / station_energy_target - 1)
            checks["insertion_margin"] = metrics["minimum_insertion_margin"] >= LIMITS["insertion_margin"]
            checks["capacitor_voltage"] = metrics["capacitor_voltage_max_deviation_pu"] <= LIMITS["capacitor_voltage_deviation_pu"]
            checks["station_energy"] = metrics["station_energy_mean_deviation_pu"] <= LIMITS["station_energy_mean_deviation_pu"]
            window[s] = metrics
            result["checks"].update({f"{name}:{s}:{key}": value for key, value in checks.items()})
    result["failed_checks"] = [name for name, passed in result["checks"].items() if not passed]
    result["status"] = "FAIL" if result["failed_checks"] else "PASS"
    return result
