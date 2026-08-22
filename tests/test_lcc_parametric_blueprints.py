import copy
import hashlib
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.assets import (
    canonical_json,
    load_parametric_blueprint,
    load_parametric_catalog,
    load_parametric_provenance,
    validate_parametric_blueprint_asset,
    validate_parametric_catalog_asset,
)
from pscad_mcp.hvdc.builders.lcc.parametric_models import (
    DerivedParameter,
    DerivedParameterReport,
    LccRatings,
    ParametricLccRequest,
)
from pscad_mcp.hvdc.builders.lcc.derivation import derive_lcc_parameters
from pscad_mcp.hvdc.builders.lcc.planner import create_parametric_topology_plan
from pscad_mcp.hvdc.builders.lcc.template_audit import audit_lcc_template
from pscad_mcp.hvdc.builders.lcc.validator import validate_parametric_topology_contract


FIXTURES = Path(__file__).parent / "fixtures" / "lcc_parametric"


def test_parametric_blueprints_have_distinct_topology_contracts():
    mono = load_parametric_blueprint("lcc_monopole_parametric_v1")
    bipole = load_parametric_blueprint("lcc_bipole_parametric_v1")
    assert mono["topology"] == "lcc" and mono["poles"] == 1
    assert bipole["topology"] == "lcc" and bipole["poles"] == 2
    assert {"positive_pole", "negative_pole", "neutral_bus"} <= set(bipole["required_assets"])
    assert mono["contract_kind"] == bipole["contract_kind"] == "template_role_topology"
    assert mono["components"] and mono["nets"] and mono["outputs"]
    assert bipole["components"] and bipole["nets"] and bipole["outputs"]


def test_bipole_declares_exact_real_template_roles_returns_and_baseline_outputs():
    bipole = load_parametric_blueprint("lcc_bipole_parametric_v1")

    assert set(bipole["template_roles"]) == {
        "rectifier_positive_pole",
        "rectifier_negative_pole",
        "inverter_positive_pole",
        "inverter_negative_pole",
        "earth_electrode",
    }
    assert {item["logical_id"] for item in bipole["components"]} == {
        *bipole["template_roles"],
        "neutral_bus",
        "metallic_return_terminal",
    }
    nets = {item["logical_id"]: item for item in bipole["nets"]}
    assert {"dc_positive", "dc_negative", "neutral_bus", "earth_return", "metallic_return"} == set(nets)
    assert nets["dc_positive"]["endpoints"] == [
        {"role": "rectifier_positive_pole", "port": "DCP1"},
        {"role": "inverter_positive_pole", "port": "DCP1"},
    ]
    assert nets["earth_return"]["endpoints"] == [
        {"role": "neutral_bus", "port": "earth"},
        {"role": "earth_electrode", "port": "A"},
    ]
    assert nets["metallic_return"]["endpoints"] == [
        {"role": "neutral_bus", "port": "metallic"},
        {"role": "metallic_return_terminal", "port": "remote"},
    ]
    assert {item["name"] for item in bipole["outputs"]} == {
        "VDCRp1", "VDCRp2", "VDCIp1", "VDCIp2",
        "CMRp1", "CMRp2", "CMIp1", "CMIp2",
        "Ielectrode", "PR", "PI",
        "AORp1", "AORp2", "AOIp1", "AOIp2",
    }


def test_monopole_has_its_own_roles_nets_and_outputs():
    mono = load_parametric_blueprint("lcc_monopole_parametric_v1")

    assert set(mono["template_roles"]) == {
        "rectifier_valve_group", "inverter_valve_group", "earth_electrode"
    }
    assert {item["logical_id"] for item in mono["nets"]} == {
        "dc_pole", "earth_return", "metallic_return"
    }
    assert {item["name"] for item in mono["outputs"]} == {
        "VDCRp1", "VDCIp1", "CMRp1", "CMIp1", "Ielectrode",
        "PR", "PI", "AORp1", "AOIp1",
    }


def test_parametric_catalog_is_versioned():
    catalog = load_parametric_catalog()
    assert catalog["identity"] == "lcc_parametric_catalog_v1"
    assert catalog["pscad_version"] == "4.6.2"
    for name in ("lcc_monopole_parametric_v1", "lcc_bipole_parametric_v1"):
        blueprint = load_parametric_blueprint(name)
        assert hashlib.sha256(canonical_json(blueprint)).hexdigest() == catalog["blueprint_hashes"][name]


