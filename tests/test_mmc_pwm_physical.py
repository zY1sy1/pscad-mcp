"""Missing or flat physical data cannot establish PWM acceptance."""

from pscad_mcp.hvdc.builders.mmc.pwm_physical import evaluate_routed_pwm_samples


def test_missing_arm_data_remains_incomplete():
    result = evaluate_routed_pwm_samples(
        {"channels": []},
        {"channels": []},
        {
            "duration_s": 1.0,
            "output_step_s": 0.01,
            "analysis": {"thresholds": {}},
            "name": "forward_steady",
            "events": [],
        },
    )
    assert result["status"] == "INCOMPLETE_ANALYSIS"
    assert result["model_accepted"] is False
    assert any(
        c["name"] == "complete_i_arm" and not c["passed"] for c in result["checks"]
    )


def test_incorrect_units_are_rejected_before_any_electrical_verdict():
    binding = {"channel_id": "dc", "role": "v_dc", "units": "kV"}
    trace = {
        "channel_id": "dc",
        "units": "V",
        "domain": [0, 0.01, 0.02],
        "values": [640, 640, 640],
    }
    result = evaluate_routed_pwm_samples(
        {"channels": [trace]},
        {"channels": [binding]},
        {
            "duration_s": 0.02,
            "output_step_s": 0.01,
            "analysis": {"thresholds": {}},
            "name": "forward_steady",
            "events": [],
        },
    )
    assert result["status"] == "INCOMPLETE_ANALYSIS"
    assert result["checks"][0]["passed"] is False
