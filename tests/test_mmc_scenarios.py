from pscad_mcp.hvdc.builders.mmc.scenarios import recommend_scenarios
from pscad_mcp.hvdc.scenarios import validate_scenario
from tests.mmc_parametric_fakes import avm_design, pwm_design


REQUIRED = {
    "startup",
    "forward_steady",
    "active_power_step",
    "reactive_power_step",
    "power_reversal",
    "reverse_steady",
    "ac_three_phase_fault",
    "ac_single_line_ground_fault",
    "dc_pole_to_pole_fault",
    "dc_pole_to_ground_fault",
    "post_fault_recovery",
}


def test_recommendations_are_directly_runnable_and_model_aware() -> None:
    pwm = recommend_scenarios(pwm_design())
    avm = recommend_scenarios(avm_design())

    assert {item.name for item in pwm} == REQUIRED
    assert {item.name for item in avm} == REQUIRED
    assert all(item.scenario["profile"].startswith("mmc_") for item in pwm + avm)
    assert all(
        validate_scenario(item.to_dict()["scenario"])["valid"] for item in pwm + avm
    )
    assert max(item.time_step_s for item in pwm) < max(
        item.time_step_s for item in avm
    )
    assert all(
        item.capabilities["intrinsic_dc_fault_blocking"] is False
        for item in pwm + avm
    )


def test_dc_fault_recommendations_require_protection_and_diode_evidence() -> None:
    recommendations = {
        item.name: item for item in recommend_scenarios(avm_design())
    }

    for name in ("dc_pole_to_pole_fault", "dc_pole_to_ground_fault"):
        item = recommendations[name]
        targets = [event["target"] for event in item.scenario["events"]]
        assert targets == [
            "dc_fault_command",
            "block_command",
            "dc_breaker_command",
            "dc_fault_command",
            "dc_breaker_command",
            "block_command",
        ]
        roles = {metric["role"] for metric in item.metrics}
        assert {"dc_current", "diode_equivalent_current", "dc_breaker_status"} <= roles
        assert "intrinsic_dc_fault_blocking" in " ".join(item.limitations)


def test_recommendations_bind_exact_units_metrics_and_timing() -> None:
    for design in (pwm_design(), avm_design()):
        for item in recommend_scenarios(design):
            assert item.time_step_s > 0
            assert item.duration_s > 0
            assert item.scenario["time_step_s"] == item.time_step_s
            assert item.scenario["duration_s"] == item.duration_s
            assert item.metrics
            assert all(metric["selector"] and metric["units"] for metric in item.metrics)
            assert item.thresholds
            assert item.preconditions
