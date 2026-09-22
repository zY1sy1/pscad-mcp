"""Measured native AVM energy, circulating-current and reversal envelopes.

These checks complement startup, network identities and dq steady checks.
Protection and fault recovery remain separate prerequisites for publication.
All windows start at observed startup events; no waveform alignment is applied.
"""

from __future__ import annotations

import bisect
import math
from statistics import fmean

from .native_energy import diagnose_native_arm_energy


LIMITS = {
    "pole_symmetry_pu": 0.01,
    "arm_energy_mean_deviation_pu": 0.05,
    "arm_energy_peak_to_peak_pu": 0.40,  # (1.1 Vnom)^2 - (0.9 Vnom)^2
    "energy_difference_mean_pu": 0.05,
    "circulating_rms_pu": 0.10,
    "circulating_second_harmonic_peak_pu": 0.10,
    "power_balance_residual_pu": 1e-6,
    "dc_voltage_deviation_pu": 0.10,
    "dc_current_peak_pu": 1.25,
    "arm_current_peak_pu": 1.25,
    "capacitor_voltage_deviation_pu": 0.10,
    "dynamic_insertion_margin": 0.02,
    "power_overshoot_pu": 0.10,
    "reversal_slew_ratio": 1.10,
    "settling_power_error_pu": 0.05,
    "settling_time_s": 0.5,
    # Direction is established outside a 0.1% rated-power measurement band.
    # Report both the command zero and the measured direction transition.
    "zero_power_deadband_pu": 0.001,
}