def test_parametric_blueprint_loader_rejects_schema_drift_and_missing_structure():
    catalog = load_parametric_catalog()
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")

    for mutate in (
        lambda value: value.update({"unexpected": True}),
        lambda value: value.update({"outputs": []}),
        lambda value: value["components"].pop(),
        lambda value: value["nets"].pop(),
    ):
        candidate = copy.deepcopy(blueprint)
        mutate(candidate)
        with pytest.raises(BackendError) as raised:
            validate_parametric_blueprint_asset(candidate, "lcc_bipole_parametric_v1", catalog)
        assert raised.value.code == "LCC_BLUEPRINT_INVALID"


def test_parametric_catalog_loader_rejects_undeclared_roles_and_contract_fields():
    catalog = load_parametric_catalog()
    bad_role = copy.deepcopy(catalog)
    bad_role["logical_parameter_bindings"]["rated_power_mw"]["roles_by_topology"]["bipolar"] = ["ghost_pole"]
    with pytest.raises(BackendError) as raised:
        validate_parametric_catalog_asset(bad_role)
    assert raised.value.code == "LCC_ASSET_MISMATCH"

    extra_field = copy.deepcopy(catalog)
    extra_field["topology_contracts"]["bipolar"]["unexpected"] = True
    with pytest.raises(BackendError) as raised:
        validate_parametric_catalog_asset(extra_field)
    assert raised.value.code == "LCC_ASSET_MISMATCH"


def test_parametric_provenance_distinguishes_invariants_from_legacy_defaults():
    catalog = load_parametric_catalog()
    provenance = load_parametric_provenance()
    entries = provenance["entries"]

    assert catalog["provenance_identity"] == provenance["identity"]
    assert entries["positive_finite"]["classification"] == "physical_invariant"
    assert entries["angle_domain_deg"]["classification"] == "basic_domain"
    assert entries["legacy_catalog_defaults"]["classification"] == "legacy_catalog_default"
    assert entries["floating_point_comparison"]["classification"] == "implementation_policy"
    assert "do not establish allowable ranges" in entries["legacy_catalog_defaults"]["limitation"]


def test_return_asset_allowlist_matches_packaged_bipole_contract():
    catalog = load_parametric_catalog()
    provenance = load_parametric_provenance()
    bipole = load_parametric_blueprint("lcc_bipole_parametric_v1")
    allowed = catalog["return_asset_requirements"]["bipolar"]["allowed"]

    assert allowed == provenance["entries"]["bipole_return_contract"]["machine_contract"]["allowed"]
    assert set(allowed) <= set(bipole["required_assets"])


def _derived(value=1000.0):
    return DerivedParameterReport(
        parameters=(
            DerivedParameter(
                name="rated_power_mw", value=value, source="user",
                formula="request.ratings.rated_power_mw", units="MW",
                asset="lcc_parametric_provenance_v1:positive_finite",
            ),
            DerivedParameter(
                name="min_firing_angle_deg", value=15.0, source="user",
                formula="user value in catalog units (deg)", units="deg",
                asset="lcc_parametric_provenance_v1:angle_domain_deg",
            ),
        )
    )


def test_parametric_topology_planner_is_deterministic_explicit_and_fail_closed():
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")
    first = create_parametric_topology_plan(blueprint, _derived())
    second = create_parametric_topology_plan(blueprint, _derived())

    assert first == second
    assert first["executable"] is False
    assert first["unresolved_bindings"]
    assert {item["parameter"] for item in first["unresolved_bindings"]} == {
        "rated_power_mw", "min_firing_angle_deg"
    }
    assert all(item["reason"] == "template_parameter_binding_unreviewed" for item in first["unresolved_bindings"])
    assert first["role_parameters"]["rectifier_positive_pole"]["rated_power_mw"] == {
        "value": 1000.0,
        "units": "MW",
        "logical_parameter": "rated_power_mw",
        "template_parameter": None,
    }
    assert first["plan_hash"] != create_parametric_topology_plan(blueprint, _derived(1200.0))["plan_hash"]


