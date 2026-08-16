from pscad_mcp.hvdc.metrics import calculate_metrics
from pscad_mcp.hvdc.service import HvdcDomainService
import asyncio
import pytest


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


def test_service_resolves_list_psout_channels_from_profile_after_output_discovery():
    class OutputBackend:
        def __init__(self):
            self.read_files = []

        async def read_output_file(self, file_path, summary_only=False):
            self.read_files.append(file_path)
            assert summary_only is False
            return {
                "channels": [
                    {"path": "Main/Vdc", "values": [500, 510, 505], "domain": [0.0, 0.1, 0.2]},
                    {"name": "IDC", "values": [1.0, 1.2, 1.1], "domain": [0.0, 0.1, 0.2]},
                ]
            }

    backend = OutputBackend()
    service = HvdcDomainService(backend)
    service._scenarios["resolved"] = {
        "scenario_id": "resolved",
        "profile": "lcc_bipolar_generic",
        "output_files": ["discovered.psout"],
        "resolved_channels": [],
        "warnings": [],
    }

    result = asyncio.run(
        service.analyze_results("resolved", ["dc_voltage_peak", "dc_current_peak", "dc_power"])
    )

    assert backend.read_files == ["discovered.psout"]
    assert [item["canonical"] for item in result["resolved_channels"]] == [
        "dc_current",
        "dc_voltage",
    ]
    assert {item["canonical"]: item["source"] for item in result["resolved_channels"]} == {
        "dc_current": "IDC",
        "dc_voltage": "Main/Vdc",
    }
    assert {item["name"]: item["value"] for item in result["metrics"]} == {
        "dc_voltage_peak": 510.0,
        "dc_current_peak": 1.2,
        "dc_power": 612.0,
    }
    assert result["verdict"] == "PASS"


@pytest.mark.parametrize(
    "samples",
    [
        {"time": [0.0, 0.1, 0.2], "channels": {"dc_voltage": [1.0, 2.0]}},
        {"time": [0.0, 0.1], "channels": {"dc_voltage": [1.0, "bad"]}},
        {"time": [0.0, 0.1, 0.1], "channels": {"dc_voltage": [1.0, 2.0, 3.0]}},
    ],
)
def test_sample_alignment_and_numeric_time_validation_fail_closed(samples):
    result = calculate_metrics(samples, ["dc_voltage_peak"])
    metric = result["metrics"][0]
    assert metric["value"] is None
    assert metric["status"] == "invalid"
    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["warnings"]


def test_trip_delay_fails_closed_when_status_crosses_before_command():
    samples = {
        "time": [0.0, 0.1, 0.2, 0.3],
        "channels": {
            "breaker_command": [0, 0, 1, 1],
            "breaker_status": [0, 1, 1, 1],
        },
    }
    result = calculate_metrics(samples, ["trip_delay_s"])
    metric = result["metrics"][0]
    assert metric["value"] is None
    assert metric["status"] == "invalid"
    assert result["verdict"] == "INCOMPLETE_ANALYSIS"


def test_recovery_time_requires_explicit_baseline_and_does_not_reuse_settling():
    samples = {
        "time": [0, 1, 2, 3, 4],
        "channels": {"dc_current": [1.0, 2.0, 1.2, 1.01, 1.0]},
    }
    result = calculate_metrics(
        samples,
        ["dc_current_settling_time_s", "dc_current_recovery_time_s"],
    )
    by_name = {item["name"]: item for item in result["metrics"]}
    assert by_name["dc_current_settling_time_s"]["value"] == 4.0
    assert by_name["dc_current_recovery_time_s"]["value"] is None
    assert by_name["dc_current_recovery_time_s"]["status"] == "invalid"
    assert result["verdict"] == "INCOMPLETE_ANALYSIS"


def test_empty_or_unaligned_channels_never_fabricate_zero_metrics():
    samples = {
        "time": [0.0, 0.1],
        "channels": {
            "dc_voltage": [],
            "dc_current": [1.0, 2.0],
            "dc_voltage_positive": [],
            "dc_voltage_negative": [-1.0, -1.0],
        },
    }
    result = calculate_metrics(samples, ["dc_voltage_mean", "dc_power", "voltage_imbalance"])
    assert all(item["value"] is None for item in result["metrics"])
    assert all(item["status"] in {"missing", "invalid"} for item in result["metrics"])
    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
