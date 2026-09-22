import copy
import math

import pytest

from pscad_mcp.hvdc.builders.mmc.native_dynamic_checks import evaluate_native_dynamic_envelope


@pytest.fixture
def evidence():
    time = [i / 1000 for i in range(3001)]
    order = lambda t: 1000.0 * max(-1.0, min(1.0, 1.0 - 2.0 * (t - 1.0)))
    trace = {"time": time, "P_P_REFERENCE": [order(t) for t in time],
             "P_P": [order(t - 0.002) for t in time]}
    trace.update({"PROTECTION_TRIP": [0.0] * len(time), "PROTECTION_CODE": [0.0] * len(time), "PROTECTION_TIME": [-1.0] * len(time)})
    capacitance = 1e-4
    for s in ("P", "V"):
        current = [(1 if s == "P" else -1) * order(t - 0.002) / 640 for t in time]
        trace[s + "_IDC"] = current
        trace[s + "_KCL_IDC"] = current[:]
        for n, v in {"VDC": 640.0, "VDC_POS": 320.0, "VDC_NEG": -320.0, "Q": 0.0,
                     "BLOCK": 0.0, "PLL_LOCKED": 1.0, "LIMIT_ACTIVE": 0.0}.items():
            trace[s + "_" + n] = [v] * len(time)
        for phase in "ABC":
            for q in ("UPPER", "LOWER"):
                arm = f"{s}_{phase}_{q}"
                trace[arm + "_I"] = [-v / 3 for v in current]
                trace[arm + "_INET"] = trace[arm + "_I"][:]
                trace[arm + "_VT"] = [0.15 * v for v in trace[arm + "_I"]]
                trace[f"{s}_M_{phase}_{q}_RAW"] = [0.5] * len(time)
                for n, v in {"W": capacitance * 640**2 / 8, "VCAP": 320.0, "PLOSS": 0.0, "PSWITCH": 0.0}.items():
                    trace[arm + "_" + n] = [v] * len(time)
    parameters = {"active_power_order_mw": 1000.0, "reactive_power_order_mvar": 0.0,
                  "vdc_order_kv": 640.0, "frequency_hz": 60.0,
                  "station_p_valve_voltage_kv": 320.0, "station_vdc_valve_voltage_kv": 320.0,
                  "arm": {"C_eq_F": capacitance, "R_arm_ohm": 0.15, "L_arm_H": 0.05,
                          "P_nonohmic_MW": 0.0, "V_loss_floor_kV": 0.01}}
    startup = {"status": "PASS", "power_start_time_s": 0.2, "reversal_window_s": [1.0, 2.0],
               "operating_windows": {"forward": [0.6, 0.9], "reverse": [2.5, 2.8]}}
    return trace, parameters, startup


def test_normal_dynamics_do_not_claim_protection_or_complete_model_acceptance(evidence):
    result = evaluate_native_dynamic_envelope(*evidence)
    assert result["status"] == "PASS", result["failed_checks"]
    assert result["model_accepted"] is False
    assert result["windows"]["reversal"]["command_zero_s"] < result["windows"]["reversal"]["measured_reverse_s"]


@pytest.mark.parametrize("channel,index,value,failed", [
    ("P_VDC", 1600, 710.0, "normal:P:dc_voltage_deviation_pu"),
    ("V_A_UPPER_VCAP", 1700, 280.0, "normal:V:capacitor_voltage_deviation_pu"),
    ("P_M_A_UPPER_RAW", 1700, 0.01, "normal:P:dynamic_insertion_margin"),
    ("V_PLL_LOCKED", 1800, 0.0, "normal:V:continuous_control"),
    ("P_P", 1400, -20.0, "reversal:command_precedes_direction_change"),
    ("P_P", 2200, -1200.0, "reversal:power_overshoot"),
    ("P_IDC", 2600, 1.0, "reverse:P:dc_current_direction"),
    ("P_A_UPPER_VT", 650, -20.0, "forward:P:power_balance"),
    ("PROTECTION_TRIP", 2900, 1.0, "normal:protection_inactive"),
])
def test_one_bad_sample_is_not_hidden_by_valid_steady_averages(evidence, channel, index, value, failed):
    evidence[0][channel][index] = value
    result = evaluate_native_dynamic_envelope(*evidence)
    assert result["status"] == "FAIL"
    assert failed in result["failed_checks"]


def test_missing_switch_loss_and_invalid_or_uncovered_evidence_cannot_pass(evidence):
    missing = copy.deepcopy(evidence)
    del missing[0]["V_C_LOWER_PSWITCH"]
    assert evaluate_native_dynamic_envelope(*missing)["missing_channels"] == ["V_C_LOWER_PSWITCH"]
    invalid = copy.deepcopy(evidence)
    invalid[0]["P_P"][700] = math.nan
    assert evaluate_native_dynamic_envelope(*invalid)["status"] == "FAIL"
    short = copy.deepcopy(evidence)
    short[2]["reversal_window_s"][1] = 3.0
    assert evaluate_native_dynamic_envelope(*short)["status"] == "FAIL"
