from pscad_mcp.hvdc.profiles import load_profile

def test_lcc_earth_return_profile_is_standalone_and_scoped():
    profile = load_profile("lcc_bipolar_earth_return_v1")
    assert profile["profile_version"] == 2
    assert profile.get("extends") is None
    assert profile["topology_constraints"] == {"family": "lcc", "polarity": "bipolar", "return_mode": "earth_return"}
    assert {"positive_pole_voltage", "negative_pole_voltage", "positive_pole_current", "negative_pole_current", "earth_return_current", "earth_return_switch_status"} <= set(profile["metric_roles"]) | {item["canonical"] for item in profile["mappings"]}
