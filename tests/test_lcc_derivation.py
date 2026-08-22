import copy

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.assets import load_parametric_catalog
from pscad_mcp.hvdc.builders.lcc.derivation import derive_lcc_parameters
from pscad_mcp.hvdc.builders.lcc.parametric_models import LccRatings, ParametricLccRequest


COMPLETE_ENGINEERING_VALUES = {
    "smoothing_reactor_mh": 120.0,
    "filter_capacitance_uf": 60.0,
    "min_firing_angle_deg": 5.0,
    "max_firing_angle_deg": 45.0,
}


def request(**changes):
    values = dict(
        topology="bipolar",
        ratings=LccRatings(1200.0, 500.0, 2.4, 500.0, 50.0, 3.0, 2.5),
        engineering_overrides=COMPLETE_ENGINEERING_VALUES,
        operation_modes=("bipolar_run", "monopolar_earth_return"),
        return_path_assets=("neutral_bus", "earth_electrode"),
    )
    values.update(changes)
    return ParametricLccRequest(**values)


def _parameters(report):
    return {item.name: item for item in report.parameters}


def test_default_catalog_derives_power_and_preserves_catalog_evidence_for_user_override():
    report = derive_lcc_parameters(request())
    parameters = _parameters(report)

    assert parameters["dc_power_mw"].value == pytest.approx(1200.0)
    assert parameters["dc_power_mw"].source == "derived"
    assert parameters["dc_power_mw"].formula == "dc_voltage_kv * dc_current_ka"
    assert parameters["dc_power_mw"].units == "MW"
    assert parameters["dc_power_mw"].asset == "lcc_parametric_catalog_v1:dimensional_identity"
    assert parameters["smoothing_reactor_mh"].source == "user"
    assert parameters["smoothing_reactor_mh"].units == "mH"
    assert parameters["smoothing_reactor_mh"].asset == "lcc_parametric_catalog_v1:engineering_ranges"
    assert parameters["overlap_angle_deg"].source == "default"
    assert report.feasible is True
    assert list(report.diagnostics) == sorted(report.diagnostics)


def test_override_units_are_normalized_only_by_catalog_conversion():
    overrides = dict(COMPLETE_ENGINEERING_VALUES)
    overrides["smoothing_reactor_mh"] = {"value": 0.12, "units": "H"}

    parameter = _parameters(derive_lcc_parameters(request(engineering_overrides=overrides)))[
        "smoothing_reactor_mh"
    ]

    assert parameter.value == pytest.approx(120.0)
    assert parameter.units == "mH"
    assert parameter.formula == "user value * 1000.0 H->mH"
    assert parameter.source == "user"


@pytest.mark.parametrize(
    "ratings, code",
    [
        (LccRatings(1000.0, 500.0, 2.4, 500.0, 50.0, 3.0, 2.5), "LCC_RATING_INCONSISTENT"),
        (LccRatings(1200.0, 500.0, 2.4, 500.0, 50.0, 0.5, 0.4), "LCC_RATING_INVALID"),
        (LccRatings(1200.0, 500.0, 2.4, 500.0, 50.0, 3.0, 3.5), "LCC_RATING_INVALID"),
    ],
)
def test_rating_feasibility_is_catalog_driven(ratings, code):
    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(request(ratings=ratings))
    assert raised.value.code == code


@pytest.mark.parametrize(
    "overrides, missing",
    [
        ({}, ["filter_capacitance_uf", "max_firing_angle_deg", "min_firing_angle_deg", "smoothing_reactor_mh"]),
        ({"smoothing_reactor_mh": 120.0}, ["filter_capacitance_uf", "max_firing_angle_deg", "min_firing_angle_deg"]),
    ],
)
def test_required_values_without_reviewed_defaults_fail_closed(overrides, missing):
    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(request(engineering_overrides=overrides))
    assert raised.value.code == "LCC_PARAMETER_DERIVATION_FAILED"
    assert raised.value.details["missing"] == missing


@pytest.mark.parametrize(
    "overrides, detail_key",
    [
        ({**COMPLETE_ENGINEERING_VALUES, "unknown": 1.0}, "unknown"),
        ({**COMPLETE_ENGINEERING_VALUES, "smoothing_reactor_mh": 5000.0}, "parameter"),
        ({**COMPLETE_ENGINEERING_VALUES, "smoothing_reactor_mh": {"value": 0.12, "units": "kg"}}, "units"),
    ],
)
def test_unsupported_or_out_of_range_overrides_fail_closed(overrides, detail_key):
    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(request(engineering_overrides=overrides))
    assert raised.value.code == "LCC_PARAMETER_DERIVATION_FAILED"
    assert detail_key in raised.value.details


@pytest.mark.parametrize(
    "overrides",
    [
        {**COMPLETE_ENGINEERING_VALUES, "overlap_angle_deg": 50.0, "min_extinction_angle_deg": 40.0},
        {**COMPLETE_ENGINEERING_VALUES, "min_firing_angle_deg": 30.0, "max_firing_angle_deg": 45.0},
    ],
)
def test_impossible_catalog_angle_relationships_fail_closed(overrides):
    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(request(engineering_overrides=overrides))
    assert raised.value.code == "LCC_PARAMETER_DERIVATION_FAILED"
    assert raised.value.details["relationship"] in {
        "commutation_angle_budget",
        "firing_angle_interval",
    }


def test_bipolar_modes_do_not_substitute_for_explicit_return_asset_evidence():
    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(request(return_path_assets=()))
    assert raised.value.code == "LCC_PARAMETER_DERIVATION_FAILED"
    assert raised.value.details["missing_return_assets"] == ["earth_electrode", "neutral_bus"]


def test_derivation_does_not_write_to_filesystem(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    derive_lcc_parameters(request())
    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert after == before


def test_catalog_controls_supported_names_ranges_and_required_values():
    catalog = copy.deepcopy(load_parametric_catalog())
    catalog["engineering_parameters"].pop("filter_capacitance_uf")
    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(request(), catalog)
    assert raised.value.code == "LCC_PARAMETER_DERIVATION_FAILED"
    assert raised.value.details["unknown"] == ["filter_capacitance_uf"]
