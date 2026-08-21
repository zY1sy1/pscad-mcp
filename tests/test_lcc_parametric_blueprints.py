from pscad_mcp.hvdc.builders.lcc.assets import load_parametric_blueprint, load_parametric_catalog


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
