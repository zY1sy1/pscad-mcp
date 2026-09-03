from __future__ import annotations

import math

from pscad_mcp.hvdc.builders.lcc.dynamic_evidence import (
    derive_fixed_lcc_dynamic_evidence,
    normalize_exact_channels,
)

from .lcc_dynamic_fakes import dynamic_contract, passing_raw_channels


def _channel(raw: dict, path: str) -> dict:
    return next(item for item in raw["channels"] if item["path"] == path)


def _set_values(raw: dict, path: str, values: list[float]) -> None:
    _channel(raw, path)["values"] = values


def test_dynamic_evidence_derives_every_engineering_check_from_raw_channels():
    result = derive_fixed_lcc_dynamic_evidence(
        passing_raw_channels(), dynamic_contract(), output_step_s=0.00005
    )

    assert result["engineering_verdict"] == "PASS"
    assert set(result["checks"]) == {
        "disturbance",
        "failure_indication",
        "bounded_dc_response",
        "recovery",
    }
    for check in result["checks"].values():
        assert set(check) == {
            "outcome",
            "selectors",
            "units",
            "window_s",
            "sample_count",
            "metrics",
        }
        assert check["outcome"] == "PASS"
        assert check["selectors"]
        assert check["units"]
        assert check["window_s"][1] > check["window_s"][0]
        assert check["sample_count"] > 0
        assert check["metrics"]


def test_missing_required_channel_is_fail():
    raw = passing_raw_channels()
    raw["channels"] = [item for item in raw["channels"] if item["path"] != "Main/IDC"]
    result = derive_fixed_lcc_dynamic_evidence(raw, dynamic_contract())
    assert result["engineering_verdict"] == "FAIL"
    assert result["checks"]["bounded_dc_response"]["outcome"] == "FAIL"


def test_duplicate_exact_selector_is_fail():
    raw = passing_raw_channels()
    raw["channels"].append(dict(_channel(raw, "Main/IDC")))
    result = derive_fixed_lcc_dynamic_evidence(raw, dynamic_contract())
    assert result["engineering_verdict"] == "FAIL"
    assert result["checks"]["bounded_dc_response"]["outcome"] == "FAIL"


def test_gamma_unit_mismatch_is_fail():
    raw = passing_raw_channels()
    _channel(raw, "Main/GAMMA_INV")["units"] = "deg"
    result = derive_fixed_lcc_dynamic_evidence(raw, dynamic_contract())
    assert result["engineering_verdict"] == "FAIL"
    assert result["checks"]["failure_indication"]["outcome"] == "FAIL"


def test_insufficient_time_coverage_is_incomplete_analysis():
    raw = passing_raw_channels(end_s=1.39995)
    result = derive_fixed_lcc_dynamic_evidence(raw, dynamic_contract())
    assert result["engineering_verdict"] == "INCOMPLETE_ANALYSIS"
    assert all(
        check["outcome"] == "INCOMPLETE_ANALYSIS"
        for check in result["checks"].values()
    )


def test_fault_active_never_rises_is_fail():
    raw = passing_raw_channels()
    _set_values(raw, "Fault/LCC Fault Active", [0.0] * len(_channel(raw, "Fault/LCC Fault Active")["values"]))
    result = derive_fixed_lcc_dynamic_evidence(raw, dynamic_contract())
    assert result["engineering_verdict"] == "FAIL"
    assert result["checks"]["disturbance"]["outcome"] == "FAIL"


def test_gamma_without_drop_is_fail():
    raw = passing_raw_channels()
    gamma = _channel(raw, "Main/GAMMA_INV")
    gamma["values"] = [math.radians(18.0)] * len(gamma["values"])
    result = derive_fixed_lcc_dynamic_evidence(raw, dynamic_contract())
    assert result["engineering_verdict"] == "FAIL"
    assert result["checks"]["failure_indication"]["outcome"] == "FAIL"


def test_current_peak_ratio_above_bound_is_fail():
    raw = passing_raw_channels()
    idc = _channel(raw, "Main/IDC")
    idc["values"] = [3.01 if 0.8 <= t < 0.9 else 1.0 for t in idc["domain"]]
    result = derive_fixed_lcc_dynamic_evidence(raw, dynamic_contract())
    assert result["engineering_verdict"] == "FAIL"
    assert result["checks"]["bounded_dc_response"]["outcome"] == "FAIL"


def test_one_recovery_sample_outside_band_is_fail():
    raw = passing_raw_channels()
    idc = _channel(raw, "Main/IDC")
    values = list(idc["values"])
    index = next(i for i, t in enumerate(idc["domain"]) if t >= 1.35)
    values[index] = 1.3
    idc["values"] = values
    result = derive_fixed_lcc_dynamic_evidence(raw, dynamic_contract())
    assert result["engineering_verdict"] == "FAIL"
    assert result["checks"]["recovery"]["outcome"] == "FAIL"


def test_caller_supplied_dynamic_object_is_ignored():
    raw = passing_raw_channels()
    raw["dynamic"] = {"engineering_verdict": "PASS", "checks": {}}
    result = derive_fixed_lcc_dynamic_evidence(raw, dynamic_contract())
    assert result["engineering_verdict"] == "PASS"
    assert set(result["checks"]) == {
        "disturbance",
        "failure_indication",
        "bounded_dc_response",
        "recovery",
    }


def test_normalize_accepts_mapping_and_preserves_immutable_traces():
    raw = passing_raw_channels()
    mapping = {item["path"]: item for item in raw["channels"]}
    traces = normalize_exact_channels(mapping | {"channels": mapping}, dynamic_contract()["required_channels"])
    assert traces["Main/IDC"].path == "Main/IDC"
    assert isinstance(traces["Main/IDC"].time, tuple)
    assert isinstance(traces["Main/IDC"].values, tuple)
