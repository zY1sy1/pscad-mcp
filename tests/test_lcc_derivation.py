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
        return_path_assets=("neutral_bus", "earth_return"),
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
    assert parameters["dc_power_mw"].asset == "lcc_parametric_provenance_v1:dimensional_identity"
    assert parameters["smoothing_reactor_mh"].source == "user"
    assert parameters["smoothing_reactor_mh"].units == "mH"
    assert parameters["smoothing_reactor_mh"].asset == "lcc_parametric_provenance_v1:positive_finite"
    assert parameters["overlap_angle_deg"].source == "default"
    assert parameters["max_feasible_inverter_firing_angle_deg"].value == pytest.approx(45.0)
    assert parameters["max_feasible_inverter_firing_angle_deg"].formula == (
        "min(max_firing_angle_deg, 180 - min_extinction_angle_deg - overlap_angle_deg)"
    )
    assert parameters["max_feasible_inverter_firing_angle_deg"].constraints == (
        "5.0 <= feasible firing angle <= 45.0 deg",
    )
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


def test_power_identity_is_catalog_driven():
    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(
            request(ratings=LccRatings(1000.0, 500.0, 2.4, 500.0, 50.0, 3.0, 2.5))
        )
    assert raised.value.code == "LCC_RATING_INCONSISTENT"


def test_scr_and_escr_do_not_gain_unreviewed_thresholds_or_ordering():
    report = derive_lcc_parameters(
        request(ratings=LccRatings(1200.0, 500.0, 2.4, 500.0, 50.0, 0.5, 3.5))
    )
    parameters = _parameters(report)
    assert parameters["scr"].value == pytest.approx(0.5)
    assert parameters["escr"].value == pytest.approx(3.5)


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
        ({**COMPLETE_ENGINEERING_VALUES, "smoothing_reactor_mh": -1.0}, "parameter"),
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
        {**COMPLETE_ENGINEERING_VALUES, "overlap_angle_deg": 180.0},
        {**COMPLETE_ENGINEERING_VALUES, "min_firing_angle_deg": 45.0, "max_firing_angle_deg": 45.0},
        {**COMPLETE_ENGINEERING_VALUES, "overlap_angle_deg": 179.0, "min_extinction_angle_deg": 179.0},
    ],
)
def test_impossible_catalog_angle_relationships_fail_closed(overrides):
    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(request(engineering_overrides=overrides))
    assert raised.value.code == "LCC_PARAMETER_DERIVATION_FAILED"
    assert raised.value.details["relationship"] in {
        "angle_domain_deg",
        "firing_angle_interval",
        "inverter_commutation_interval",
    }


def test_large_positive_values_and_nonstandard_angle_sum_are_not_rejected_by_invented_limits():
    overrides = {
        **COMPLETE_ENGINEERING_VALUES,
        "smoothing_reactor_mh": 5000.0,
        "filter_capacitance_uf": 5000.0,
        "overlap_angle_deg": 80.0,
        "min_extinction_angle_deg": 80.0,
        "max_firing_angle_deg": 170.0,
    }
    report = derive_lcc_parameters(request(engineering_overrides=overrides))
    assert report.feasible is True


def test_inverter_firing_feasibility_uses_nonempty_interval_not_unique_alpha():
    boundary = {
        **COMPLETE_ENGINEERING_VALUES,
        "min_firing_angle_deg": 142.0,
        "max_firing_angle_deg": 170.0,
    }
    parameter = _parameters(
        derive_lcc_parameters(request(engineering_overrides=boundary))
    )["max_feasible_inverter_firing_angle_deg"]
    assert parameter.value == pytest.approx(142.0)
    assert parameter.constraints == ("142.0 <= feasible firing angle <= 142.0 deg",)

    infeasible = {**boundary, "min_firing_angle_deg": 142.0001}
    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(request(engineering_overrides=infeasible))
    assert raised.value.code == "LCC_PARAMETER_DERIVATION_FAILED"
    assert raised.value.details["relationship"] == "inverter_commutation_interval"


def test_bipolar_modes_do_not_substitute_for_explicit_return_asset_evidence():
    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(request(return_path_assets=()))
    assert raised.value.code == "LCC_PARAMETER_DERIVATION_FAILED"
    assert raised.value.details["missing_return_assets"] == ["earth_return", "neutral_bus"]


def test_return_asset_evidence_rejects_catalog_undeclared_names():
    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(
            request(return_path_assets=("neutral_bus", "earth_return", "looks_like_a_return"))
        )
    assert raised.value.code == "LCC_PARAMETER_DERIVATION_FAILED"
    assert raised.value.details["unknown_return_assets"] == ["looks_like_a_return"]


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


@pytest.mark.parametrize(
    ("catalog_change", "missing"),
    [
        (lambda catalog: catalog["rating_parameters"].pop("rated_power_mw"), ["rated_power_mw"]),
        (lambda catalog: catalog["rating_parameters"].pop("dc_voltage_kv"), ["dc_voltage_kv"]),
        (lambda catalog: catalog["rating_parameters"].pop("dc_current_ka"), ["dc_current_ka"]),
        (
            lambda catalog: catalog["derived_parameters"]["dc_power_mw"].update(
                {"dependencies": ["dc_voltage_kv"]}
            ),
            ["dc_current_ka"],
        ),
    ],
)
def test_catalog_missing_power_inputs_or_formula_dependencies_fails_structured(catalog_change, missing):
    catalog = copy.deepcopy(load_parametric_catalog())
    catalog_change(catalog)
    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(request(), catalog)
    assert raised.value.code == "LCC_PARAMETER_DERIVATION_FAILED"
    assert raised.value.details["missing_catalog_dependencies"] == missing


