from pscad_mcp.hvdc.metrics import calculate_metrics
from pscad_mcp.hvdc.service import HvdcDomainService
import asyncio


def test_metrics_calculate_extrema_rms_and_dc_power():
    samples = {
        "time": [0.0, 0.1, 0.2, 0.3],
        "channels": {
            "dc_voltage": [100.0, 110.0, 90.0, 100.0],
            "dc_current": [2.0, 3.0, 1.0, 2.0],
        },
    }
    result = calculate_metrics(samples, ["dc_voltage_peak", "dc_current_rms", "dc_power"])
    by_name = {item["name"]: item for item in result["metrics"]}
    assert by_name["dc_voltage_peak"]["value"] == 110.0
    assert round(by_name["dc_current_rms"]["value"], 6) == round((18 / 4) ** 0.5, 6)
    assert by_name["dc_power"]["value"] == 330.0
    assert result["verdict"] == "PASS"


def test_metrics_fail_closed_for_missing_channels():
    result = calculate_metrics({"time": [0.0, 0.1], "channels": {"dc_voltage": [1.0, 2.0]}}, ["dc_power", "dc_current_peak"])
    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert all(item["status"] == "missing" for item in result["metrics"])


def test_trip_delay_uses_ordered_crossings():
    samples = {"time": [0.0, 1.0, 1.05, 2.0], "channels": {"breaker_command": [0, 0, 1, 1], "breaker_status": [0, 0, 0, 1]}}
    result = calculate_metrics(samples, ["trip_delay_s"])
    assert result["metrics"][0]["value"] == 0.95


def test_service_compares_stored_scenario_metrics():
    service = HvdcDomainService()
    service._scenarios["a"] = {"scenario_id": "a", "samples": {"time": [0, 1], "channels": {"dc_voltage": [100, 110]}}}
    service._scenarios["b"] = {"scenario_id": "b", "samples": {"time": [0, 1], "channels": {"dc_voltage": [100, 120]}}}
    asyncio.run(service.analyze_results("a", ["dc_voltage_peak"]))
    asyncio.run(service.analyze_results("b", ["dc_voltage_peak"]))
    result = asyncio.run(service.compare_scenarios(["a", "b"], ["dc_voltage_peak"]))
    assert result["comparisons"][0]["delta"] == 10.0


def test_step_response_metrics_are_bounded_and_deterministic():
    samples = {"time": [0, 1, 2, 3, 4], "channels": {"dc_current": [0, 2, 1.2, 1.01, 1.0]}}
    result = calculate_metrics(samples, ["dc_current_overshoot", "dc_current_undershoot", "dc_current_settling_time_s"])
    by_name = {item["name"]: item for item in result["metrics"]}
    assert by_name["dc_current_overshoot"]["value"] == 1.0
    assert by_name["dc_current_undershoot"]["value"] == 0.0
    assert by_name["dc_current_settling_time_s"]["value"] == 4.0


def test_pole_imbalance_and_sequence_metrics_require_ordered_channels():
    samples = {"time": [0, 1, 2], "channels": {"dc_voltage_positive": [500, 490, 495], "dc_voltage_negative": [-500, -480, -495], "breaker_command": [0, 1, 1], "breaker_status": [0, 0, 1], "protection_trip": [0, 0, 1]}}
    result = calculate_metrics(samples, ["voltage_imbalance", "breaker_sequence"])
    by_name = {item["name"]: item for item in result["metrics"]}
    assert by_name["voltage_imbalance"]["value"] == 10.0
    assert by_name["breaker_sequence"]["status"] == "observed"
