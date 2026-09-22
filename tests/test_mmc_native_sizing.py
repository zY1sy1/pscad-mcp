import pytest

from pscad_mcp.hvdc.builders.mmc.derivation import derive_mmc_parameters
from pscad_mcp.hvdc.builders.mmc.native_sizing import periodic_native_envelope
from tests.mmc_parametric_fakes import valid_request
from tests.test_mmc_derivation import native_cable_profile


def test_periodic_integral_converges_and_respects_three_phase_symmetry():
    request = valid_request(model_fidelity="average_value", dc_link={"kind": "cable", "length_km": 100.0})
    parameters = derive_mmc_parameters(request, avm_cable_profile=native_cable_profile()).candidates[0].parameters
    coarse = periodic_native_envelope(parameters, points=1440)
    fine = periodic_native_envelope(parameters, points=5760)
    assert coarse["required_stored_energy_mj"] == pytest.approx(fine["required_stored_energy_mj"], rel=2e-5)
    assert coarse["minimum_insertion_margin"] == pytest.approx(fine["minimum_insertion_margin"], abs=1e-5)
    for operating in fine["operating_points"]:
        for side in (0, 1):
            for phase in (1, 2):
                assert operating["arm_energy_swings"][side] == pytest.approx(operating["arm_energy_swings"][phase * 2 + side], abs=1e-12)


def test_voltage_and_impedance_scaling_preserves_energy_swing():
    request = valid_request(model_fidelity="average_value", dc_link={"kind": "cable", "length_km": 100.0})
    parameters = derive_mmc_parameters(request, avm_cable_profile=native_cable_profile()).candidates[0].parameters
    scaled = dict(parameters)
    for name in ("rated_dc_voltage_kv", "station_p_ac_voltage_kv", "station_vdc_ac_voltage_kv"):
        scaled[name] *= 2
    for name in ("arm_resistance_ohm", "arm_inductance_h", "line_resistance_ohm", "neutral_inductance_h", "neutral_resistance_ohm", "station_p_grid_r_ohm", "station_p_grid_x_ohm", "station_vdc_grid_r_ohm", "station_vdc_grid_x_ohm"):
        scaled[name] *= 4
    a, b = map(periodic_native_envelope, (parameters, scaled))
    assert a["required_stored_energy_mj"] == pytest.approx(b["required_stored_energy_mj"], rel=1e-12)
    assert a["minimum_insertion_margin"] == pytest.approx(b["minimum_insertion_margin"], abs=1e-12)
    for pa, pb in zip(a["operating_points"], b["operating_points"]):
        assert pb["valve_current_peak_ka"] == pytest.approx(pa["valve_current_peak_ka"] / 2)
