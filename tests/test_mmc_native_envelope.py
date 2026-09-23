import pytest

from pscad_mcp.hvdc.builders.mmc.native_envelope import evaluate_native_steady_envelope


def _trace():
    time = [i / 10000 for i in range(20001)]
    power = [1000.0 if t < 1.0 else -1000.0 for t in time]
    return {
        "time": time, "P_P": power, "P_Q": [0.0] * len(time), "V_Q": [0.0] * len(time),
        "P_VDC": [640.0] * len(time), "V_VDC": [640.0] * len(time),
        "P_IDC": [p / 640 for p in power], "V_IDC": [-p / 640 for p in power],
    }


def test_steady_envelope_matches_derived_ratings_without_claiming_full_acceptance():
    result = evaluate_native_steady_envelope(_trace(), power_mw=1000, voltage_kv=640)
    assert result["status"] == "PASS"
    assert result["model_accepted"] is False


@pytest.mark.parametrize("defect", ["oscillation", "wrong_direction", "overcurrent", "missing"])
def test_bounded_or_mean_correct_data_cannot_hide_steady_defects(defect):
    trace = _trace()
    if defect == "oscillation":
        trace["V_VDC"] = [640 + (100 if i % 2 else -100) for i in range(len(trace["time"]))]
    elif defect == "wrong_direction":
        trace["P_P"] = [1000.0] * len(trace["time"])
    elif defect == "overcurrent":
        trace["P_IDC"][7000] = 2.0
    else:
        del trace["V_Q"]
    assert evaluate_native_steady_envelope(trace, power_mw=1000, voltage_kv=640)["status"] == "FAIL"