@pytest.mark.parametrize(
    "tamper",
    [
        lambda catalog: catalog["engineering_parameters"]["smoothing_reactor_mh"]["constraints"][0].update({"value": 1.0}),
        lambda catalog: catalog["engineering_parameters"]["overlap_angle_deg"]["constraints"][0].update({"maximum": 179.0}),
        lambda catalog: catalog["engineering_parameters"]["smoothing_reactor_mh"]["unit_multipliers"].update({"H": 999.0}),
        lambda catalog: catalog["engineering_parameters"]["filter_capacitance_uf"]["unit_multipliers"].update({"F": 999.0}),
        lambda catalog: catalog["engineering_parameters"]["overlap_angle_deg"]["unit_multipliers"].update({"rad": 57.0}),
        lambda catalog: catalog["feasibility_relationships"]["firing_angle_interval"].update({"left": "overlap_angle_deg"}),
    ],
)
def test_catalog_contract_must_exactly_match_machine_provenance(tamper):
    catalog = copy.deepcopy(load_parametric_catalog())
    tamper(catalog)

    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(request(), catalog)

    assert raised.value.code == "LCC_PARAMETER_DERIVATION_FAILED"
    assert "asset" in raised.value.details


def test_inverter_commutation_identity_must_match_machine_provenance():
    catalog = copy.deepcopy(load_parametric_catalog())
    catalog["feasibility_relationships"]["inverter_commutation_interval"] = {
        "operator": "nonempty_upper_bounded_interval",
        "output": "max_feasible_inverter_firing_angle_deg",
        "units": "deg",
        "formula": "min(max_firing_angle_deg, 179 - min_extinction_angle_deg - overlap_angle_deg)",
        "constant_deg": 179.0,
        "subtract": ["min_extinction_angle_deg", "overlap_angle_deg"],
        "minimum": "min_firing_angle_deg",
        "user_maximum": "max_firing_angle_deg",
        "asset": "lcc_parametric_provenance_v1:inverter_commutation_identity",
    }

    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(request(), catalog)

    assert raised.value.code == "LCC_PARAMETER_DERIVATION_FAILED"
    assert raised.value.details["relationship"] == "inverter_commutation_interval"


@pytest.mark.parametrize(
    "tamper",
    [
        lambda catalog: catalog["rating_parameters"].pop("scr"),
        lambda catalog: catalog["rating_parameters"]["frequency_hz"].update({"required": False}),
        lambda catalog: catalog["rating_parameters"]["escr"].update({"required": True}),
    ],
)
def test_required_rating_set_and_flags_are_bound_to_machine_provenance(tamper):
    catalog = copy.deepcopy(load_parametric_catalog())
    tamper(catalog)

    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(request(), catalog)

    assert raised.value.code == "LCC_PARAMETER_DERIVATION_FAILED"
    assert raised.value.details["asset"] == "lcc_parametric_provenance_v1:rating_contract"


@pytest.mark.parametrize(
    "tamper",
    [
        lambda catalog: catalog["return_asset_requirements"].pop("bipolar"),
        lambda catalog: catalog["return_asset_requirements"]["bipolar"]["required"].remove("neutral_bus"),
        lambda catalog: catalog["return_asset_requirements"]["bipolar"]["mode_requirements"].pop("monopolar_earth_return"),
        lambda catalog: catalog["return_asset_requirements"]["bipolar"]["mode_requirements"].update({"metallic_return": ["earth_return"]}),
    ],
)
def test_bipole_return_requirements_are_bound_to_machine_provenance(tamper):
    catalog = copy.deepcopy(load_parametric_catalog())
    tamper(catalog)

    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(request(), catalog)

    assert raised.value.code == "LCC_PARAMETER_DERIVATION_FAILED"
    assert raised.value.details["asset"] == "lcc_parametric_provenance_v1:bipole_return_contract"


@pytest.mark.parametrize(
    "relationship",
    ["firing_angle_interval", "inverter_commutation_interval"],
)
def test_required_relationship_inventory_cannot_be_removed_from_catalog(relationship):
    catalog = copy.deepcopy(load_parametric_catalog())
    catalog["feasibility_relationships"].pop(relationship)

    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(request(), catalog)

    assert raised.value.code == "LCC_PARAMETER_DERIVATION_FAILED"
    assert raised.value.details["missing_relationships"] == [relationship]


def test_required_return_topology_cannot_be_removed_from_both_catalog_bindings():
    catalog = copy.deepcopy(load_parametric_catalog())
    catalog["return_contract_assets"].pop("bipolar")
    catalog["return_asset_requirements"].pop("bipolar")

    with pytest.raises(BackendError) as raised:
        derive_lcc_parameters(request(), catalog)

    assert raised.value.code == "LCC_PARAMETER_DERIVATION_FAILED"
    assert raised.value.details["missing_return_topologies"] == ["bipolar"]
