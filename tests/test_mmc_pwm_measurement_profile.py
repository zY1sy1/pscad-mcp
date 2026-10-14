"""Public measurement names must identify the physical probes and exact units."""

from pscad_mcp.hvdc.builders.mmc import pwm_channels
from pscad_mcp.hvdc.profiles import bind_profile_project
from pscad_mcp.hvdc.results import resolve_result_channels


def test_routed_profile_replaces_uninstantiated_placeholder_channels():
    prepared = {
        "routing": {"command_bindings": []},
        "channels": {
            "channels": [{
                "channel_id": "MFE_T2_p_active", "role": "p_active",
                "model_scope": "T2", "units": "MW", "dimension": 1,
                "selector": {"description": "MFE_T2_p_active", "group": "MMC_FAULT_EVIDENCE", "owner_id": "42"},
                "signal_source": {"kind": "physical_state", "polarity": "station_import"},
            }],
            "diagnostic_channels": [],
        },
    }
    profile = pwm_channels.routed_pwm_profile(prepared)
    assert len(profile["result_channels"]) == 1
    result = profile["result_channels"][0]
    assert result["path"].endswith("/MFE_T2_p_active")
    assert result["units"] == "MW"
    assert result["selector"]["owner_id"] == "42"
    assert profile["mappings"][0]["aliases"] == ["MFE_T2_p_active"]
    assert "extends" not in profile
    rebound = bind_profile_project(profile, "PWM_RENAMED.pscx")
    resolved = resolve_result_channels({"channels": [{
        "path": "MMC_FAULT_EVIDENCE/MFE_T2_p_active", "units": "MW",
        "domain": [0, 1], "values": [-1000, -1000],
    }]}, rebound)
    assert len(resolved["resolved_channels"]) == 1
    assert resolved["warnings"] == []
