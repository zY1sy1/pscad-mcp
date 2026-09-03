from __future__ import annotations

import json
from pathlib import Path

import pytest

from pscad_mcp.hvdc.builders.lcc.dynamic_acceptance import (
    validate_dynamic_lcc_acceptance_report,
)
from pscad_mcp.hvdc.builders.lcc.dynamic_acceptance_cli import main, run_exit_code
from tests.lcc_dynamic_fakes import valid_wp1c_report

ROOT = Path(__file__).parents[1]


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


def test_evaluate_cli_persists_failure_even_with_invalid_commit_metadata(tmp_path: Path):
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
            "bad",
            "--branch",
            "codex/wp1c",
            "--event-time",
            "nan",
            "--event-duration",
            "0.1",
            "--recovery-window",
            "0.5",
        ]
    )

    assert exit_code == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert len(payload["commit"]) == 40
    assert payload["dynamic"]["event"]["time_s"] == 0.0


def test_evaluate_cli_records_evaluation_failure_and_waveform_checks(tmp_path: Path):
    samples = tmp_path / "samples.json"
    golden = tmp_path / "golden.json"
    contract = tmp_path / "contract.json"
    report = Path("dynamic-report.json")
    samples.write_text(json.dumps(_samples()), encoding="utf-8")
    golden.write_text(json.dumps({"source": "reference run placeholder"}), encoding="utf-8")
    contract.write_text(json.dumps(_contract()), encoding="utf-8")
    try:
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
        assert "golden_checks" in payload["dynamic"]["physical"]
    finally:
        report.unlink(missing_ok=True)


def test_evaluate_cli_records_failure_details_for_missing_required_channel(tmp_path: Path):
    samples = _samples()
    del samples["channels"]["Main/VDC_RECT"]
    samples_path = tmp_path / "samples.json"
    golden_path = tmp_path / "golden.json"
    contract_path = tmp_path / "contract.json"
    report = tmp_path / "report.json"
    samples_path.write_text(json.dumps(samples), encoding="utf-8")
    golden_path.write_text(json.dumps({"source": "reference run placeholder"}), encoding="utf-8")
    contract_path.write_text(json.dumps(_contract()), encoding="utf-8")
    assert main(
        [
            "evaluate", "--samples", str(samples_path), "--golden", str(golden_path),
            "--contract", str(contract_path), "--report", str(report),
            "--commit", "a" * 40, "--branch", "codex/wp1c",
            "--event-time", "0.8", "--event-duration", "0.1", "--recovery-window", "0.5",
        ]
    ) == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["failure"]["stage"] == "evaluation"


@pytest.mark.parametrize(
    ("preflight", "engineering", "expected"),
    [("FAIL", "FAIL", 2), ("PASS", "FAIL", 1), ("PASS", "PASS", 0)],
)
def test_run_exit_code_separates_preflight_and_engineering(preflight, engineering, expected):
    assert run_exit_code(preflight_status=preflight, engineering_verdict=engineering) == expected


def _run_args(tmp_path: Path, report: Path) -> list[str]:
    return [
        "run",
        "--repository-root", str(tmp_path),
        "--workspace-root", str(report.parent),
        "--master-path", str(tmp_path / "master.pslx"),
        "--compiler-configuration", str(tmp_path / "fortran_compilers.xml"),
        "--compiler-executable", str(tmp_path / "gfortran.exe"),
        "--report", str(report),
        "--commit", "a" * 40,
        "--branch", "codex/wp1c",
    ]


def _fake_valid_report(report: Path) -> dict[str, object]:
    payload = valid_wp1c_report()
    workspace = report.parent.resolve()
    payload["build"]["workspace"] = str(workspace)
    for name, suffix in (("project", ".pscx"), ("library", ".pslx"), ("normalized_samples", ".json")):
        payload["artifacts"][name]["path"] = str(workspace / f"{name}{suffix}")
    payload["artifacts"]["selected_output"]["path"] = str(workspace / "run_01.out")
    payload["artifacts"]["output_parts"][0]["path"] = str(workspace / "run_01.out")
    payload["artifacts"]["output_metadata"][0]["path"] = str(workspace / "run.inf")
    return payload


def test_run_preflight_failure_returns_two_without_creating_service(tmp_path: Path):
    report = tmp_path / "run" / "report.json"
    calls: list[str] = []
    code = main(
        _run_args(tmp_path, report),
        preflight_action=lambda _args: {"status": "FAIL", "sha256": "d" * 64, "snapshot": {}},
        service_factory=lambda _request: calls.append("service") or (object(), object()),
    )
    assert code == 2
    assert calls == []
    persisted = json.loads(report.read_text(encoding="utf-8"))
    assert validate_dynamic_lcc_acceptance_report(persisted)["failure"]["stage"] == "setup"


