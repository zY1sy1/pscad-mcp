"""Measured precharge readiness for the two-station native MMC assembly."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import fmean
from xml.etree import ElementTree as ET

from .avm_companion import _definition, _script


STARTUP_NAME = "MMCPrechargeReadiness"
STARTUP_INPUTS = ("P_VDC", "V_VDC", "P_PLL_LOCKED", "V_PLL_LOCKED") + tuple(
    f"{s}_{p}_{q}_{quantity}" for s in ("P", "V") for p in "ABC"
    for q in ("UPPER", "LOWER") for quantity in ("VCAP", "I")
)
STARTUP_OUTPUTS = {
    "READY": ("PRECHARGE_READY", "1"),
    "START_TIME": ("DEBLOCK_TIME", "s"),
    "FAILED": ("PRECHARGE_FAILED", "1"),
    "P_RATE": ("P_PRECHARGE_ENERGY_RATE", "1/s"),
    "V_RATE": ("V_PRECHARGE_ENERGY_RATE", "1/s"),
    "CURRENT_MAX": ("PRECHARGE_CURRENT_MAX", "kA"),
    "CAP_MIN": ("PRECHARGE_CAP_MIN", "kV"),
    "POWER_READY": ("POWER_READY", "1"), "POWER_START": ("POWER_START_TIME", "s"),
    "CHARGE_FAILED": ("CHARGE_FAILED", "1"),
}
STARTUP_DEFAULTS = {
    "Frequency_Hz": 60.0, "Vdc_Order_kV": 640.0, "C_eq_F": 6.510416666666667e-5,
    "Deblock_Time_s": 0.10, "Maximum_Precharge_s": 1.0,
    "Precharge_Voltage_Fraction": 0.65, "Precharge_Current_Limit_kA": 2.0,
    "Precharge_Rate_Per_Cycle": 0.01, "Precharge_Hold_Cycles": 2.0,
    "PLL_Required": 0.0,
    "Controlled_Charge": 0.0, "Startup_Charge_Time_s": 0.5, "Maximum_Conditioning_s": 1.5,
}


@dataclass(frozen=True)
class PrechargeState:
    p_energy_filtered_mj: float = 0.0
    v_energy_filtered_mj: float = 0.0
    stable_time_s: float = 0.0
    start_time_s: float = -1.0


def advance_precharge(state: PrechargeState, observation: dict[str, float],
                      time_s: float, step_s: float, parameters: dict[str, float]) -> tuple[PrechargeState, dict]:
    """Independent discrete reference for cold-start readiness and timeout."""
    if not math.isfinite(time_s) or time_s < 0 or not math.isfinite(step_s) or step_s <= 0:
        raise ValueError("Precharge needs finite nonnegative time and a positive timestep")
    if set(observation) != set(STARTUP_INPUTS) or any(not math.isfinite(v) for v in observation.values()):
        raise ValueError("Precharge requires all finite capacitor, current and bus observations")
    p = {**STARTUP_DEFAULTS, **parameters}
    if any(isinstance(v, bool) or not math.isfinite(v) or (v < 0 if name in {"Deblock_Time_s", "PLL_Required", "Controlled_Charge"} else v <= 0) for name, v in p.items()):
        raise ValueError("Precharge parameters must be finite and positive")
    alpha = 1.0 - math.exp(-step_s * p["Frequency_Hz"])
    energies = [sum(0.5 * p["C_eq_F"] * observation[f"{s}_{phase}_{position}_VCAP"]**2
                    for phase in "ABC" for position in ("UPPER", "LOWER")) for s in ("P", "V")]
    previous = (state.p_energy_filtered_mj, state.v_energy_filtered_mj)
    filtered = tuple(old + alpha * (new - old) for old, new in zip(previous, energies))
    energy_floor = 0.75 * p["C_eq_F"] * (p["Precharge_Voltage_Fraction"] * p["Vdc_Order_kV"])**2
    rates = tuple(abs(new - old) / (step_s * max(new, energy_floor)) for old, new in zip(previous, filtered))
    cap_min = min(v for name, v in observation.items() if name.endswith("_VCAP"))
    current = max(abs(v) for name, v in observation.items() if name.endswith("_I"))
    qualified = (
        time_s >= p["Deblock_Time_s"] and time_s <= p["Maximum_Precharge_s"]
        and cap_min >= 0.5 * p["Precharge_Voltage_Fraction"] * p["Vdc_Order_kV"]
        and min(observation["P_VDC"], observation["V_VDC"]) >= p["Precharge_Voltage_Fraction"] * p["Vdc_Order_kV"]
        and current <= 0.1 * p["Precharge_Current_Limit_kA"]
        and max(rates) <= p["Precharge_Rate_Per_Cycle"] * p["Frequency_Hz"]
        and (p["PLL_Required"] < 0.5 or min(observation["P_PLL_LOCKED"], observation["V_PLL_LOCKED"]) >= 0.5)
    )
    stable = state.stable_time_s + step_s if qualified else 0.0
    start = state.start_time_s
    if start < 0 and stable >= p["Precharge_Hold_Cycles"] / p["Frequency_Hz"]:
        start = time_s
    return PrechargeState(*filtered, stable, start), {
        "ready": start >= 0, "failed": start < 0 and time_s > p["Maximum_Precharge_s"],
        "energy_rates_per_s": rates, "current_max_ka": current, "cap_min_kv": cap_min,
    }


def append_precharge_readiness(root: ET.Element) -> None:
    component = _definition(root, STARTUP_NAME,
                            {**{n: (-90, -432 + i * 36, "Transfer", "Input") for i, n in enumerate(STARTUP_INPUTS)},
                             **{n: (90, -108 + i * 36, "Transfer", "Output") for i, n in enumerate(STARTUP_OUTPUTS)}},
                            STARTUP_DEFAULTS)
    energy = "".join(f"      E{s} = E{s} + 0.5 * $C_eq_F * ${s}_{p}_{q}_VCAP**2\n"
                     for s in ("P", "V") for p in "ABC" for q in ("UPPER", "LOWER"))
    extremes = "".join(f"      $CAP_MIN = MIN($CAP_MIN, ${s}_{p}_{q}_VCAP)\n"
                       f"      $CURRENT_MAX = MAX($CURRENT_MAX, ABS(${s}_{p}_{q}_I))\n"
                       for s in ("P", "V") for p in "ABC" for q in ("UPPER", "LOWER"))
    _script(component, "Dsdyn", """#STORAGE REAL:6