def test_parametric_topology_planner_maps_the_complete_derived_report_without_authorizing_writes():
    request = ParametricLccRequest(
        topology="bipolar",
        ratings=LccRatings(1200.0, 500.0, 2.4, 500.0, 50.0, 3.0, 2.5),
        engineering_overrides={
            "smoothing_reactor_mh": 120.0,
            "filter_capacitance_uf": 60.0,
            "min_firing_angle_deg": 5.0,
            "max_firing_angle_deg": 45.0,
        },
        return_path_assets=("neutral_bus",),
    )
    report = derive_lcc_parameters(request)
    plan = create_parametric_topology_plan(
        load_parametric_blueprint("lcc_bipole_parametric_v1"), report
    )

    assert plan["executable"] is False
    assert {item["parameter"] for item in plan["unresolved_bindings"]} == {
        item.name for item in report.parameters
    }


def _audit_roles(blueprint):
    components = {
        item.get("template_role"): item
        for item in blueprint["components"]
        if item["kind"] == "template_role"
    }
    return {
        role: {
            "definition": (
                "master:ground"
                if role == "earth_electrode"
                else "Fixture:" + ("RectPole" if role.startswith("rectifier") else "InverterPole")
            ),
            **(
                {"discriminator": components[role]["discriminator"]}
                if components[role]["discriminator"] is not None
                else {}
            ),
            "validated_contract": (
                "lcc_parametric_catalog_v1:earth_electrode"
                if role == "earth_electrode"
                else "lcc_parametric_catalog_v1:" + ("RectPole" if role.startswith("rectifier") else "InverterPole")
            ),
        }
        for role in blueprint["template_roles"]
    }


def test_parametric_validator_accepts_exact_roles_and_topology_evidence():
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")
    result = validate_parametric_topology_contract(blueprint, _audit_roles(blueprint))
    assert result == {
        "valid": True,
        "blueprint": "lcc_bipole_parametric_v1",
        "template_roles": sorted(blueprint["template_roles"]),
        "nets": sorted(item["logical_id"] for item in blueprint["nets"]),
        "outputs": sorted(item["name"] for item in blueprint["outputs"]),
    }


@pytest.mark.parametrize("field,item", [
    ("components", "neutral_bus"),
    ("nets", "earth_return"),
    ("nets", "metallic_return"),
    ("outputs", "VDCRp2"),
])
def test_parametric_validator_rejects_missing_bipole_evidence(field, item):
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")
    candidate = copy.deepcopy(blueprint)
    key = "name" if field == "outputs" else "logical_id"
    candidate[field] = [record for record in candidate[field] if record[key] != item]

    with pytest.raises(BackendError) as raised:
        validate_parametric_topology_contract(candidate, _audit_roles(blueprint))
    assert raised.value.code == "LCC_BLUEPRINT_INVALID"


def test_parametric_validator_rejects_extra_template_role_or_net():
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")
    roles = _audit_roles(blueprint)
    roles["extra_pole"] = {"definition": "Fixture:RectPole"}
    with pytest.raises(BackendError) as raised:
        validate_parametric_topology_contract(blueprint, roles)
    assert raised.value.code == "LCC_PROJECT_INVALID"

    candidate = copy.deepcopy(blueprint)
    candidate["nets"].append(copy.deepcopy(candidate["nets"][0]) | {"logical_id": "extra_dc"})
    with pytest.raises(BackendError) as raised:
        validate_parametric_topology_contract(candidate, _audit_roles(blueprint))
    assert raised.value.code == "LCC_BLUEPRINT_INVALID"


def test_parametric_validator_requires_exact_audited_definition_not_just_claimed_contract():
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")
    roles = _audit_roles(blueprint)
    roles["rectifier_positive_pole"]["definition"] = "Fixture:WrongPole"

    with pytest.raises(BackendError) as raised:
        validate_parametric_topology_contract(blueprint, roles)
    assert raised.value.code == "LCC_PROJECT_INVALID"


@pytest.mark.parametrize("name,fixture", [
    ("lcc_monopole_parametric_v1", "monopole_template.pscx"),
    ("lcc_bipole_parametric_v1", "bipole_template.pscx"),
])
def test_parametric_validator_accepts_real_read_only_audit_roles(name, fixture):
    blueprint = load_parametric_blueprint(name)
    audit = audit_lcc_template(FIXTURES / fixture)

    assert validate_parametric_topology_contract(blueprint, audit)["valid"] is True
