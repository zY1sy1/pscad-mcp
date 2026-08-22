from pscad_mcp.hvdc.builders.lcc.assets import (
    load_parametric_blueprint,
    load_parametric_catalog,
    load_parametric_provenance,
)


def test_parametric_blueprints_have_distinct_topology_contracts():
    mono = load_parametric_blueprint("lcc_monopole_parametric_v1")
    bipole = load_parametric_blueprint("lcc_bipole_parametric_v1")
    assert mono["topology"] == "lcc" and mono["poles"] == 1
    assert bipole["topology"] == "lcc" and bipole["poles"] == 2
    assert {"positive_pole", "negative_pole", "neutral_bus"} <= set(bipole["required_assets"])


def test_parametric_catalog_is_versioned():
    catalog = load_parametric_catalog()
    assert catalog["identity"] == "lcc_parametric_catalog_v1"
    assert catalog["pscad_version"] == "4.6.2"


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