#LOCAL REAL EP
#LOCAL REAL EV
#LOCAL REAL FP
#LOCAL REAL FV
#LOCAL REAL ALPHA
#LOCAL REAL EFLOOR
#LOCAL REAL CAPMAX
#LOCAL INTEGER QUALIFIED
      IF (TIMEZERO) THEN
        STORF(NSTORF) = 0.0
        STORF(NSTORF+1) = 0.0
        STORF(NSTORF+2) = 0.0
        STORF(NSTORF+3) = -1.0
        STORF(NSTORF+4) = -1.0
        STORF(NSTORF+5) = 0.0
      ENDIF
      EP = 0.0
      EV = 0.0
""" + energy + """      ALPHA = 1.0 - EXP(-DELT * $Frequency_Hz)
      FP = STORF(NSTORF) + ALPHA * (EP - STORF(NSTORF))
      FV = STORF(NSTORF+1) + ALPHA * (EV - STORF(NSTORF+1))
      EFLOOR = 0.75 * $C_eq_F * ($Precharge_Voltage_Fraction * $Vdc_Order_kV)**2
      $P_RATE = ABS(FP - STORF(NSTORF)) / (DELT * MAX(FP, EFLOOR))
      $V_RATE = ABS(FV - STORF(NSTORF+1)) / (DELT * MAX(FV, EFLOOR))
      $CAP_MIN = $P_A_UPPER_VCAP
      CAPMAX = $P_A_UPPER_VCAP
      $CURRENT_MAX = 0.0
