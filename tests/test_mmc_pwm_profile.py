"""Exact global probe descriptions remain valid when the project is renamed."""

from pscad_mcp.hvdc.builders.mmc.pwm_channels import routed_pwm_profile
from pscad_mcp.hvdc.profiles import bind_profile_project


def test_physical_probe_profile_can_bind_to_a_timed_scenario(tmp_path):
    prepared = {
        "routing": {"command_bindings": []},
        "channels": {
            "channels": [
                {
                    "channel_id": "MFE_T2_p_active",
                    "role": "p_active",
                    "model_scope": "T2",
                    "units": "MW",
                    "definition_name": "Main",
                    "selector": {"description": "MFE_T2_p_active"},
                }
            ],
            "diagnostic_channels": [],
        },
    }
    profile = bind_profile_project(
        routed_pwm_profile(prepared), tmp_path / "PWM_renamed.pscx"
    )
    assert profile["result_channels"][0]["path"] == "MFE_T2_p_active"
    assert profile["result_channels"][0]["canonical"] == "station_p_active_power"
