from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("PSCAD_MCP_ACCEPTANCE") != "1",
    reason="Set PSCAD_MCP_ACCEPTANCE=1 for licensed WP1C validation.",
)


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def invoke_real_dynamic_cli_from_environment(tmp_path: Path):
    root = Path(__file__).parents[1].resolve()
    master = os.getenv("PSCAD_MCP_MASTER_PATH")
    compiler_configuration = os.getenv("PSCAD_MCP_COMPILER_CONFIGURATION")
    compiler_executable = os.getenv("PSCAD_MCP_COMPILER_EXECUTABLE")
    workspace = os.getenv("PSCAD_MCP_WORKSPACE_ROOT")
    if not all((master, compiler_configuration, compiler_executable, workspace)):
        raise RuntimeError(
            "PSCAD_MCP_MASTER_PATH, PSCAD_MCP_COMPILER_CONFIGURATION, "
            "PSCAD_MCP_COMPILER_EXECUTABLE, and PSCAD_MCP_WORKSPACE_ROOT are required."
        )
    report = Path(workspace) / "fixed-lcc-dynamic-report.json"
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=root, text=True).strip()
    command = [
        sys.executable,
        "-m",
        "pscad_mcp.hvdc.builders.lcc.dynamic_acceptance_cli",
        "run",
        "--repository-root", str(root),
        "--workspace-root", str(Path(workspace)),
        "--master-path", master,
        "--compiler-configuration", compiler_configuration,
        "--compiler-executable", compiler_executable,
        "--report", str(report),
        "--commit", git_head(),
        "--branch", branch,
    ]
    completed = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    payload = json.loads(report.read_text(encoding="utf-8"))
    return type("RealResult", (), {"exit_code": completed.returncode, "report": payload})()


def test_fixed_lcc_dynamic_runner_uses_current_named_checkout(tmp_path: Path):
    result = invoke_real_dynamic_cli_from_environment(tmp_path)
    assert result.exit_code == 0
    assert result.report["engineering_verdict"] == "PASS"
    assert result.report["golden_verdict"] == "INCOMPLETE_ANALYSIS"
    assert result.report["status"] == "INCOMPLETE_ANALYSIS"
    assert result.report["commit"] == git_head()
    assert result.report["runtime"]["remaining_processes"] == []