""" + extremes + "".join(f"      CAPMAX = MAX(CAPMAX, ${s}_{p}_{q}_VCAP)\n" for s in ("P", "V") for p in "ABC" for q in ("UPPER", "LOWER")) + """      QUALIFIED = 1
      IF (TIME .LT. $Deblock_Time_s .OR. TIME .GT. $Maximum_Precharge_s) QUALIFIED = 0
      IF ($CAP_MIN .LT. 0.5 * $Precharge_Voltage_Fraction * $Vdc_Order_kV) QUALIFIED = 0
      IF (MIN($P_VDC, $V_VDC) .LT. $Precharge_Voltage_Fraction * $Vdc_Order_kV) QUALIFIED = 0
      IF ($CURRENT_MAX .GT. 0.1 * $Precharge_Current_Limit_kA) QUALIFIED = 0
      IF (MAX($P_RATE, $V_RATE) .GT. $Precharge_Rate_Per_Cycle * $Frequency_Hz) QUALIFIED = 0
      IF ($PLL_Required .GE. 0.5 .AND. MIN($P_PLL_LOCKED, $V_PLL_LOCKED) .LT. 0.5) QUALIFIED = 0
      IF (QUALIFIED .EQ. 1) THEN
        STORF(NSTORF+2) = STORF(NSTORF+2) + DELT
      ELSE
        STORF(NSTORF+2) = 0.0
      ENDIF
      IF (STORF(NSTORF+3) .LT. 0.0 .AND. STORF(NSTORF+2) .GE. $Precharge_Hold_Cycles / $Frequency_Hz) STORF(NSTORF+3) = TIME
      $START_TIME = STORF(NSTORF+3)
      $READY = 0.0
      IF ($START_TIME .GE. 0.0) $READY = 1.0
      $FAILED = 0.0
      IF ($START_TIME .LT. 0.0 .AND. TIME .GT. $Maximum_Precharge_s) $FAILED = 1.0
      STORF(NSTORF) = FP
      STORF(NSTORF+1) = FV
      $POWER_READY = $READY
      $POWER_START = $START_TIME
      $CHARGE_FAILED = 0.0
      IF ($Controlled_Charge .GE. 0.5) THEN
        QUALIFIED = 0
        IF ($READY .GE. 0.5 .AND. TIME .GE. $START_TIME + $Startup_Charge_Time_s) QUALIFIED = 1
        IF (MIN($P_PLL_LOCKED, $V_PLL_LOCKED) .LT. 0.5) QUALIFIED = 0
        IF ($CAP_MIN .LT. 0.475 * $Vdc_Order_kV .OR. CAPMAX .GT. 0.525 * $Vdc_Order_kV) QUALIFIED = 0
        IF (ABS($P_VDC / $Vdc_Order_kV - 1.0) .GT. 0.05 .OR. ABS($V_VDC / $Vdc_Order_kV - 1.0) .GT. 0.05) QUALIFIED = 0
        IF ($CURRENT_MAX .GT. 0.1 * $Precharge_Current_Limit_kA) QUALIFIED = 0
        IF (QUALIFIED .EQ. 1) THEN
          STORF(NSTORF+5) = STORF(NSTORF+5) + DELT
        ELSE
          STORF(NSTORF+5) = 0.0
        ENDIF
        IF (STORF(NSTORF+4) .LT. 0.0 .AND. STORF(NSTORF+5) .GE. 2.0 / $Frequency_Hz) STORF(NSTORF+4) = TIME
        $POWER_START = STORF(NSTORF+4)
        $POWER_READY = 0.0
        IF ($POWER_START .GE. 0.0) $POWER_READY = 1.0
        IF ($READY .GE. 0.5 .AND. $POWER_READY .LT. 0.5 .AND. TIME .GT. $START_TIME + $Maximum_Conditioning_s) $CHARGE_FAILED = 1.0
      ENDIF
      NSTORF = NSTORF + 6
