import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.derivation import derive_mmc_parameters
from pscad_mcp.hvdc.builders.mmc.electrical import arm_energy
from pscad_mcp.hvdc.builders.mmc.parametric_models import parse_parametric_request
from tests.mmc_parametric_fakes import valid_request


def test_common_base_quantities_are_dimensionally_correct() -> None:
    report = derive_mmc_parameters(parse_parametric_request(valid_request()))
    assert report.common["dc_current_ka"] == pytest.approx(1000.0 / 640.0)
    assert report.common["station_p_grid_impedance_ohm"] == pytest.approx(
        230.0**2 / (5.0 * 1000.0)
    )
    assert {candidate.engine for candidate in report.candidates} == {"detailed_pwm", "average_value"}


def test_grid_impedance_uses_requested_ac_rating_without_dc_rescaling() -> None:
    base = derive_mmc_parameters(parse_parametric_request(valid_request()))
    scaled = derive_mmc_parameters(
        parse_parametric_request(valid_request(dc_voltage_kv=1280.0, active_power_mw=2000.0))
    )
    assert scaled.common["dc_current_ka"] == pytest.approx(base.common["dc_current_ka"])
    assert scaled.common["station_p_grid_impedance_ohm"] == pytest.approx(
        230.0**2 / (5.0 * 2000.0)
    )
    assert scaled.common["station_p_grid_impedance_ohm"] == pytest.approx(
        0.5 * base.common["station_p_grid_impedance_ohm"]
    )


def test_ac_voltage_and_power_scaling_preserves_requested_scr() -> None:
    request = valid_request(dc_voltage_kv=1280.0, active_power_mw=2000.0)
    for station in ("station_p", "station_vdc"):
        request[station] = {**request[station], "ac_voltage_kv": 460.0}
    scaled = derive_mmc_parameters(request)
    for station in ("station_p", "station_vdc"):
        resistance = scaled.common[f"{station}_grid_r_ohm"]
        reactance = scaled.common[f"{station}_grid_x_ohm"]
        impedance = (resistance**2 + reactance**2) ** 0.5
        assert 460.0**2 / (2000.0 * impedance) == pytest.approx(
            request[station]["short_circuit_ratio"]
        )
        assert reactance / resistance == pytest.approx(request[station]["x_over_r"])


def test_candidates_are_bounded_ordered_and_have_unique_parameter_hashes() -> None:
    report = derive_mmc_parameters(parse_parametric_request(valid_request(model_fidelity="detailed_pwm")))
    assert [item.purpose for item in report.candidates] == [
        "nominal", "numerical_stability", "control_stability", "energy_balance"
    ]
    assert len({item.parameter_hash for item in report.candidates}) == 4


def test_analytically_infeasible_request_returns_failed_constraints() -> None:
    report = derive_mmc_parameters(
        parse_parametric_request(valid_request(active_power_mw=10000.0, dc_voltage_kv=100.0))
    )
    assert report.feasible is False
    assert any(not item.passed for item in report.constraints)


def _assert_candidate_arm_energy(candidate, dc_voltage_kv):
    parameters = candidate.parameters
    target_voltage_v = dc_voltage_kv * 1000.0 / 2.0
    expected_energy_j = parameters["stored_energy_mj"] * 1e6 / 12.0
    assert arm_energy(
        parameters["equivalent_arm_capacitance_f"], target_voltage_v
    ) == pytest.approx(expected_energy_j, rel=1e-12)


@pytest.mark.parametrize("dc_voltage_kv, power_mw", [(640.0, 1000.0), (1280.0, 2000.0)])
def test_all_candidates_preserve_half_dc_voltage_energy_identity(dc_voltage_kv, power_mw):
    report = derive_mmc_parameters(
        valid_request(dc_voltage_kv=dc_voltage_kv, active_power_mw=power_mw)
    )
    for candidate in report.candidates:
        _assert_candidate_arm_energy(candidate, dc_voltage_kv)
    assert all(
        candidate.parameters["equivalent_capacitor_voltage_target_kv"] == dc_voltage_kv / 2.0
        for candidate in report.candidates
    )
    for engine in ("detailed_pwm", "average_value"):
        nominal, _, _, energy_balance = [
            candidate for candidate in report.candidates if candidate.engine == engine
        ]
        assert energy_balance.parameters["equivalent_arm_capacitance_f"] == pytest.approx(
            nominal.parameters["equivalent_arm_capacitance_f"] * 1.2
        )


