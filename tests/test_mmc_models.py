import math

import pytest

from pscad_mcp.hvdc.builders.mmc.models import (
    MmcAcceptanceCheck,
    MmcArmSpec,
    MmcBlueprint,
    MmcBuildPlan,
    MmcBuildRecord,
    MmcBuildState,
    MmcComponentSpec,
    MmcControlContract,
    MmcNetSpec,
    MmcOutputSpec,
    MmcPlanOperation,
    MmcSequencePhase,
    MmcStationSpec,
)


def test_mmc_build_state_contains_explicit_stage_a_sequence():
    assert [state.value for state in MmcBuildState] == [
        "validated",
        "staging_created",
        "components_placed",
        "parameters_verified",
        "connections_verified",
        "structure_verified",
        "staging_saved",
        "compiled",
        "startup_simulated",
        "forward_simulated",
        "reversal_simulated",
        "reverse_simulated",
        "acceptance_passed",
        "published",
        "failed",
        "timed_out",
        "interrupted",
    ]


def test_mmc_records_are_frozen_and_json_safe():
    arm = MmcArmSpec(
        logical_id="STATION_P.A.upper",
        station_role="P",
        phase="A",
        arm="upper",
        definition="cigre_mmc_avm_v1:MMCAverageArm",
        location=(100, 100),
        parameters={"C_eq_F": 0.01, "L_arm_H": 0.1, "R_arm_ohm": 0.01},
        ports=("ac", "dc", "control"),
    )
    station = MmcStationSpec(
        logical_id="STATION_P",
        role="P",
        arms=(arm,),
        ac_component="station_p.ac",
        control_contract=MmcControlContract(
            role="P",
            active_power_command="P_order",
            reactive_power_command="Q_order",
            dc_voltage_command=None,
        ),
    )
    component = MmcComponentSpec(
        logical_id="station_p.ac",
        definition="master:source3",
        location=(0, 0),
        parameters={"Amplitude": 230.0},
        ports=("ac",),
    )
    net = MmcNetSpec(
        logical_id="ac_p",
        kind="electrical",
        endpoints=("station_p.ac:ac", "STATION_P.A.upper:ac"),
    )
    output = MmcOutputSpec(
        logical_id="station_p.p_ac",
        path="Main/STATION_P/P_AC",
        units="MW",
        role="station_ac_active_power",
    )
    phase = MmcSequencePhase(
        name="blocked_precharge",
        order=1,
        entry_condition="reset",
        exit_condition="ready",
        duration_s=0.1,
        outputs=("station_p.p_ac",),
    )
    check = MmcAcceptanceCheck(
        name="precharge_ready",
        kind="window",
        required=True,
        expected={"finite": True},
        units="s",
        comparison_window=(0.0, 0.1),
    )
    blueprint = MmcBlueprint(
        schema_version=1,
        name="cigre_b4_p2p_avm_v1",
        profile="cigre_b4_p2p_avm_v1",
        nominal_vdc_kv=640.0,
        nominal_power_mw=1000.0,
        settings={"time_step_s": 5e-5, "output_step_s": 5e-5, "simulation_duration_s": 2.0},
        stations=(station,),
        components=(component,),
        nets=(net,),
        outputs=(output,),
        control_contract=MmcControlContract(
            role="link",
            active_power_command="P_order",
            reactive_power_command="Q_order",
            equations={
                "arm_current": "i_upper = I_dc / 3 + i_phase / 2 + i_circulating",
                "arm_current_lower": "i_lower = I_dc / 3 - i_phase / 2 + i_circulating",
                "energy": "W_arm = 0.5 * C_eq * V_cap_eq^2",
                "energy_derivative": "dW_arm/dt = v_inserted * i_arm - p_loss_arm",
            },
        ),
        sequence=(phase,),
        acceptance_checks=(check,),
    )
    record = MmcBuildRecord(build_id="b1", state=MmcBuildState.VALIDATED, plan=None)
    plan = MmcBuildPlan(blueprint=blueprint, operations=(), plan_hash="a" * 64)

    assert blueprint.to_dict()["settings"]["time_step_s"] == 5e-5
    assert record.to_dict()["state"] == "validated"
    assert plan.to_dict()["blueprint"]["profile"] == "cigre_b4_p2p_avm_v1"
    with pytest.raises(TypeError):
        blueprint.settings["new"] = 1
    with pytest.raises(TypeError):
        blueprint.settings["time_step_s"] = math.nan