""")


def analyze_precharge_trace(trace: dict, parameters: dict) -> dict:
    """Check the observed precharge interval before deriving operating windows."""
    result = {"status": "FAIL", "model_accepted": False, "scope": "native_precharge_readiness",
              "checks": {}, "limits": {"energy_change_per_cycle": 0.01, "hold_cycles": 2.0,
                                        "voltage_fraction": 0.65, "ready_current_fraction": 0.10}}
    arms = [f"{s}_{p}_{q}" for s in ("P", "V") for p in "ABC" for q in ("UPPER", "LOWER")]
    required = {"time", "PRECHARGE_READY", "PRECHARGE_FAILED", "DEBLOCK_TIME", "P_BLOCK", "V_BLOCK", "P_VDC", "V_VDC"}
    if parameters.get("control_kind") == "dq_current":
        required.update(("POWER_READY", "POWER_START_TIME", "CHARGE_FAILED"))
    required.update(arm + suffix for arm in arms for suffix in ("_I", "_VCAP", "_W"))
    time = trace.get("time", ())
    if not required <= trace.keys() or len(time) < 2 or any(
        len(trace[name]) != len(time) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in trace[name])
        for name in required
    ) or any(b <= a for a, b in zip(time, time[1:])):
        result["error"] = "Precharge measurements are missing, invalid, or unaligned"
        return result
    ready = [i for i, value in enumerate(trace["PRECHARGE_READY"]) if value >= 0.5]
    if not ready or any(value >= 0.5 for value in trace["PRECHARGE_FAILED"]):
        result["error"] = "Precharge readiness was not reached before its deadline"
        return result
    first = ready[0]
    start = trace["DEBLOCK_TIME"][first]
    step = parameters["output_step_s"]
    frequency = parameters["frequency_hz"]
    voltage = parameters["vdc_order_kv"]
    limit = parameters["precharge_current_limit_ka"]
    hold = 2.0 / frequency
    checks = result["checks"]
    checks["declared_deblock_time"] = parameters["deblock_time_s"] <= start <= parameters["maximum_precharge_time_s"] and 0 <= time[first] - start <= 2.1 * step
    checks["ready_precedes_both_deblocks"] = all(
        all(trace[f"{s}_BLOCK"][i] >= 0.5 for i in range(first))
        and any(trace[f"{s}_BLOCK"][i] < 0.5 for i, t in enumerate(time) if start <= t <= start + 2.1 * step)
        for s in ("P", "V")
    )
    indexes = [i for i, t in enumerate(time) if start - hold <= t < start]
    precharge = [i for i, t in enumerate(time) if 0 <= t < start]
    if len(indexes) < 2 or not precharge:
        result["error"] = "The readiness hold interval is not covered by samples"
        return result
    peak = max(abs(trace[arm + "_I"][i]) for arm in arms for i in precharge)
    ready_peak = max(abs(trace[arm + "_I"][i]) for arm in arms for i in indexes)
    minimum_cap = min(trace[arm + "_VCAP"][i] for arm in arms for i in indexes)
    minimum_bus = min(trace[s + "_VDC"][i] for s in ("P", "V") for i in indexes)
    checks["bounded_precharge_current"] = peak <= limit
    checks["current_settled_before_deblock"] = ready_peak <= 0.10 * limit
    checks["charged_capacitors_before_deblock"] = minimum_cap >= 0.5 * 0.65 * voltage
    checks["charged_dc_buses_before_deblock"] = minimum_bus >= 0.65 * voltage
    metrics = {"peak_current_ka": peak, "ready_peak_current_ka": ready_peak,
               "minimum_equivalent_capacitor_voltage_kv": minimum_cap, "minimum_dc_bus_voltage_kv": minimum_bus,
               "hold_window_s": [time[indexes[0]], time[indexes[-1]]], "energy_excursion_fraction": {}}
    for s in ("P", "V"):
        energy = [sum(trace[f"{s}_{p}_{q}_W"][i] for p in "ABC" for q in ("UPPER", "LOWER")) for i in indexes]
        mean = fmean(energy)
        excursion = (max(energy) - min(energy)) / mean if mean > 0 else math.inf
        metrics["energy_excursion_fraction"][s] = excursion if math.isfinite(excursion) else None
        checks[s + ":precharge_energy_convergence"] = mean > 0 and excursion <= 0.02
    result["metrics"] = metrics
    result["deblock_time_s"] = start
    power_start = start
    if parameters.get("control_kind") == "dq_current":
        power_ready = [i for i, value in enumerate(trace["POWER_READY"]) if value >= 0.5]
        if not power_ready or any(v >= 0.5 for v in trace["CHARGE_FAILED"]):
            result["error"] = "Active capacitor charging did not reach measured readiness before its deadline"
            return result
        power_start = trace["POWER_START_TIME"][power_ready[0]]
        checks["charge_finishes_before_power_transfer"] = power_start >= start + parameters["startup_charge_time_s"]
        ready_indexes = [i for i, t in enumerate(time) if power_start - hold <= t < power_start]
        checks["capacitor_voltages_ready_for_power"] = bool(ready_indexes) and all(
            0.95 <= 2 * trace[arm + "_VCAP"][i] / voltage <= 1.05 for arm in arms for i in ready_indexes
        )
        checks["dc_voltages_ready_for_power"] = bool(ready_indexes) and all(
            abs(trace[s + "_VDC"][i] / voltage - 1) <= 0.05 for s in ("P", "V") for i in ready_indexes
        )
    result["power_start_time_s"] = power_start
    reversal_start = power_start + parameters["reversal_time_s"] - parameters["deblock_time_s"]
    reversal_end = reversal_start + parameters["reversal_duration_s"]
    result["operating_windows"] = {"forward": [power_start + 0.5, power_start + 0.8], "reverse": [reversal_end + 0.5, reversal_end + 0.8]}
    result["reversal_window_s"] = [reversal_start, reversal_end]
    result["failed_checks"] = [name for name, value in checks.items() if not value]
    result["status"] = "FAIL" if result["failed_checks"] else "PASS"
    return result
