from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.dynamic_acceptance import (
    evaluate_fixed_lcc_dynamic_samples,
    validate_dynamic_lcc_acceptance_report,
)
from tests.lcc_dynamic_fakes import valid_wp1c_report


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


def test_dynamic_report_requires_event_and_recovery_evidence():
    report = valid_wp1c_report()
    assert validate_dynamic_lcc_acceptance_report(report)["status"] == "INCOMPLETE_ANALYSIS"


def test_dynamic_report_does_not_promote_placeholder_golden():
    result = evaluate_fixed_lcc_dynamic_samples(
        valid_dynamic_samples(), placeholder_golden(), dynamic_contract()
    )
    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["dynamic"]["verdict"] == "PASS"
    assert result["physical"]["verdict"] == "PASS"


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


def test_dynamic_evaluator_derives_required_channels_from_golden_declarations():
    contract = dynamic_contract()
    del contract["required_channels"]
    result = evaluate_fixed_lcc_dynamic_samples(
        valid_dynamic_samples(), placeholder_golden(), contract
    )
    assert result["missing_channels"] == []


def test_dynamic_evaluator_stays_incomplete_without_golden_declarations():
    contract = dynamic_contract()
    contract["golden"]["channels"] = []
    result = evaluate_fixed_lcc_dynamic_samples(
        valid_dynamic_samples(), {}, contract
    )
    assert result["verdict"] == "INCOMPLETE_ANALYSIS"


def test_dynamic_report_rejects_forged_pass_with_placeholder_golden():
    report = valid_wp1c_report()
    report["status"] = "PASS"
    with pytest.raises(BackendError):
        validate_dynamic_lcc_acceptance_report(report)


def test_dynamic_report_requires_failure_details_for_fail_status():
    report = valid_wp1c_report()
    report["status"] = "FAIL"
    with pytest.raises(BackendError):
        validate_dynamic_lcc_acceptance_report(report)


def test_wp1c_report_allows_engineering_pass_with_incomplete_golden():
    report = valid_wp1c_report()
    normalized = validate_dynamic_lcc_acceptance_report(report)
    assert normalized["capability_state"] == "simulated"
    assert normalized["kind"] == "licensed_simulation"
    assert normalized["engineering_verdict"] == "PASS"
    assert normalized["golden_verdict"] == "INCOMPLETE_ANALYSIS"
    assert normalized["status"] == "INCOMPLETE_ANALYSIS"


def test_wp1c_report_rejects_total_pass_without_reviewed_golden():
    report = valid_wp1c_report()
    report["status"] = "PASS"
    with pytest.raises(BackendError) as raised:
        validate_dynamic_lcc_acceptance_report(report)
    assert raised.value.code == "LCC_DYNAMIC_REPORT_INVALID"


@pytest.mark.parametrize(
    ("section", "extra"),
    [
        ("dynamic", {"unexpected": True}),
        ("artifacts", {"project": None}),
        ("runtime", {"unexpected": True}),
    ],
)
def test_dynamic_report_rejects_nested_schema_mutations(section, extra):
    report = valid_wp1c_report()
    report[section].update(extra)
    with pytest.raises(BackendError):
        validate_dynamic_lcc_acceptance_report(report)


def test_fail_report_with_minimal_sections_self_validates():
    report = valid_wp1c_report()
    report["status"] = "FAIL"
    report["engineering_verdict"] = "FAIL"
    report["golden_verdict"] = "INCOMPLETE_ANALYSIS"
    report["failure"] = {"stage": "setup", "code": "X", "message": "broken"}
    snapshot = {name: {"path": f"/tmp/{name}", "sha256": "a" * 64} for name in report["sources"]}
    report["preflight"] = {"status": "FAIL", "sha256": hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "snapshot": snapshot}
    report["build"]["terminal_state"] = "failed"
    report["build"]["history"] = []
    report["dynamic"] = {"evidence_source": "raw_pscad_output", "engineering_verdict": "FAIL", "checks": {}}
    report["physical"] = {"verdict": "FAIL", "checks": []}
    report["artifacts"] = {
        "project": None,
        "library": None,
        "selected_output": None,
        "output_parts": [],
        "output_metadata": [],
        "normalized_samples": None,
    }
    report["runtime"] = {
        "remaining_processes": [],
        "managed_pid": None,
        "backend": None,
        "version": None,
        "x64": None,
        "licensed": None,
        "quit_error": None,
    }
    assert validate_dynamic_lcc_acceptance_report(report)["status"] == "FAIL"


def test_roadmap_names_wp1c_as_the_next_step():
    roadmap = Path(__file__).parents[1] / "docs" / "superpowers" / "specs" / "2026-08-30-lcc-mmc-completion-roadmap-design.md"
    text = roadmap.read_text(encoding="utf-8")
    assert "执行 WP1C fixed LCC 动态验收" in text
    assert "先审阅并合并 WP0 分支" not in text


def test_readme_documents_dynamic_evidence_status():
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    assert "run_fixed_lcc_dynamic_acceptance.ps1" in readme
    assert "INCOMPLETE_ANALYSIS" in readme
