"""Native stderr is ordinary unittest output, including under Windows PS 5.1."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


SHELLS = [value for value in dict.fromkeys((shutil.which("powershell.exe"), shutil.which("pwsh"))) if value]


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell runner coverage")
@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("python_exit, expected", [(2, 2), (0, 1)])
def test_dynamic_post_run_preserves_preflight_failure_without_pid(tmp_path, shell, python_exit, expected):
    script = Path(__file__).resolve().parents[1] / "scripts" / "run_fixed_lcc_dynamic_acceptance.ps1"
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"runtime": {"managed_pid": None}, "status": "FAIL", "engineering_verdict": "FAIL"}))
    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"

    command = (
        "$ErrorActionPreference='Stop'; $tokens=$null; $errors=$null; "
        f"$ast=[System.Management.Automation.Language.Parser]::ParseFile({quote(script)},[ref]$tokens,[ref]$errors); "
        "$outer=$ast.Find({param($n) $n -is [System.Management.Automation.Language.TryStatementAst]},$false); "
        "$statements=$outer.Body.Statements; "
        "$assignment=$statements | Where-Object {$_.Extent.Text -eq '$ExitCode = $LASTEXITCODE'} | Select-Object -First 1; "
        "if (-not $assignment) {throw 'Post-run boundary unavailable'}; "
        "$post=$statements | Where-Object {$_.Extent.StartOffset -gt $assignment.Extent.EndOffset}; "
        "$block=[scriptblock]::Create(($post | ForEach-Object {$_.Extent.Text}) -join [Environment]::NewLine); "
        "$env:PSCAD_MCP_ACCEPTANCE_CONCURRENT='1'; "
        f"$Report={quote(report)}; $ExitCode={python_exit}; "
        "try { & $block } catch {Write-Output ('POST_ERROR='+$_.Exception.Message); $ExitCode=1}; Write-Output ('POST_EXIT='+$ExitCode)"
    )
    # Each PowerShell version must discover its own bundled utility modules.
    env = {key: value for key, value in os.environ.items() if key.casefold() != "psmodulepath"}
    result = subprocess.run([shell, "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=30, env=env)
    assert result.returncode == 0, result.stderr
    assert f"POST_EXIT={expected}" in result.stdout


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell runner coverage")
@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("exit_code", [0, 7])
def test_native_stderr_is_captured_without_losing_exit_code(shell, exit_code):
    helper = Path(__file__).resolve().parents[1] / "scripts" / "acceptance_test_command.ps1"
    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"

    code = f"import sys; print('ACCEPTANCE_PID=42'); print('normal progress', file=sys.stderr); sys.exit({exit_code})"
    command = (
        "$ErrorActionPreference='Stop'; "
        f". {quote(helper)}; "
        f"$result=Invoke-AcceptanceTestCommand -Executable {quote(sys.executable)} "
        f"-ArgumentList @('-c', {quote(code)}); "
        "[pscustomobject]@{ExitCode=$result.ExitCode; Output=$result.Output; "
        "Preference=[string]$ErrorActionPreference} | ConvertTo-Json -Compress"
    )
    completed = subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.splitlines()[-1])
    assert result["ExitCode"] == exit_code
    assert result["Preference"] == "Stop"
    assert "ACCEPTANCE_PID=42" in result["Output"]
    assert any("normal progress" in line for line in result["Output"])
