"""EMTDC-timed physical fault injection for staged native AVM verification."""

from xml.etree import ElementTree as ET

from .avm_companion import _definition, _script, _PARAMETER_UNITS

FAULT_KINDS = ("ac_three_phase", "ac_single_line_ground", "dc_pole_to_pole", "dc_pole_to_ground")
FAULT_NAME = "MMCNativeFaultProtocol"
FAULT_OUTPUTS = {"ACTIVE": ("FAULT_ACTIVE", "1"), "OPEN": ("FAULT_OPEN", "1"),
                 "START": ("FAULT_START", "s"), "END": ("FAULT_END", "s")}
FAULT_DEFAULTS = {"Fault_Delay_s": 2.9, "Fault_Duration_s": 0.05}


def append_native_fault_protocol(root: ET.Element) -> None:
    _PARAMETER_UNITS.update({name: "s" for name in FAULT_DEFAULTS})
    definition = _definition(root, FAULT_NAME,
        {"POWER_READY": (-90, -18, "Transfer", "Input"), "POWER_START": (-90, 18, "Transfer", "Input"),
         **{n: (90, -54 + i * 36, "Transfer", "Output") for i, n in enumerate(FAULT_OUTPUTS)}}, FAULT_DEFAULTS)
    _script(definition, "Dsdyn", """      $ACTIVE = 0.0
      $OPEN = 1.0
      $START = -1.0
      $END = -1.0
      IF ($POWER_READY .GE. 0.5) THEN
        $START = $POWER_START + $Fault_Delay_s
        $END = $START + $Fault_Duration_s
        IF (TIME .GE. $START .AND. TIME .LT. $END) THEN
          $ACTIVE = 1.0
          $OPEN = 0.0
        ENDIF
      ENDIF
""")


def fault_branches(kind: str) -> dict[str, tuple[str, str]]:
    if kind == "ac_three_phase":
        return {p: ("P_GRID_" + p, "GND") for p in "ABC"}
    if kind == "ac_single_line_ground":
        return {"A": ("P_GRID_A", "GND")}
    if kind == "dc_pole_to_pole":
        return {"DC": ("P_CABLE_POS", "P_CABLE_NEG")}
    if kind == "dc_pole_to_ground":
        return {"DC": ("P_CABLE_POS", "GND")}
    raise ValueError("Unsupported native AVM fault kind")