def evaluate_native_dynamic_envelope(trace: dict, parameters: dict, startup: dict) -> dict:
    result = {"scope": "native_energy_and_normal_dynamics", "status": "FAIL",
              "model_accepted": False, "limits": dict(LIMITS), "checks": {}, "windows": {}}
    arms = [f"{s}_{p}_{q}" for s in ("P", "V") for p in "ABC" for q in ("UPPER", "LOWER")]
    required = {"time", "P_P_REFERENCE", "P_P"}
    for s in ("P", "V"):
        required.update(s + "_" + n for n in ("VDC", "VDC_POS", "VDC_NEG", "IDC", "KCL_IDC", "Q", "BLOCK", "PLL_LOCKED", "LIMIT_ACTIVE"))
        for p in "ABC":
            for q in ("UPPER", "LOWER"):
                required.add(f"{s}_M_{p}_{q}_RAW")
    required.update(a + "_" + n for a in arms for n in ("I", "INET", "W", "VCAP", "VT", "PLOSS", "PSWITCH"))
    if not required <= trace.keys():
        result["missing_channels"] = sorted(required - trace.keys())
        return result
    time = trace["time"]
    if len(time) < 3 or any(len(trace[n]) != len(time) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in trace[n]) for n in required) or any(b <= a for a, b in zip(time, time[1:])):
        result["error"] = "Dynamic evidence is nonfinite or unaligned"
        return result
    if startup.get("status") != "PASS" or not {"operating_windows", "power_start_time_s", "reversal_window_s"} <= startup.keys():
        result["error"] = "Measured startup and operating windows are required"
        return result
    power = parameters["active_power_order_mw"]
    vdc = parameters["vdc_order_kv"]
    frequency = parameters["frequency_hz"]
    capacitance = parameters["arm"]["C_eq_F"]
    energy_base = capacitance * vdc**2 / 8.0
    dc_current_base = power / vdc
    reversal_start, reversal_end = startup["reversal_window_s"]
    normal_end = startup["operating_windows"]["reverse"][1]
    windows = {**startup["operating_windows"],
               "reversal": (reversal_start, reversal_end + LIMITS["settling_time_s"]),
               "normal": (startup["power_start_time_s"], normal_end)}
    indexes = {}
    for name, (start, end) in windows.items():
        if not time[0] <= start < end <= time[-1]:
            result["error"] = "A declared dynamic window is not covered"
            return result
        indexes[name] = [i for i, instant in enumerate(time) if start <= instant <= end]
        if len(indexes[name]) < 3:
            result["error"] = "A dynamic window has fewer than three samples"
            return result

    def check(name, passed):
        result["checks"][name] = bool(passed)

    energy = diagnose_native_arm_energy(trace, parameters["arm"], tuple(startup["operating_windows"].values()))
    result["energy_accounting"] = energy
    for (name, _), offset in zip(startup["operating_windows"].items(), range(0, len(energy), 2)):
        ix = indexes[name]
        for si, s in enumerate(("P", "V")):
            stem = name + ":" + s
            metrics = result["windows"].setdefault(name, {})[s] = {}
            residual = energy[offset + si]["unaccounted_mean_power_mw"] / power
            metrics["energy_residual_pu"] = residual
            check(stem + ":power_balance", abs(residual) <= LIMITS["power_balance_residual_pu"])
            symmetry = max(abs(trace[s + "_VDC_POS"][i] + trace[s + "_VDC_NEG"][i]) for i in ix) / vdc
            metrics["pole_symmetry_pu"] = symmetry
            check(stem + ":pole_symmetry", symmetry <= LIMITS["pole_symmetry_pu"] and all(trace[s + "_VDC_POS"][i] > 0 > trace[s + "_VDC_NEG"][i] for i in ix))
            direction = 1.0 if name == "forward" else -1.0
            check(stem + ":dc_current_direction", all(direction * (1 if s == "P" else -1) * trace[s + "_IDC"][i] > 0 for i in ix))
            for phase in "ABC":
                upper, lower = (f"{s}_{phase}_{q}" for q in ("UPPER", "LOWER"))
                difference = abs(fmean(trace[upper + "_W"][i] - trace[lower + "_W"][i] for i in ix)) / energy_base
                check(stem + ":" + phase + ":energy_difference", difference <= LIMITS["energy_difference_mean_pu"])
                circulating = [(trace[upper + "_INET"][i] + trace[lower + "_INET"][i]) / 2 + trace[s + "_KCL_IDC"][i] / 3 for i in ix]
                mean = fmean(circulating)
                rms = math.sqrt(fmean(v*v for v in circulating)) / dc_current_base
                h2 = 2 * math.hypot(fmean((v - mean) * math.sin(4 * math.pi * frequency * time[i]) for v, i in zip(circulating, ix)), fmean((v - mean) * math.cos(4 * math.pi * frequency * time[i]) for v, i in zip(circulating, ix))) / dc_current_base
                metrics[phase] = {"circulating_rms_pu": rms, "circulating_second_harmonic_peak_pu": h2, "energy_difference_mean_pu": difference}
                check(stem + ":" + phase + ":circulating_current", rms <= LIMITS["circulating_rms_pu"] and h2 <= LIMITS["circulating_second_harmonic_peak_pu"])
                for arm in (upper, lower):
                    values = [trace[arm + "_W"][i] for i in ix]
                    mean_error = abs(fmean(values) / energy_base - 1)
                    ripple = (max(values) - min(values)) / energy_base
                    check(name + ":" + arm + ":energy", min(values) > 0 and mean_error <= LIMITS["arm_energy_mean_deviation_pu"] and ripple <= LIMITS["arm_energy_peak_to_peak_pu"])

    normal, reversal = indexes["normal"], indexes["reversal"]
    dynamic = result["windows"]["normal"] = {}
    for s, voltage_key in (("P", "station_p_valve_voltage_kv"), ("V", "station_vdc_valve_voltage_kv")):
        station_arms = [a for a in arms if a.startswith(s + "_")]
        ac_peak = math.sqrt(2.0) * math.hypot(power, parameters["reactive_power_order_mvar"]) / (math.sqrt(3.0) * parameters[voltage_key])
        arm_base = dc_current_base / 3 + ac_peak / 2
        metrics = dynamic[s] = {
            "dc_voltage_deviation_pu": max(abs(trace[s + "_VDC"][i] / vdc - 1) for i in normal),
            "dc_current_peak_pu": max(abs(trace[s + "_IDC"][i]) for i in normal) / dc_current_base,
            "arm_current_peak_pu": max(abs(trace[a + "_I"][i]) for a in station_arms for i in normal) / arm_base,
            "capacitor_voltage_deviation_pu": max(abs(2 * trace[a + "_VCAP"][i] / vdc - 1) for a in station_arms for i in normal),
            "dynamic_insertion_margin": min(min(trace[f"{s}_M_{p}_{q}_RAW"][i], 1 - trace[f"{s}_M_{p}_{q}_RAW"][i]) for p in "ABC" for q in ("UPPER", "LOWER") for i in normal),
        }
        for name, value in metrics.items():
            check(f"normal:{s}:{name}", value >= LIMITS[name] if name == "dynamic_insertion_margin" else value <= LIMITS[name])
        check(f"normal:{s}:continuous_control", all(trace[s + "_BLOCK"][i] < 0.5 and trace[s + "_PLL_LOCKED"][i] >= 0.5 and trace[s + "_LIMIT_ACTIVE"][i] < 0.5 for i in normal))

    order_zero = next((i for i in reversal if trace["P_P_REFERENCE"][i] <= 0), None)
    measured_reverse = next((i for i in reversal if trace["P_P"][i] < -LIMITS["zero_power_deadband_pu"] * power), None)
    check("reversal:command_precedes_direction_change", order_zero is not None and measured_reverse is not None and order_zero <= measured_reverse)
    expected_slew = 2 * power / (reversal_end - reversal_start)
    slopes = []
    for i in reversal:
        left = bisect.bisect_left(time, time[i] - 1 / frequency)
        if time[left] >= reversal_start and time[i] <= reversal_end and left < i:
            slopes.append(abs(trace["P_P"][i] - trace["P_P"][left]) / (time[i] - time[left]))
    slew_ratio = max(slopes) / expected_slew if slopes else math.inf
    overshoot = max(abs(trace["P_P"][i]) for i in reversal) / power - 1
    check("reversal:power_slew", slew_ratio <= LIMITS["reversal_slew_ratio"])
    check("reversal:power_overshoot", overshoot <= LIMITS["power_overshoot_pu"])
    after = [i for i in reversal if time[i] >= reversal_end]
    if not after:
        result["error"] = "No samples cover reverse settling"
        return result
    unsettled = [i for i in after if abs(trace["P_P"][i] / power + 1) > LIMITS["settling_power_error_pu"] or any(abs(trace[s + "_VDC"][i] / vdc - 1) > LIMITS["dc_voltage_deviation_pu"] or abs(trace[s + "_Q"][i] - parameters["reactive_power_order_mvar"]) / power > LIMITS["settling_power_error_pu"] for s in ("P", "V"))]
    settle_index = (unsettled[-1] + 1) if unsettled else after[0]
    settling = time[settle_index] - reversal_end if settle_index <= after[-1] else None
    check("reversal:settling", settling is not None and settling <= LIMITS["settling_time_s"] and time[after[-1]] - time[settle_index] >= 2 / frequency)
    result["windows"]["reversal"] = {"command_zero_s": time[order_zero] if order_zero is not None else None,
        "measured_reverse_s": time[measured_reverse] if measured_reverse is not None else None,
        "slew_ratio": slew_ratio, "overshoot_pu": overshoot, "settling_time_s": settling}
    result["failed_checks"] = [name for name, passed in result["checks"].items() if not passed]
    result["status"] = "FAIL" if result["failed_checks"] else "PASS"
    return result
