"""Independent native network identities and unresolved physical diagnostics.

KCL uses native DSDYN copies of the preceding network solution at both the
independent terminal meters and the arm resistance branches. Identity checks
use the existing 1e-9 kA current, 1e-6 kV voltage,
and 1e-9 relative energy tolerances. Diagnostic ripple, pole symmetry, and
circulating-current metrics are not promoted to a full-model PASS.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from statistics import fmean


def evaluate_native_network_identities(
    trace: Mapping[str, Sequence[float]], *, capacitance_f: float,
    grounding_resistance_ohm: float, voltage_kv: float, frequency_hz: float,
    valve_grounding_resistance_ohm: float,
    windows: Mapping[str, tuple[float, float]],
) -> dict:
    result = {
        "scope": "native_network_identities_and_physical_diagnostics",
        "status": "FAIL", "model_accepted": False, "checks": {},
        "limits": {"current_residual_ka": 1e-9, "voltage_residual_kv": 1e-6,
                   "energy_relative_error": 1e-9, "modulation_clip_error": 1e-9},
        "stations": {}, "windows": {},
        "pending_physical_checks": ["pole_symmetry_envelope", "energy_ripple_envelope",
                                    "circulating_current_envelope", "startup_readiness",
                                    "pll", "protection", "reversal", "fault_recovery"],
    }
    parameters = (capacitance_f, grounding_resistance_ohm, valve_grounding_resistance_ohm, voltage_kv, frequency_hz)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in parameters):
        raise ValueError("Network identity parameters must be finite and positive")
    required = {"time"}
    for station in ("P", "V"):
        required.update(f"{station}_{s}" for s in ("VDC", "VDC_POS", "VDC_NEG", "IDC", "IDC_NEG"))
        required.update(f"{station}_KCL_{s}" for s in ("VDC_POS", "VDC_NEG", "IDC", "IDC_NEG"))
        for phase in "ABC":
            required.add(f"{station}_VALVE_I_{phase}")
            required.add(f"{station}_VALVE_V_{phase}")
            required.add(f"{station}_KCL_VALVE_V_{phase}")
            required.add(f"{station}_KCL_VALVE_I_{phase}")
            for position in ("UPPER", "LOWER"):
                required.update(f"{station}_{phase}_{position}_{s}" for s in ("INET", "W", "VCAP"))
                required.update((f"{station}_M_{phase}_{position}", f"{station}_M_{phase}_{position}_RAW"))
    if not required <= trace.keys():
        result["missing_channels"] = sorted(required - trace.keys())
        return result
    time = trace["time"]
    if len(time) < 2 or any(
        len(trace[name]) != len(time)
        or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in trace[name])
        for name in required
    ) or any(b <= a for a, b in zip(time, time[1:])):
        result["error"] = "Missing, nonfinite, or unaligned measurements"
        return result
    indexes_by_window = {}
    if not windows:
        result["error"] = "Physical windows are required"
        return result
    for name, (start, end) in windows.items():
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (start, end)) or not time[0] <= start < end <= time[-1]:
            result["error"] = "A physical window is invalid or not covered"
            return result
        indexes = [i for i, instant in enumerate(time) if start <= instant <= end]
        if len(indexes) < 2:
            result["error"] = "A physical window has fewer than two samples"
            return result
        indexes_by_window[name] = indexes
    for station in ("P", "V"):
        vpos, vneg, vdc, ipos, ineg = (trace[f"{station}_{s}"] for s in ("VDC_POS", "VDC_NEG", "VDC", "IDC", "IDC_NEG"))
        phases = {}
        arms = {}
        for phase in "ABC":
            upper = trace[f"{station}_{phase}_UPPER_INET"]
            lower = trace[f"{station}_{phase}_LOWER_INET"]
            phase_current = trace[f"{station}_KCL_VALVE_I_{phase}"]
            phase_voltage = trace[f"{station}_KCL_VALVE_V_{phase}"]
            phases[phase] = {
                "kcl_max_residual_ka": max(abs(u + ac - l - v / valve_grounding_resistance_ohm) for u, ac, l, v in zip(upper, phase_current, lower, phase_voltage)),
            }
            result["checks"][f"{station}:{phase}:phase_kcl"] = phases[phase]["kcl_max_residual_ka"] <= result["limits"]["current_residual_ka"]
            for position in ("UPPER", "LOWER"):
                prefix = f"{station}_{phase}_{position}"
                energy, capacitor = trace[prefix + "_W"], trace[prefix + "_VCAP"]
                clipped, raw = trace[f"{station}_M_{phase}_{position}"], trace[f"{station}_M_{phase}_{position}_RAW"]
                error = max(abs(w - 0.5 * capacitance_f * v**2) / max(1e-6, abs(w)) for w, v in zip(energy, capacitor))
                clip_error = max(abs(c - min(1.0, max(0.0, r))) for c, r in zip(clipped, raw))
                arms[phase + "_" + position] = {"energy_relative_error": error, "modulation_clip_error": clip_error}
                arms[phase + "_" + position].update(minimum_energy_mj=min(energy), minimum_capacitor_kv=min(capacitor))
                # A native diode may leave sub-millivolt roundoff at zero charge.
                # Retain the measured minimum and apply the declared tolerances.
                result["checks"][prefix + ":energy_capacitance"] = error <= result["limits"]["energy_relative_error"] and min(energy) >= -1e-9 and min(capacitor) >= -result["limits"]["voltage_residual_kv"]
                result["checks"][prefix + ":modulation_clip"] = clip_error <= result["limits"]["modulation_clip_error"]
        upper_sum = [math.fsum(trace[f"{station}_{phase}_UPPER_INET"][i] for phase in "ABC") for i in range(len(time))]
        lower_sum = [math.fsum(trace[f"{station}_{phase}_LOWER_INET"][i] for phase in "ABC") for i in range(len(time))]
        metrics = {
            "positive_pole_kcl_max_residual_ka": max(abs(u + i + v / grounding_resistance_ohm) for u, i, v in zip(upper_sum, trace[station + "_KCL_IDC"], trace[station + "_KCL_VDC_POS"])),
            "negative_pole_kcl_max_residual_ka": max(abs(l - i - v / grounding_resistance_ohm) for l, i, v in zip(lower_sum, trace[station + "_KCL_IDC_NEG"], trace[station + "_KCL_VDC_NEG"])),
            "voltage_max_residual_kv": max(abs(p - n - d) for p, n, d in zip(vpos, vneg, vdc)),
            "phases": phases, "arms": arms,
        }
        for field in ("positive_pole_kcl_max_residual_ka", "negative_pole_kcl_max_residual_ka"):
            result["checks"][f"{station}:{field}"] = metrics[field] <= result["limits"]["current_residual_ka"]
        result["checks"][station + ":pole_voltage_identity"] = metrics["voltage_max_residual_kv"] <= result["limits"]["voltage_residual_kv"]
        result["stations"][station] = metrics
        for name, indexes in indexes_by_window.items():
            window = result["windows"].setdefault(name, {"time_s": list(windows[name]), "stations": {}})
            diagnostic = {
                "pole_symmetry_max_deviation_pu": max(abs(vpos[i] + vneg[i]) for i in indexes) / voltage_kv,
                "pole_polarity_valid": all(vpos[i] > 0 > vneg[i] for i in indexes),
                "grounding_loss_mean_mw": fmean((vpos[i]**2 + vneg[i]**2) / grounding_resistance_ohm for i in indexes),
                "valve_grounding_loss_mean_mw": fmean(sum(trace[f"{station}_VALVE_V_{p}"][i]**2 for p in "ABC") / valve_grounding_resistance_ohm for i in indexes),
                "dc_terminal_power_mean_mw": fmean(vpos[i] * ipos[i] + vneg[i] * ineg[i] for i in indexes),
                "arms": {}, "phases": {},
            }
            for phase in "ABC":
                circulating = [(trace[f"{station}_{phase}_UPPER_INET"][i] + trace[f"{station}_{phase}_LOWER_INET"][i]) * 0.5 + trace[station + "_KCL_IDC"][i] / 3.0 for i in indexes]
                mean = fmean(circulating)
                sine = 2 * fmean((x - mean) * math.sin(4 * math.pi * frequency_hz * time[i]) for x, i in zip(circulating, indexes))
                cosine = 2 * fmean((x - mean) * math.cos(4 * math.pi * frequency_hz * time[i]) for x, i in zip(circulating, indexes))
                diagnostic["phases"][phase] = {
                    "circulating_rms_ka": math.sqrt(fmean(x*x for x in circulating)),
                    "circulating_second_harmonic_peak_ka": math.hypot(sine, cosine),
                }
                for position in ("UPPER", "LOWER"):
                    prefix = f"{station}_{phase}_{position}"
                    energy = [trace[prefix + "_W"][i] for i in indexes]
                    raw = [trace[f"{station}_M_{phase}_{position}_RAW"][i] for i in indexes]
                    saturated_s = sum(time[right] - time[left] for left, right in zip(indexes, indexes[1:]) if not 0 <= trace[f"{station}_M_{phase}_{position}_RAW"][left] <= 1)
                    mean_energy = fmean(energy)
                    diagnostic["arms"][phase + "_" + position] = {
                        "mean_energy_mj": mean_energy, "minimum_energy_mj": min(energy),
                        "energy_peak_to_peak_over_mean": (max(energy) - min(energy)) / mean_energy if mean_energy > 0 else None,
                        "unclipped_insertion_min": min(raw), "unclipped_insertion_max": max(raw),
                        "minimum_insertion_margin": min(min(raw), 1 - max(raw)),
                        "saturation_duration_s": saturated_s,
                    }
            window["stations"][station] = diagnostic
    result["failed_checks"] = [name for name, passed in result["checks"].items() if not passed]
    result["status"] = "FAIL" if result["failed_checks"] else "PASS"
    return result
