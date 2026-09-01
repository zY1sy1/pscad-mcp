from __future__ import annotations

import copy
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.dynamic_acceptance import (
    evaluate_fixed_lcc_dynamic_samples,
    validate_dynamic_lcc_acceptance_report,
)


def _wave(values: list[float], units: str) -> dict[str, object]:
    return {"units": units, "time": [0.0, 0.01, 0.02, 0.03], "values": values}


def dynamic_contract() -> dict[str, object]:
    return {
        "golden": {
            "comparison_window": [0.0, 0.03],
            "scale_floor": 1.0e-9,
            "nrmse_limit": 0.05,
            "max_error_limit": 0.15,
            "channels": [
                {"name": "Main/VDC_RECT", "units": "kV", "required": True},
                {"name": "Main/IDC", "units": "kA", "required": True},
            ],
        },
        "physical_checks": [
            {
                "name": "rectifier_dc_voltage",
                "kind": "dc_magnitude_polarity",
                "channel": "Main/VDC_RECT",
                "units": "kV",
                "polarity": "positive",
                "min": 0.0,
                "max": 1000.0,
                "window": [0.0, 0.03],
                "required": True,
            }
        ],
        "checks": [
            {"name": "golden_waveforms", "kind": "golden", "required": True},
            {"name": "physical", "kind": "physical", "required": True},
        ],
        "required_channels": ["Main/VDC_RECT", "Main/IDC"],
    }


def valid_dynamic_samples() -> dict[str, object]:
    return {
        "channels": {
            "Main/VDC_RECT": _wave([500.0, 500.0, 500.0, 500.0], "kV"),
            "Main/IDC": _wave([1.0, 1.0, 1.0, 1.0], "kA"),
        },
        "dynamic": {
            "disturbance": True,
            "failure_indication": True,
            "dc_current_peak_ka": 1.2,
            "dc_current_limit_ka": 3.0,
            "recovered": True,
        },
    }


def placeholder_golden() -> dict[str, object]:
    return {"source": "independently reviewed reference run placeholder"}


def valid_dynamic_report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": "dynamic-run-1",
        "scope": "lcc.fixed_autonomous",
        "builder_path": "lcc.fixed_autonomous",
        "kind": "licensed_acceptance",
        "capability_state": "accepted",
        "commit": "a" * 40,
        "generated_at_utc": "2026-09-01T00:00:00Z",
        "status": "INCOMPLETE_ANALYSIS",
        "repository": {"branch": "codex/wp1c", "commit": "a" * 40, "clean": True},
        "dynamic": {
            "event": {"kind": "inverter_ac_disturbance", "time_s": 0.8, "duration_s": 0.1},
            "recovery": {"observed": True, "window_s": 0.5},
            "required_channels": ["Main/VDC_RECT", "Main/IDC"],
            "physical": {"verdict": "PASS"},
        },
        "golden": {"source": "independently reviewed reference run placeholder"},
        "explicit_exclusions": ["independent_golden", "final_accepted"],
        "failure": None,
    }


def test_dynamic_report_requires_event_and_recovery_evidence():
    report = valid_dynamic_report()
    assert validate_dynamic_lcc_acceptance_report(report)["status"] == "INCOMPLETE_ANALYSIS"
    report["dynamic"]["recovery"] = None
    with pytest.raises(BackendError):
        validate_dynamic_lcc_acceptance_report(report)


def test_dynamic_report_does_not_promote_placeholder_golden():
    result = evaluate_fixed_lcc_dynamic_samples(
        valid_dynamic_samples(), placeholder_golden(), dynamic_contract()
    )
    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["dynamic"]["verdict"] == "PASS"


def test_dynamic_report_fails_when_required_channel_is_missing():
    samples = valid_dynamic_samples()
    del samples["channels"]["Main/IDC"]
    result = evaluate_fixed_lcc_dynamic_samples(samples, {}, dynamic_contract())
    assert result["verdict"] == "FAIL"
    assert result["missing_channels"] == ["Main/IDC"]


def test_dynamic_report_fails_when_fault_is_not_bounded_or_recovered():
    samples = copy.deepcopy(valid_dynamic_samples())
    samples["dynamic"]["dc_current_peak_ka"] = 4.0
    result = evaluate_fixed_lcc_dynamic_samples(samples, {}, dynamic_contract())
    assert result["verdict"] == "FAIL"
    assert result["dynamic"]["verdict"] == "FAIL"


def test_roadmap_names_wp1c_as_the_next_step():
    roadmap = Path(__file__).parents[1] / "docs" / "superpowers" / "specs" / "2026-08-30-lcc-mmc-completion-roadmap-design.md"
    text = roadmap.read_text(encoding="utf-8")
    assert "执行 WP1C fixed LCC 动态验收" in text
    assert "先审阅并合并 WP0 分支" not in text


def test_readme_documents_dynamic_evidence_status():
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    assert "run_fixed_lcc_dynamic_acceptance.ps1" in readme
    assert "INCOMPLETE_ANALYSIS" in readme
