"""Optional arrester studies must not opt themselves into licensed PSCAD."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _environment(source):
    env = os.environ.copy()
    env.pop("PSCAD_MCP_ACCEPTANCE", None)
    env.pop("PSCAD_MCP_ACCEPTANCE_CONCURRENT", None)
    env["ARRESTER_PREVIEW_SOURCE"] = str(source)
    return env


@pytest.mark.parametrize("script", [
    "preview_five_arresters.py",
    "try_cumulative_arresters.py",
    "run_arrester_ratio_study.py",
])
def test_missing_optin_is_rejected_before_model_or_output_access(script, tmp_path):
    # Existing output and an empty plan also prevent the old implementation
    # from reaching PSCAD while demonstrating its missing consent gate.
    (tmp_path / "search.json").write_text("{}", encoding="utf-8")
    arguments = [] if script.startswith("preview") else ["--output", str(tmp_path)]
    if script == "run_arrester_ratio_study.py":
        arguments.insert(0, "simulate")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *arguments],
        cwd=tmp_path, env=_environment(tmp_path),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert "PSCAD_MCP_ACCEPTANCE=1" in result.stdout + result.stderr
    assert "PSCAD_MCP_ACCEPTANCE_CONCURRENT=1" in result.stdout + result.stderr
    assert sorted(path.name for path in tmp_path.iterdir()) == ["search.json"]


def test_importing_preview_preserves_environment_and_filesystem(tmp_path):
    preview = str(SCRIPTS / "preview_five_arresters.py")
    code = (
        f"import os,runpy,json; runpy.run_path({preview!r}); "
        "print(json.dumps({key:os.environ.get(key) for key in "
        "['PSCAD_MCP_ACCEPTANCE','PSCAD_MCP_ACCEPTANCE_CONCURRENT']}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path,
        env=_environment(tmp_path), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "PSCAD_MCP_ACCEPTANCE": None, "PSCAD_MCP_ACCEPTANCE_CONCURRENT": None,
    }
    assert list(tmp_path.iterdir()) == []
