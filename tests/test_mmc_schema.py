import copy
import math

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.schema import parse_blueprint


def _arm(station: str, phase: str, arm: str) -> dict:
    return {
        "logical_id": f"{station}.{phase}.{arm}",
        "station_role": station.split("_")[-1],
        "phase": phase,
        "arm": arm,
        "definition": "cigre_mmc_avm_v1:MMCAverageArm",
        "location": {"x": 100, "y": 100},
        "parameters": {"C_eq_F": 0.01, "L_arm_H": 0.1, "R_arm_ohm": 0.01},
        "ports": ["ac", "dc", "control"],
    }


def valid_blueprint() -> dict:
    stations = []
    for role in ("P", "VDC"):
        station_name = f"STATION_{role}"
        stations.append(
            {
                "logical_id": station_name,
                "role": role,
                "ac_component": f"{station_name}.ac",
                "arms": [_arm(station_name, phase, arm) for phase in ("A", "B", "C") for arm in ("upper", "lower")],
                "control_contract": {
                    "role": role,
                    "active_power_command": "P_order",
                    "reactive_power_command": "Q_order",
                    "dc_voltage_command": "Vdc_order" if role == "VDC" else None,
                },
            }
        )
    return {
        "schema_version": 1,
        "name": "cigre_b4_p2p_avm_v1",
        "profile": "cigre_b4_p2p_avm_v1",
        "nominal_vdc_kv": 640.0,
        "nominal_power_mw": 1000.0,
        "settings": {"time_step_s": 5e-5, "output_step_s": 5e-5, "simulation_duration_s": 2.0},
        "stations": stations,
        "components": [
            {
                "logical_id": "STATION_P.ac",
                "definition": "master:source3",
                "location": {"x": 0, "y": 0},
                "parameters": {"Amplitude": 230.0},
                "ports": ["ac"],
            },
            {
                "logical_id": "STATION_VDC.ac",
                "definition": "master:source3",
                "location": {"x": 0, "y": 200},
                "parameters": {"Amplitude": 230.0},
                "ports": ["ac"],
            },
        ],
        "nets": [
            {"logical_id": "dc_positive", "kind": "electrical", "endpoints": ["STATION_P.dc_pos", "STATION_VDC.dc_pos"]},
            {"logical_id": "dc_negative", "kind": "electrical", "endpoints": ["STATION_P.dc_neg", "STATION_VDC.dc_neg"]},
        ],
        "outputs": [
            {"logical_id": "vdc_pole_to_pole", "path": "Main/VDC_P2P", "units": "kV", "role": "dc_voltage_pole_to_pole"},
            {"logical_id": "p_ac_p", "path": "Main/STATION_P/P_AC", "units": "MW", "role": "station_ac_active_power"},
            {"logical_id": "q_ac_p", "path": "Main/STATION_P/Q_AC", "units": "MVAr", "role": "station_ac_reactive_power"},
            {"logical_id": "arm_current_p_a_upper", "path": "Main/STATION_P/A_UPPER/I", "units": "kA", "role": "arm_current"},
        ],
        "control_contract": {
            "version": "mmc-control-v1",
            "active_power_command": "P_order",
            "reactive_power_command": "Q_order",
            "equations": {
                "arm_current": "i_upper = I_dc / 3 + i_phase / 2 + i_circulating",
                "arm_current_lower": "i_lower = I_dc / 3 - i_phase / 2 + i_circulating",
                "energy": "W_arm = 0.5 * C_eq * V_cap_eq^2",
                "energy_derivative": "dW_arm/dt = v_inserted * i_arm - p_loss_arm",
            },
            "modulation_bounds": [0.0, 1.0],
        },
        "sequence": [
            {"name": "blocked_precharge", "order": 1, "entry_condition": "reset", "exit_condition": "ready", "duration_s": 0.1, "outputs": ["vdc_pole_to_pole"]},
            {"name": "ready_to_deblock", "order": 2, "entry_condition": "ready", "exit_condition": "deblocked", "duration_s": 0.1, "outputs": ["vdc_pole_to_pole"]},
            {"name": "forward_ramp", "order": 3, "entry_condition": "deblocked", "exit_condition": "forward", "duration_s": 0.5, "outputs": ["p_ac_p"]},
            {"name": "forward_steady", "order": 4, "entry_condition": "forward", "exit_condition": "reversal", "duration_s": 0.5, "outputs": ["p_ac_p"]},
            {"name": "power_reversal", "order": 5, "entry_condition": "reversal", "exit_condition": "reverse", "duration_s": 0.5, "outputs": ["p_ac_p"]},
            {"name": "reverse_steady", "order": 6, "entry_condition": "reverse", "exit_condition": "complete", "duration_s": 0.5, "outputs": ["p_ac_p"]},
        ],
        "acceptance_checks": [
            {"name": "precharge_ready", "kind": "window", "required": True, "expected": {"finite": True, "channels": ["vdc_pole_to_pole"]}, "units": "kV", "comparison_window": [0.0, 0.1]},
            {"name": "forward_steady", "kind": "window", "required": True, "expected": {"power_mw": 1000.0, "channels": ["p_ac_p"]}, "units": "MW", "comparison_window": [0.6, 1.0]},
            {"name": "power_reversal", "kind": "window", "required": True, "expected": {"direction": "negative", "channels": ["p_ac_p"]}, "units": "MW", "comparison_window": [1.0, 1.5]},
            {"name": "reverse_steady", "kind": "window", "required": True, "expected": {"power_mw": -1000.0, "channels": ["p_ac_p"]}, "units": "MW", "comparison_window": [1.5, 2.0]},
        ],
    }


