from __future__ import annotations

import json
from pathlib import Path

from pscad_mcp.hvdc.builders.lcc.dynamic_acceptance_cli import main


def _wave(values: list[float], units: str) -> dict[str, object]:
    return {"units": units, "time": [0.0, 0.01, 0.02, 0.03], "values": values}


def _contract() -> dict[str, object]:
    return {
        "golden": {
            "comparison_window": [0.0, 0.03],
            "scale_floor": 1e-9,
            "nrmse_limit": 0.05,
            "max_error_limit": 0.15,
            "channels": [{"name": "Main/VDC_RECT", "units": "kV", "required": True}],
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
        "required_channels": ["Main/VDC_RECT"],
    }


def _samples() -> dict[str, object]:
    return {
        "channels": {"Main/VDC_RECT": _wave([500.0] * 4, "kV")},
        "dynamic": {
            "disturbance": True,
            "failure_indication": True,
            "dc_current_peak_ka": 1.2,
            "dc_current_limit_ka": 3.0,
            "recovered": True,
        },
    }


def test_evaluate_cli_writes_incomplete_report_for_placeholder_golden(tmp_path: Path):
    samples = tmp_path / "samples.json"
    golden = tmp_path / "golden.json"
    contract = tmp_path / "contract.json"
    report = tmp_path / "dynamic-report.json"
    samples.write_text(json.dumps(_samples()), encoding="utf-8")
    golden.write_text(json.dumps({"source": "reference run placeholder"}), encoding="utf-8")
    contract.write_text(json.dumps(_contract()), encoding="utf-8")

    exit_code = main(
        [
            "evaluate",
            "--samples",
            str(samples),
            "--golden",
            str(golden),
            "--contract",
            str(contract),
            "--report",
            str(report),
            "--commit",
            "a" * 40,
            "--branch",
            "codex/wp1c",
            "--event-time",
            "0.8",
            "--event-duration",
            "0.1",
            "--recovery-window",
            "0.5",
        ]
    )

    assert exit_code == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "INCOMPLETE_ANALYSIS"
    assert payload["dynamic"]["physical"]["verdict"] == "PASS"
    assert payload["failure"] is None


def test_evaluate_cli_persists_failure_for_invalid_input(tmp_path: Path):
    report = tmp_path / "dynamic-report.json"
    exit_code = main(
        [
            "evaluate",
            "--samples",
            str(tmp_path / "missing.json"),
            "--golden",
            str(tmp_path / "missing-golden.json"),
            "--contract",
            str(tmp_path / "missing-contract.json"),
            "--report",
            str(report),
            "--commit",
            "b" * 40,
            "--branch",
            "codex/wp1c",
            "--event-time",
            "0.8",
            "--event-duration",
            "0.1",
            "--recovery-window",
            "0.5",
        ]
    )

    assert exit_code == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["failure"]["stage"] == "input"
