from __future__ import annotations

import json
from pathlib import Path

from pscad_mcp.hvdc.builders.lcc.native_acceptance_cli import main

ROOT = Path(__file__).parents[1]


def test_run_action_writes_external_report_without_touching_baseline(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text("baseline", encoding="ascii")
    report = tmp_path / "workspace" / "run" / "report.json"

    async def runner(request, **kwargs):
        request.report_path.parent.mkdir(parents=True)
        request.report_path.write_text(
            json.dumps({"status": "PASS"}),
            encoding="utf-8",
        )
        return {"status": "PASS", "commit": request.commit}

    result = main(
        [
            "run",
            "--repository-root",
            str(tmp_path),
            "--workspace-root",
            str(tmp_path / "workspace"),
            "--template-path",
            str(tmp_path / "official.pscx"),
            "--master-path",
            str(tmp_path / "master.pslx"),
            "--compiler-configuration",
            str(tmp_path / "fortran_compilers.xml"),
            "--compiler-executable",
            str(tmp_path / "gfortran.exe"),
            "--report",
            str(report),
            "--commit",
            "a" * 40,
            "--branch",
            "codex/lcc-wp1a",
        ],
        run_action=runner,
        service_factory=lambda request: (
            object(),
            object(),
            "b" * 64,
            "c" * 64,
            "d" * 64,
        ),
        preflight_action=lambda arguments: {
            "status": "PASS",
            "sha256": "d" * 64,
            "snapshot": {},
        },
    )

    assert result == 0
    assert baseline.read_text(encoding="ascii") == "baseline"


def test_run_action_persists_service_factory_failure(tmp_path):
    report = tmp_path / "workspace" / "run" / "report.json"

    def setup_failure(request, error):
        request.report_path.parent.mkdir(parents=True)
        payload = {"status": "FAIL", "commit": request.commit}
        request.report_path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def fail_factory(request):
        raise RuntimeError("factory failed")

    result = main(
        [
            "run",
            "--repository-root",
            str(tmp_path),
            "--workspace-root",
            str(tmp_path / "workspace"),
            "--template-path",
            str(tmp_path / "official.pscx"),
            "--master-path",
            str(tmp_path / "master.pslx"),
            "--compiler-configuration",
            str(tmp_path / "fortran_compilers.xml"),
            "--compiler-executable",
            str(tmp_path / "gfortran.exe"),
            "--report",
            str(report),
            "--commit",
            "a" * 40,
            "--branch",
            "codex/lcc-wp1a",
        ],
        service_factory=fail_factory,
        preflight_action=lambda arguments: {
            "status": "PASS",
            "sha256": "d" * 64,
            "snapshot": {},
        },
        setup_failure_action=setup_failure,
    )

    assert result == 1
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "FAIL"


def test_promote_action_calls_explicit_baseline_promotion(tmp_path):
    calls = []

    def promote(baseline, report, **kwargs):
        calls.append((baseline, report, kwargs))
        return {"scopes": []}

    result = main(
        [
            "promote",
            "--baseline",
            str(tmp_path / "baseline.json"),
            "--report",
            str(tmp_path / "report.json"),
        ],
        promote_action=promote,
    )

    assert result == 0
    assert calls[0][0] == tmp_path / "baseline.json"
    assert calls[0][1] == tmp_path / "report.json"


def test_powershell_runner_is_run_only_and_checks_cleanup():
    script = (
        ROOT / "scripts" / "run_blank_lcc_native_acceptance.ps1"
    ).read_text(encoding="utf-8")
    assert "native_acceptance_cli" in script
    assert "'run'" in script
    assert "'promote'" not in script
    assert "NATIVE_LCC_REPORT_SHA256=" in script
    assert "Get-Process" in script
    assert "source_after" in script or "sources.template.after" in script
