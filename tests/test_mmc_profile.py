from __future__ import annotations

from pscad_mcp.hvdc.profiles import load_profile


def test_fixed_mmc_profile_exposes_project_qualified_read_only_selectors():
    profile = load_profile("cigre_b4_p2p_avm_v1")

    assert profile["profile_version"] == 2
    assert profile["command_bindings"] == []
    assert profile["project_fingerprints"] == [
        {
            "project_stem": "MMC_STAGE_A",
            "pscad_version": "4.6.2",
            "definitions": [
                "cigre_mmc_avm_v1:MMCAverageArm",
                "cigre_mmc_avm_v1:MMCStationControl",
                "cigre_mmc_avm_v1:MMCEnergyControl",
                "cigre_mmc_avm_v1:MMCInitialization",
            ],
        }
    ]

    selectors = {item["canonical"]: item for item in profile["result_channels"]}
    assert len(selectors) == 80
    assert selectors["vdc_pole_to_pole"] == {
        "canonical": "vdc_pole_to_pole",
        "path": "Main/VDC_P2P",
        "units": "kV",
        "location": "Main",
    }
    assert selectors["p_ac_p"]["units"] == "MW"
    assert selectors["arm_current_p_a_upper"]["path"] == "Main/STATION_P/A_UPPER/I"
    assert selectors["cap_v_vdc_c_lower"]["units"] == "kV"
    assert sum(item["canonical"].startswith("arm_current_") for item in selectors.values()) == 12
    assert sum(item["canonical"].startswith("arm_energy_") for item in selectors.values()) == 12
    assert sum(item["canonical"].startswith("cap_v_") for item in selectors.values()) == 12
