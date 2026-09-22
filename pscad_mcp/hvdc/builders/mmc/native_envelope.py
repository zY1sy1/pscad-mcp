"""Independent steady-state envelopes; not full MMC or golden acceptance."""

from __future__ import annotations

import math
from statistics import fmean


# Voltage/current limits retain the public scenario contract. P/Q tracking
# limits are explicit for this additional steady operating diagnostic.
LIMITS = {
    "dc_voltage_deviation_pu": 0.10,
    "dc_current_peak_pu": 1.25,
    "active_power_nrmse": 0.05,
    "reactive_power_rms_pu": 0.05,
}


def evaluate_native_steady_envelope(trace: dict, *, power_mw: float, voltage_kv: float,
                                    reactive_mvar: float = 0.0,
                                    forward_window_s: tuple[float, float] = (0.6, 0.9),
                                    reverse_window_s: tuple[float, float] = (1.6, 1.9)) -> dict:
    result = {
        "scope": "native_steady_operating_envelope",
        "status": "FAIL",
        "model_accepted": False,
        "limits": dict(LIMITS),
        "checks": {},
        "windows": {},
    }
    if any(isinstance(v, bool) or not math.isfinite(v) for v in (power_mw, voltage_kv, reactive_mvar)) or min(power_mw, voltage_kv) <= 0:
        raise ValueError("Envelope ratings must be finite and positive")
    required = {"time", "P_P", "P_Q", "V_Q", "P_VDC", "V_VDC", "P_IDC", "V_IDC"}
    if not required <= trace.keys():
        result["missing_channels"] = sorted(required - trace.keys())
        return result
    time = trace["time"]
    if len(time) < 2 or any(b <= a for a, b in zip(time, time[1:])) or any(
        len(trace[name]) != len(time)
        or any(isinstance(v, bool) or not math.isfinite(v) for v in trace[name])
        for name in required
    ):
        result["error"] = "Missing, unaligned or nonfinite samples"
        return result
    for window, start, end, direction in (
        ("forward", *forward_window_s, 1.0), ("reverse", *reverse_window_s, -1.0)
    ):
        indexes = [i for i, instant in enumerate(time) if start <= instant <= end]
        if len(indexes) < 2 or time[indexes[0]] > start + 1.1e-4 or time[indexes[-1]] < end - 1.1e-4:
            result["error"] = "Steady operating window is incomplete"
            return result
        metrics = {}
        actual_power = [trace["P_P"][i] for i in indexes]
        metrics["active_power_mean_mw"] = fmean(actual_power)
        metrics["active_power_nrmse"] = math.sqrt(fmean(
            (p - direction * power_mw) ** 2 for p in actual_power
        )) / power_mw
        result["checks"][window + ":active_power_tracking"] = metrics["active_power_nrmse"] <= LIMITS["active_power_nrmse"]
        for station in ("P", "V"):
            metrics[station] = station_metrics = {
                "dc_voltage_mean_kv": fmean(trace[station + "_VDC"][i] for i in indexes),
                "dc_voltage_max_deviation_pu": max(abs(trace[station + "_VDC"][i] / voltage_kv - 1) for i in indexes),
                "dc_current_peak_pu": max(abs(trace[station + "_IDC"][i]) for i in indexes) / (power_mw / voltage_kv),
                "reactive_power_rms_pu": math.sqrt(fmean((trace[station + "_Q"][i] - reactive_mvar) ** 2 for i in indexes)) / power_mw,
            }
            for metric, limit in (
                ("dc_voltage_max_deviation_pu", "dc_voltage_deviation_pu"),
                ("dc_current_peak_pu", "dc_current_peak_pu"),
                ("reactive_power_rms_pu", "reactive_power_rms_pu"),
            ):
                result["checks"][f"{window}:{station}:{metric}"] = station_metrics[metric] <= LIMITS[limit]
        result["windows"][window] = metrics
    result["failed_checks"] = [name for name, value in result["checks"].items() if not value]
    result["status"] = "FAIL" if result["failed_checks"] else "PASS"
    return result