def assert_invalid(value: dict, *, fragment: str | None = None) -> None:
    with pytest.raises(BackendError) as raised:
        parse_blueprint(value)
    assert raised.value.code == "MMC_BLUEPRINT_INVALID"
    if fragment:
        assert fragment in str(raised.value)


def test_valid_fixed_blueprint_parses_exact_stations_arms_sequence_and_windows():
    blueprint = parse_blueprint(valid_blueprint())
    assert blueprint.profile == "cigre_b4_p2p_avm_v1"
    assert blueprint.control_contract.version == "mmc-control-v1"
    assert {station.role for station in blueprint.stations} == {"P", "VDC"}
    assert [len(station.arms) for station in blueprint.stations] == [6, 6]
    assert [phase.name for phase in blueprint.sequence] == [
        "blocked_precharge", "ready_to_deblock", "forward_ramp", "forward_steady", "power_reversal", "reverse_steady"
    ]
    assert [check.name for check in blueprint.acceptance_checks] == [
        "precharge_ready", "forward_steady", "power_reversal", "reverse_steady"
    ]
    assert {output.units for output in blueprint.outputs} == {"kV", "MW", "MVAr", "kA"}


@pytest.mark.parametrize("field", ["unknown", "_extra"])
def test_schema_rejects_unknown_top_level_fields(field):
    value = valid_blueprint()
    value[field] = 1
    assert_invalid(value, fragment="unknown field")


def test_schema_rejects_missing_fields_and_bad_station_roles():
    value = valid_blueprint()
    del value["control_contract"]
    assert_invalid(value, fragment="control_contract")

    value = valid_blueprint()
    value["stations"][1]["role"] = "Q"
    assert_invalid(value, fragment="role")


def test_schema_rejects_non_finite_values_and_non_string_mapping_keys():
    value = valid_blueprint()
    value["nominal_power_mw"] = math.inf
    assert_invalid(value, fragment="finite")

    value = valid_blueprint()
    value["settings"]["compiler_target"] = {1: "not-json"}
    assert_invalid(value, fragment="keys must be strings")


def test_schema_rejects_duplicate_ids_ports_and_wrong_arm_count():
    value = valid_blueprint()
    value["components"].append(copy.deepcopy(value["components"][0]))
    assert_invalid(value, fragment="logical IDs")

    value = valid_blueprint()
    value["stations"][0]["arms"] = value["stations"][0]["arms"][:-1]
    assert_invalid(value, fragment="six")

    value = valid_blueprint()
    value["stations"][0]["arms"][0]["ports"].append("ac")
    assert_invalid(value, fragment="ports")


def test_schema_requires_positive_steps_and_exact_acceptance_windows():
    value = valid_blueprint()
    value["settings"]["time_step_s"] = 0
    assert_invalid(value, fragment="positive")

    value = valid_blueprint()
    value["acceptance_checks"] = value["acceptance_checks"][:-1]
    assert_invalid(value, fragment="four")


def test_schema_requires_declared_same_unit_acceptance_channels():
    value = valid_blueprint()
    del value["acceptance_checks"][0]["expected"]["channels"]
    assert_invalid(value, fragment="channels")

    value = valid_blueprint()
    value["acceptance_checks"][1]["expected"]["channels"] = ["unknown_output"]
    assert_invalid(value, fragment="unknown output")

    value = valid_blueprint()
    value["acceptance_checks"][0]["expected"]["channels"] = ["p_ac_p"]
    assert_invalid(value, fragment="units")


def test_schema_rejects_wrong_equation_and_output_unit():
    value = valid_blueprint()
    value["control_contract"]["equations"]["arm_current_lower"] = "wrong"
    assert_invalid(value, fragment="equations")

    value = valid_blueprint()
    value["outputs"][0]["units"] = "MW"
    assert_invalid(value, fragment="units")
