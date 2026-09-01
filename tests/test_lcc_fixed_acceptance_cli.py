from __future__ import annotations

import json
from pathlib import Path

from pscad_mcp.hvdc.builders.lcc.fixed_acceptance_cli import main

ROOT = Path(__file__).parents[1]


def run_arguments(
    tmp_path: Path,
    report: Path,
    baseline: Path,
) -> list[str]:
    return [
        "run",
        "--repository-root",
        str(tmp_path),
        "--workspace-root",
        str(report.parent),
        "--master-path",
        str(tmp_path / "master.pslx"),
        "--compiler-configuration",
        str(tmp_path / "fortran_compilers.xml"),
        "--compiler-executable",
        str(tmp_path / "gfortran.exe"),
        "--report",
        str(report),
        "--baseline",
        str(baseline),
        "--commit",
        "a" * 40,
        "--branch",
        "codex/lcc-wp1b",
        "--project-name",
        "WP1B_FIXED_LCC",
    ]


async def fake_pass_run(request, **_kwargs):
    request.report_path.parent.mkdir(parents=True, exist_ok=True)
    request.report_path.write_text(
        json.dumps({"status": "PASS"}),
        encoding="utf-8",
    )
    return {"status": "PASS", "commit": request.commit}


def fake_service_factory(_request):
    return object(), object()


def fake_preflight(_arguments):
    return {"status": "PASS", "sha256": "d" * 64, "snapshot": {}}


def test_run_action_writes_report_and_never_touches_baseline(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_bytes(b"baseline")
    report = tmp_path / "run" / "fixed-lcc-report.json"

    exit_code = main(
        run_arguments(tmp_path, report, baseline),
        run_action=fake_pass_run,
        service_factory=fake_service_factory,
        preflight_action=fake_preflight,
    )

    assert exit_code == 0
    assert report.is_file()
    assert baseline.read_bytes() == b"baseline"


def test_promote_action_is_explicit(tmp_path):
    calls = []

    exit_code = main(
        [
            "promote",
            "--baseline",
            str(tmp_path / "baseline.json"),
            "--report",
            str(tmp_path / "report.json"),
        ],
        promote_action=lambda *args, **kwargs: calls.append((args, kwargs))
        or {},
    )

    assert exit_code == 0
    assert len(calls) == 1


def test_failed_preflight_persists_setup_report_without_creating_service(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_bytes(b"baseline")
    report = tmp_path / "run" / "fixed-lcc-report.json"
    factory_calls = []

    def service_factory(_request):
        factory_calls.append(True)
        return object(), object()

    def setup_failure(request, error):
        request.report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"status": "FAIL", "commit": request.commit}
        request.report_path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    exit_code = main(
        run_arguments(tmp_path, report, baseline),
        service_factory=service_factory,
        preflight_action=lambda _arguments: {
            "status": "FAIL",
            "sha256": "d" * 64,
            "snapshot": {},
        },
        setup_failure_action=setup_failure,
    )

    assert exit_code == 1
    assert factory_calls == []
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "FAIL"
    assert baseline.read_bytes() == b"baseline"


def test_powershell_runner_is_run_only_and_checks_cleanup():
    script = (
        ROOT / "scripts" / "run_fixed_lcc_smoke_acceptance.ps1"
    ).read_text(encoding="utf-8")

    assert "fixed_acceptance_cli" in script
    assert "'run'" in script
    assert "'promote'" not in script
    assert "FIXED_LCC_REPORT_SHA256=" in script
    assert "Get-Process" in script
    assert "git status --porcelain" in script
    assert "Stop-Process" not in script
