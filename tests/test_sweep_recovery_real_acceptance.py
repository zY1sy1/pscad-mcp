"""Explicit opt-in real Legacy cancellation and crash/restart acceptance."""

import os
from pathlib import Path

import pytest

from scripts.run_sweep_recovery_acceptance import run_acceptance


@pytest.mark.skipif(
    os.getenv("PSCAD_MCP_ACCEPTANCE") != "1"
    or not os.getenv("PSCAD_MCP_SWEEP_RECOVERY_SPEC"),
    reason="A licensed opt-in and reviewed recovery contract are required.",
)
def test_licensed_sweep_recovery():
    workspace = Path(os.environ["PSCAD_MCP_WORKSPACE"])
    spec = Path(os.environ["PSCAD_MCP_SWEEP_RECOVERY_SPEC"])
    report = run_acceptance(workspace, spec)
    assert report["status"] == "PASS", report.get("error")
