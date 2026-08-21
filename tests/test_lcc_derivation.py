import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.derivation import derive_lcc_parameters
from pscad_mcp.hvdc.builders.lcc.parametric_models import LccRatings, ParametricLccRequest


def request(**overrides):
    values = dict(
        topology="bipolar",
        ratings=LccRatings(1200.0, 500.0, 2.4, 500.0, 50.0, 3.0),
        engineering_overrides={"smoothing_reactor_mh": 120.0},
        operation_modes=("bipolar_run", "monopole_earth_return"),
    )
    values.update(overrides)
    return ParametricLccRequest(**values)


def test_derives_power_and_preserves_user_override():
    report = derive_lcc_parameters(request())
    parameters = {item.name: item for item in report.parameters}
    assert parameters["dc_power_mw"].value == pytest.approx(1200.0)
    assert parameters["dc_power_mw"].source == "derived"
    assert parameters["smoothing_reactor_mh"].source == "user"
    assert report.feasible is True


@pytest.mark.parametrize("change, code", [
    ({"ratings": LccRatings(1000.0, 500.0, 2.4, 500.0, 50.0, 3.0)}, "LCC_RATING_INCONSISTENT"),
    ({"engineering_overrides": {"unknown": 1.0}}, "LCC_PARAMETER_DERIVATION_FAILED"),
])
def test_derivation_fails_closed(change, code):
    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(request(**change))
    assert raised.value.code == code
