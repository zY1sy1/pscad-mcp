from __future__ import annotations

import json
from pathlib import Path

import pytest

from pscad_mcp.acceptance.preflight_cli import main

COMMIT = "dadd739e2abc14dcc7de73149da7fd7f0c0ca763"
ROOT = Path(__file__).parents[1]


def arguments(tmp_path, *, output=None):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return [
        "--repository-root",
        str(tmp_path),
        "--workspace-root",
        str(workspace),
        "--master-path",
        str(tmp_path / "master.pslx"),
        "--compiler-configuration",
        str(tmp_path / "fortran_compilers.xml"),
        "--compiler-executable",
        str(tmp_path / "gfortran.exe"),
        "--expected-commit",
        COMMIT,
        "--expected-branch",
        "codex/lcc-mmc-wp0-baseline",
        "--output",
        str(output or workspace / "run-1" / "program-preflight-report.json"),
    ]


@pytest.mark.parametrize(("status", "exit_code"), [("PASS", 0), ("FAIL", 1)])
def test_cli_writes_commit_owned_report_and_returns_status(
    tmp_path,
    status,
    exit_code,
):
    async def runner(request, service):
        assert request.expected_commit == COMMIT
        return {
            "schema_version": 1,
            "kind": "lcc_mmc_program_preflight",
            "commit": request.expected_commit,
            "status": status,
        }

    result = main(
        arguments(tmp_path),
        runner=runner,
        service_factory=lambda root: object(),
    )

    output = tmp_path / "workspace" / "run-1" / "program-preflight-report.json"
    assert result == exit_code
    assert json.loads(output.read_text(encoding="ascii"))["commit"] == COMMIT


def test_cli_rejects_report_path_outside_workspace(tmp_path):
    async def runner(request, service):
        raise AssertionError("runner must not be called")

    with pytest.raises(SystemExit, match="contained"):
        main(
            arguments(tmp_path, output=tmp_path / "outside.json"),
            runner=runner,
            service_factory=lambda root: object(),
        )


def test_powershell_runner_uses_report_cli_and_checks_cleanup():
    script = (
        ROOT / "scripts" / "run_lcc_mmc_program_preflight.ps1"
    ).read_text(encoding="utf-8")

    assert "-m pscad_mcp.acceptance.preflight_cli" in script
    assert "--expected-commit $commit" in script
    assert "program-preflight-report.json" in script
    assert "ConvertFrom-Json" in script
    assert "PROGRAM_PREFLIGHT_SHA256=" in script
    assert "Get-Process" in script
    assert "'.pscx', '.pslx', '.pswx'" in script
