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