def test_stored_energy_override_recomputes_equivalent_capacitance():
    report = derive_mmc_parameters(
        valid_request(
            engineering_overrides={"stored_energy_mj": {"value": 48e6, "unit": "J"}}
        )
    )
    for candidate in report.candidates:
        assert candidate.parameters["stored_energy_mj"] == pytest.approx(
            57.6 if candidate.purpose == "energy_balance" else 48.0
        )
        _assert_candidate_arm_energy(candidate, 640.0)


def test_public_joule_and_megajoule_overrides_produce_identical_candidates():
    requests = [
        parse_parametric_request(
            valid_request(
                engineering_overrides={"stored_energy_mj": {"value": value, "unit": unit}}
            )
        )
        for value, unit in [(48.0, "MJ"), (48e6, "J")]
    ]
    megajoules, joules = [derive_mmc_parameters(request) for request in requests]

    assert megajoules.candidates == joules.candidates
    assert megajoules.candidates[0].parameters["stored_energy_mj"] == 48.0
    for candidate in megajoules.candidates:
        _assert_candidate_arm_energy(candidate, 640.0)


@pytest.mark.parametrize("value, unit", [(80e-6, "F"), (80.0, "uF")])
def test_capacitance_override_recomputes_stored_energy(value, unit):
    report = derive_mmc_parameters(
        valid_request(
            engineering_overrides={
                "equivalent_arm_capacitance_f": {"value": value, "unit": unit}
            }
        )
    )
    for candidate in report.candidates:
        multiplier = 1.2 if candidate.purpose == "energy_balance" else 1.0
        assert candidate.parameters["stored_energy_mj"] == pytest.approx(49.152 * multiplier)
        assert candidate.parameters["equivalent_arm_capacitance_f"] == pytest.approx(
            80e-6 * multiplier
        )
        _assert_candidate_arm_energy(candidate, 640.0)


def test_consistent_energy_and_capacitance_overrides_are_preserved():
    report = derive_mmc_parameters(
        valid_request(
            engineering_overrides={
                "stored_energy_mj": {"value": 49.152e6, "unit": "J"},
                "equivalent_arm_capacitance_f": {"value": 80.0, "unit": "uF"},
            }
        )
    )
    for candidate in report.candidates:
        _assert_candidate_arm_energy(candidate, 640.0)
    assert report.candidates[0].parameters["stored_energy_mj"] == pytest.approx(49.152)
    assert report.candidates[0].parameters["equivalent_arm_capacitance_f"] == pytest.approx(80e-6)


def test_inconsistent_energy_and_capacitance_overrides_are_rejected():
    with pytest.raises(BackendError) as raised:
        derive_mmc_parameters(
            valid_request(
                engineering_overrides={
                    "stored_energy_mj": {"value": 40e6, "unit": "J"},
                    "equivalent_arm_capacitance_f": {"value": 80e-6, "unit": "F"},
                }
            )
        )
    assert raised.value.code == "MMC_ENERGY_INFEASIBLE"


@pytest.mark.parametrize(
    "name, unit",
    [("stored_energy_mj", "J"), ("equivalent_arm_capacitance_f", "F")],
)
@pytest.mark.parametrize("value", [0.0, -1.0])
def test_nonpositive_energy_and_capacitance_overrides_are_rejected(name, unit, value):
    with pytest.raises(BackendError) as raised:
        derive_mmc_parameters(
            valid_request(engineering_overrides={name: {"value": value, "unit": unit}})
        )
    assert raised.value.code == "MMC_ENERGY_INFEASIBLE"


@pytest.mark.parametrize(
    "name, unit",
    [("stored_energy_mj", "MW"), ("equivalent_arm_capacitance_f", "H")],
)
def test_energy_overrides_reject_incompatible_units(name, unit):
    with pytest.raises(BackendError) as raised:
        derive_mmc_parameters(
            valid_request(engineering_overrides={name: {"value": 1.0, "unit": unit}})
        )
    assert raised.value.code == "MMC_REQUEST_INVALID"


def test_half_dc_capacitor_voltage_target_is_not_an_independent_override():
    with pytest.raises(BackendError) as raised:
        derive_mmc_parameters(
            valid_request(
                engineering_overrides={
                    "equivalent_capacitor_voltage_target_kv": {"value": 200.0, "unit": "kV"}
                }
            )
        )
    assert raised.value.code == "MMC_REQUEST_INVALID"