def evaluate_native_fault_trace(trace: dict, parameters: dict) -> dict:
    """Fault response and recovery gate; a latch alone cannot establish PASS."""
    import math

    result = {"scope": "native_half_bridge_fault_response", "status": "FAIL", "model_accepted": False,
              "intrinsic_dc_fault_blocking": False, "checks": {}, "metrics": {},
              "limits": {"trip_latency_s": 0.005, "recovery_time_s": 0.5,
                         "dc_current_peak_pu": 2.0, "arm_current_peak_pu": 2.0,
                         "recovered_power_error_pu": 0.05, "recovered_voltage_error_pu": 0.10}}
    kind = parameters.get("fault_kind")
    branches = fault_branches(kind)
    if kind.startswith("ac_"):
        result["limits"]["dc_current_peak_pu"] = 1.25
    required = {"time", "FAULT_ACTIVE", "FAULT_START", "FAULT_END", "PROTECTION_TRIP", "PROTECTION_TIME", "PROTECTION_CODE"}
    required.update("FAULT_I_" + name for name in branches)
    for s in ("P", "V"):
        required.update(s + "_" + n for n in ("BLOCK", "VDC", "IDC", "P", "P_REFERENCE", "PLL_LOCKED"))
        required.update(f"{s}_{p}_{q}_I" for p in "ABC" for q in ("UPPER", "LOWER"))
    if not required <= trace.keys():
        result["missing_channels"] = sorted(required - trace.keys())
        return result
    time = trace["time"]
    if len(time) < 3 or any(len(trace[k]) != len(time) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in trace[k]) for k in required) or any(b <= a for a, b in zip(time, time[1:])):
        result["error"] = "Fault observations are invalid or unaligned"
        return result
    active = [i for i, v in enumerate(trace["FAULT_ACTIVE"]) if v >= 0.5]
    if not active:
        result["error"] = "The requested fault was never applied"
        return result
    start, end = trace["FAULT_START"][active[0]], trace["FAULT_END"][active[0]]
    step = parameters["output_step_s"]
    if not 0 < start < end < end + 0.7 <= time[-1]:
        result["error"] = "Fault and recovery windows are not fully covered"
        return result
    checks = result["checks"]
    checks["fault_timing"] = abs(time[active[0]] - start) <= 1.1 * step and abs(time[active[-1]] + step - end) <= 1.1 * step
    checks["physical_fault_current"] = all(max(abs(trace["FAULT_I_" + name][i]) for i in active) > 0.01 for name in branches)
    trip = next((i for i, v in enumerate(trace["PROTECTION_TRIP"]) if v >= 0.5), None)
    checks["protection_trips_after_fault"] = trip is not None and start - 1.1 * step <= trace["PROTECTION_TIME"][trip] <= start + result["limits"]["trip_latency_s"]
    if trip is not None:
        checks["both_stations_block"] = all(any(trace[s + "_BLOCK"][i] >= 0.5 for i in range(trip, min(len(time), trip + 4))) for s in ("P", "V"))
    checks["fault_clears"] = all(v < 0.5 for t, v in zip(time, trace["FAULT_ACTIVE"]) if t >= end + step)
    fault_window = [i for i, t in enumerate(time) if start <= t <= end + 0.5]
    recovery = [i for i, t in enumerate(time) if end + 0.5 <= t <= end + 0.7]
    vdc, power = parameters["vdc_order_kv"], parameters["active_power_order_mw"]
    metrics = result["metrics"]
    metrics.update(fault_start_s=start, fault_end_s=end, trip_time_s=trace["PROTECTION_TIME"][trip] if trip is not None else None)
    for s, voltage_key in (("P", "station_p_valve_voltage_kv"), ("V", "station_vdc_valve_voltage_kv")):
        arms = [f"{s}_{p}_{q}_I" for p in "ABC" for q in ("UPPER", "LOWER")]
        base = power / (3 * vdc) + math.sqrt(2) * math.hypot(power, parameters["reactive_power_order_mvar"]) / (2 * math.sqrt(3) * parameters[voltage_key])
        metrics[s] = {"dc_current_peak_pu": max(abs(trace[s + "_IDC"][i]) for i in fault_window) / (power / vdc),
                      "arm_current_peak_pu": max(abs(trace[a][i]) for a in arms for i in fault_window) / base,
                      "recovered_dc_voltage_error_pu": max(abs(trace[s + "_VDC"][i] / vdc - 1) for i in recovery)}
        checks[s + ":dc_current_bound"] = metrics[s]["dc_current_peak_pu"] <= result["limits"]["dc_current_peak_pu"]
        checks[s + ":arm_current_bound"] = metrics[s]["arm_current_peak_pu"] <= result["limits"]["arm_current_peak_pu"]
        checks[s + ":voltage_recovery"] = metrics[s]["recovered_dc_voltage_error_pu"] <= result["limits"]["recovered_voltage_error_pu"]
        checks[s + ":control_recovery"] = all(trace[s + "_BLOCK"][i] < 0.5 and trace[s + "_PLL_LOCKED"][i] >= 0.5 for i in recovery)
    metrics["recovered_power_error_pu"] = max(abs(trace["P_P"][i] / power + 1) for i in recovery)
    checks["power_recovery"] = metrics["recovered_power_error_pu"] <= result["limits"]["recovered_power_error_pu"]
    result["failed_checks"] = [k for k, passed in checks.items() if not passed]
    result["status"] = "FAIL" if result["failed_checks"] else "PASS"
    return result
