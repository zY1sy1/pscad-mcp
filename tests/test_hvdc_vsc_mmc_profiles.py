from pscad_mcp.hvdc.metrics import calculate_metrics
from pscad_mcp.hvdc.profiles import load_profile


def test_vsc_profile_exposes_explicit_measurement_selectors_and_roles():
    profile = load_profile("vsc_2level_generic")
    assert profile["profile_version"] == 2
    assert {
        "dc_voltage",
        "dc_current",
        "active_power",
        "reactive_power",
        "pll_frequency",
        "dq_current",
        "dq_voltage",
    } <= set(profile["metric_roles"])
    assert profile["command_bindings"] == []


def test_mmc_profile_exposes_arm_submodule_and_circulating_current_metrics():
    profile = load_profile("mmc_bipolar_generic")
    assert profile["profile_version"] == 2
    assert {"arm_current", "submodule_capacitor_voltage", "circulating_current"} <= set(profile["metric_roles"])
    assert profile["command_bindings"] == []


def test_vsc_power_and_dq_metrics_are_unit_aware():
    profile = load_profile("vsc_2level_generic")
    samples = {
        "time": [0.0, 1.0],
        "channels": {
            "dc_voltage": [500.0, 510.0],
            "dc_current": [1.0, 1.2],
            "active_power": [100.0, 120.0],
            "reactive_power": [20.0, 30.0],
            "pll_frequency": [50.0, 50.1],
            "dq_current": [1.0, 1.1],
            "dq_voltage": [100.0, 101.0],
        },
    }
    result = calculate_metrics(samples, ["active_power_peak", "reactive_power_peak", "pll_frequency_mean"], profile=profile)
    by_name = {item["name"]: item for item in result["metrics"]}
    assert by_name["active_power_peak"]["units"] == "MW"
    assert by_name["reactive_power_peak"]["units"] == "MVAr"
    assert by_name["pll_frequency_mean"]["units"] == "Hz"
    assert result["verdict"] == "PASS"


def test_mmc_circulating_current_rms_is_supported():
    profile = load_profile("mmc_bipolar_generic")
    result = calculate_metrics(
        {"time": [0.0, 1.0], "channels": {"circulating_current": [1.0, 3.0]}},
        ["circulating_current_rms"],
        profile=profile,
    )
    metric = result["metrics"][0]
    assert metric["value"] == (5.0) ** 0.5
    assert metric["units"] == "kA"
