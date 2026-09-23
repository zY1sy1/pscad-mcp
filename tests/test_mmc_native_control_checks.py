import math

import pytest

from pscad_mcp.hvdc.builders.mmc.native_control_checks import evaluate_native_dq_controls
from tests.test_mmc_native_physical import balanced_measurements


def trace_and_parameters():
    trace = balanced_measurements()
    for s in ("P", "V"):
        for name, value in {
            "PLL_FREQUENCY": 60.0, "PLL_ERROR": 0.0, "PLL_LOCKED": 1.0, "PLL_LIMITED": 0.0,
            "PLL_INTEGRATOR": 0.0, "BLOCK": 0.0, "ID_MEASURED": 2.0, "ID_REFERENCE": 2.0,
            "IQ_MEASURED": 0.0, "IQ_REFERENCE": 0.0, "ID_INTEGRATOR": 0.1,
            "IQ_INTEGRATOR": 0.1, "LIMIT_ACTIVE": 0.0, "LIMIT_DURATION": 0.0,
        }.items():
            trace[s + "_" + name] = [value] * len(trace["time"])
    parameters = {"active_power_order_mw": 1000.0, "reactive_power_order_mvar": 0.0,
                  "vdc_order_kv": 640.0, "frequency_hz": 60.0,
                  "station_p_valve_voltage_kv": 350.0, "station_vdc_valve_voltage_kv": 350.0,
                  "arm": {"C_eq_F": 6.510416666666667e-5}}
    return trace, parameters


def test_complete_steady_control_evidence_remains_a_partial_scope():
    trace, parameters = trace_and_parameters()
    result = evaluate_native_dq_controls(trace, parameters, {"steady": (0.02, 0.12)})
    assert result["status"] == "PASS"
    assert result["model_accepted"] is False


@pytest.mark.parametrize("channel, value, check", [
    ("P_PLL_LOCKED", 0.0, "pll_locked"),
    ("P_PLL_FREQUENCY", 60.3, "pll_frequency"),
    ("P_PLL_ERROR", math.radians(3), "pll_phase"),
    ("P_ID_MEASURED", 2.5, "D_current_tracking"),
    ("P_M_A_UPPER_RAW", 0.049, "insertion_margin"),
    ("P_A_UPPER_VCAP", 353.0, "capacitor_voltage"),
    ("P_LIMIT_ACTIVE", 1.0, "no_steady_saturation"),
])
def test_one_bad_control_sample_cannot_be_hidden_by_averages(channel, value, check):
    trace, parameters = trace_and_parameters()
    trace[channel][500] = value
    result = evaluate_native_dq_controls(trace, parameters, {"steady": (0.02, 0.12)})
    assert result["status"] == "FAIL"
    assert "steady:P:" + check in result["failed_checks"]


def test_missing_nonfinite_and_uncovered_control_evidence_is_rejected():
    trace, parameters = trace_and_parameters()
    del trace["P_PLL_ERROR"]
    assert evaluate_native_dq_controls(trace, parameters, {"steady": (0.02, 0.12)})["status"] == "FAIL"
    trace, parameters = trace_and_parameters()
    trace["P_PLL_ERROR"][500] = math.nan
    assert evaluate_native_dq_controls(trace, parameters, {"steady": (0.02, 0.12)})["status"] == "FAIL"
    trace, parameters = trace_and_parameters()
    assert evaluate_native_dq_controls(trace, parameters, {"steady": (0.02, 0.3)})["status"] == "FAIL"
