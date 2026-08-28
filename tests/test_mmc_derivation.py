import pytest

from pscad_mcp.hvdc.builders.mmc.derivation import derive_mmc_parameters
from pscad_mcp.hvdc.builders.mmc.parametric_models import parse_parametric_request
from tests.mmc_parametric_fakes import valid_request


def test_common_base_quantities_are_dimensionally_correct() -> None:
    report = derive_mmc_parameters(parse_parametric_request(valid_request()))
    assert report.common["dc_current_ka"] == pytest.approx(1000.0 / 640.0)
    assert report.common["station_p_grid_impedance_ohm"] == pytest.approx(
        230.0**2 / (5.0 * 1000.0)
    )
    assert {candidate.engine for candidate in report.candidates} == {"detailed_pwm", "average_value"}


def test_voltage_and_power_scaling_preserves_dimensionless_margin() -> None:
    base = derive_mmc_parameters(parse_parametric_request(valid_request()))
    scaled = derive_mmc_parameters(
        parse_parametric_request(valid_request(dc_voltage_kv=1280.0, active_power_mw=2000.0))
    )
    assert scaled.common["dc_current_ka"] == pytest.approx(base.common["dc_current_ka"])
    assert scaled.common["station_p_grid_impedance_ohm"] == pytest.approx(
        2.0 * base.common["station_p_grid_impedance_ohm"]
    )


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