def test_run_preflight_failure_does_not_overwrite_existing_report(tmp_path: Path):
    report = tmp_path / "run" / "report.json"
    report.parent.mkdir(parents=True)
    sentinel = b"existing-report"
    report.write_bytes(sentinel)
    code = main(
        _run_args(tmp_path, report),
        preflight_action=lambda _args: {"status": "FAIL", "error": {"code": "PREFLIGHT_X", "message": "bad compiler"}},
        service_factory=lambda _request: (_ for _ in ()).throw(AssertionError("must not create service")),
    )
    assert code == 2
    assert report.read_bytes() == sentinel


def test_run_preflight_failure_new_report_preserves_stable_code_and_reason(tmp_path: Path):
    report = tmp_path / "run" / "report.json"
    code = main(
        _run_args(tmp_path, report),
        preflight_action=lambda _args: {"status": "FAIL", "error": {"code": "PREFLIGHT_X", "message": "bad compiler"}, "details": {"source": "compiler"}},
    )
    assert code == 2
    persisted = validate_dynamic_lcc_acceptance_report(json.loads(report.read_text(encoding="utf-8")))
    assert persisted["failure"]["code"] == "LCC_DYNAMIC_PREFLIGHT_FAILED"
    assert "bad compiler" in persisted["failure"]["message"]


def test_run_engineering_pass_with_incomplete_status_returns_zero(tmp_path: Path):
    report = tmp_path / "run" / "report.json"
    payload = _fake_valid_report(report)

    async def fake_runner(request, **_kwargs):
        request.report_path.parent.mkdir(parents=True, exist_ok=True)
        request.report_path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    code = main(
        _run_args(tmp_path, report),
        preflight_action=lambda _args: {"status": "PASS", "sha256": "d" * 64, "snapshot": {}},
        service_factory=lambda _request: (object(), object()),
        run_action=fake_runner,
    )
    assert code == 0
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "INCOMPLETE_ANALYSIS"


def test_run_engineering_failure_returns_one(tmp_path: Path):
    report = tmp_path / "run" / "report.json"
    payload = _fake_valid_report(report)
    payload["engineering_verdict"] = "FAIL"
    payload["status"] = "FAIL"
    payload["dynamic"] = {"evidence_source": "raw_pscad_output", "engineering_verdict": "FAIL", "checks": {}}
    payload["physical"] = {"verdict": "FAIL", "checks": []}
    payload["build"]["terminal_state"] = "failed"
    payload["build"]["history"] = []
    payload["artifacts"] = {
        "project": None,
        "library": None,
        "selected_output": None,
        "output_parts": [],
        "output_metadata": [],
        "normalized_samples": None,
    }

    async def fake_runner(request, **_kwargs):
        request.report_path.parent.mkdir(parents=True, exist_ok=True)
        request.report_path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    code = main(
        _run_args(tmp_path, report),
        preflight_action=lambda _args: {"status": "PASS", "sha256": "d" * 64, "snapshot": {}},
        service_factory=lambda _request: (object(), object()),
        run_action=fake_runner,
    )
    assert code == 1


def test_run_service_factory_failure_persists_strict_report(tmp_path: Path):
    report = tmp_path / "run" / "report.json"
    code = main(
        _run_args(tmp_path, report),
        preflight_action=lambda _args: {"status": "PASS", "sha256": "d" * 64, "snapshot": {}},
        service_factory=lambda _request: (_ for _ in ()).throw(RuntimeError("factory failed")),
    )
    assert code == 1
    persisted = json.loads(report.read_text(encoding="utf-8"))
    assert validate_dynamic_lcc_acceptance_report(persisted)["failure"]["stage"] == "setup"


def test_run_service_factory_failure_does_not_overwrite_existing_report(tmp_path: Path):
    report = tmp_path / "run" / "report.json"
    report.parent.mkdir(parents=True)
    sentinel = b"existing-report"
    report.write_bytes(sentinel)
    code = main(
        _run_args(tmp_path, report),
        preflight_action=lambda _args: {"status": "PASS", "sha256": "d" * 64, "snapshot": {}},
        service_factory=lambda _request: (_ for _ in ()).throw(RuntimeError("factory failed")),
    )
    assert code == 1
    assert report.read_bytes() == sentinel


def test_dynamic_wrapper_uses_run_and_no_manual_sample_contract_inputs():
    script = (ROOT / "scripts" / "run_fixed_lcc_dynamic_acceptance.ps1").read_text(encoding="utf-8")
    assert "dynamic_acceptance_cli run" in script
    assert "[string]$WorkspaceRoot" in script
    assert "[string]$MasterPath" in script
    assert "[string]$CompilerConfiguration" in script
    assert "[string]$CompilerExecutable" in script
    assert "[string]$ProjectName" in script
    assert "[string]$Samples" not in script
    assert "[string]$Golden" not in script
    assert "[string]$Contract" not in script
    for field in (
        "FIXED_LCC_DYNAMIC_REPORT=",
        "FIXED_LCC_DYNAMIC_REPORT_SHA256=",
        "FIXED_LCC_DYNAMIC_ENGINEERING_VERDICT=",
        "FIXED_LCC_DYNAMIC_STATUS=",
    ):
        assert field in script
