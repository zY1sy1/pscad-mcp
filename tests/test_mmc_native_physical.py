import math

import pytest

from pscad_mcp.hvdc.builders.mmc.native_physical import evaluate_native_network_identities


def balanced_measurements():
    time = [i / 10000 for i in range(2001)]
    trace = {"time": time}
    capacitance = 6.510416666666667e-5
    for station, current in (("P", 1.5), ("V", -1.5)):
        for suffix, value in (("VDC", 640.0), ("VDC_POS", 320.0), ("VDC_NEG", -320.0), ("IDC", current), ("IDC_NEG", -current)):
            trace[f"{station}_{suffix}"] = [value] * len(time)
        for p, phase in enumerate("ABC"):
            ac = [math.sin(2 * math.pi * 60 * t - p * 2 * math.pi / 3) for t in time]
            trace[f"{station}_VALVE_V_{phase}"] = [200 * i for i in ac]
            trace[f"{station}_VALVE_I_{phase}"] = [-i + 200 * i / 1e6 for i in ac]
            for position, sign in (("UPPER", 1.0), ("LOWER", -1.0)):
                prefix = f"{station}_{phase}_{position}"
                trace[prefix + "_INET"] = [(-current - 320.0 / 1e6) / 3.0 + sign * i / 2.0 for i in ac]
                trace[prefix + "_W"] = [0.5 * capacitance * 320.0**2] * len(time)
                trace[prefix + "_VCAP"] = [320.0] * len(time)
                trace[f"{station}_M_{phase}_{position}"] = [0.5] * len(time)
                trace[f"{station}_M_{phase}_{position}_RAW"] = [0.5] * len(time)
        for name, values in list(trace.items()):
            if name.startswith(station + "_") and name.removeprefix(station + "_") in {"VDC_POS", "VDC_NEG", "IDC", "IDC_NEG", *(f"VALVE_{q}_{p}" for p in "ABC" for q in ("I", "V"))}:
                trace[station + "_KCL_" + name.removeprefix(station + "_")] = list(values)
    return trace


def evaluate(trace, **overrides):
    return evaluate_native_network_identities(
        trace, **{"capacitance_f": 6.510416666666667e-5, "grounding_resistance_ohm": 1e6,
                  "valve_grounding_resistance_ohm": 1e6,
                  "voltage_kv": 640.0, "frequency_hz": 60.0,
                  "windows": {"steady": (0.02, 0.12)}, **overrides},
    )


def test_independent_network_identities_include_ground_current_and_preserve_partial_scope():
    result = evaluate(balanced_measurements())
    assert result["status"] == "PASS"
    assert result["model_accepted"] is False
    assert "fault_recovery" in result["pending_physical_checks"]
    assert result["windows"]["steady"]["stations"]["P"]["grounding_loss_mean_mw"] == pytest.approx(0.2048)
    # Ignoring the physical grounding shunt breaks terminal KCL.
    assert evaluate(balanced_measurements(), grounding_resistance_ohm=1e12)["status"] == "FAIL"
    assert evaluate(balanced_measurements(), valve_grounding_resistance_ohm=1e12)["status"] == "FAIL"


def test_neutral_reactor_current_must_be_observed_in_phase_kcl():
    trace = balanced_measurements()
    for s in ("P", "V"):
        for phase, current in zip("ABC", (0.03, -0.015, -0.015)):
            trace[f"{s}_NEUTRAL_I_{phase}"] = [current] * len(trace["time"])
            trace[f"{s}_KCL_VALVE_I_{phase}"] = [v + current for v in trace[f"{s}_KCL_VALVE_I_{phase}"]]
    assert evaluate(trace)["status"] == "FAIL"
    assert evaluate(trace, neutral_grounded=True)["status"] == "PASS"
    del trace["V_NEUTRAL_I_C"]
    assert evaluate(trace, neutral_grounded=True)["status"] == "FAIL"


@pytest.mark.parametrize("signal, value, failed", [
    ("P_KCL_VALVE_I_A", 1.0, "P:A:phase_kcl"),
    ("V_KCL_IDC_NEG", 1.0, "V:negative_pole_kcl_max_residual_ka"),
    ("P_VDC", 639.0, "P:pole_voltage_identity"),
    ("P_A_UPPER_W", 4.0, "P_A_UPPER:energy_capacitance"),
    ("P_M_A_UPPER_RAW", 1.1, "P_A_UPPER:modulation_clip"),
])
def test_rejects_one_bad_sample_not_hidden_by_window_averages(signal, value, failed):
    trace = balanced_measurements()
    trace[signal][500] = value
    result = evaluate(trace)
    assert result["status"] == "FAIL"
    assert failed in result["failed_checks"]


@pytest.mark.parametrize("mutation", ["missing", "nan", "length", "time", "bool", "window"])
def test_rejects_incomplete_or_invalid_evidence(mutation):
    trace = balanced_measurements()
    options = {}
    if mutation == "missing":
        del trace["P_A_UPPER_INET"]
    elif mutation == "nan":
        trace["P_A_UPPER_INET"][100] = math.nan
    elif mutation == "length":
        trace["P_A_UPPER_INET"].pop()
    elif mutation == "time":
        trace["time"][100] = trace["time"][99]
    elif mutation == "bool":
        trace["P_VDC"][100] = True
    else:
        options["windows"] = {"uncovered": (0.0, 0.5)}
    assert evaluate(trace, **options)["status"] == "FAIL"
