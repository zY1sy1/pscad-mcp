"""Opt-in licensed PSCAD 4.6.2 fixed LCC smoke acceptance."""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pscad_mcp.hvdc.builders.lcc.assets import sha256_file
from pscad_mcp.hvdc.builders.lcc.fixed_acceptance_cli import main


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@unittest.skipUnless(
    os.getenv("PSCAD_MCP_LCC_WP1B_ACCEPTANCE") == "1",
    "Set PSCAD_MCP_LCC_WP1B_ACCEPTANCE=1 for licensed fixed LCC acceptance.",
)
class TestFixedLccAcceptanceReal(unittest.TestCase):
    def test_current_commit_components_compile_and_full_smoke_passes(self):
        root = Path(__file__).parents[1]
        workspace = Path(os.environ["PSCAD_MCP_WORKSPACE"]).resolve()
        master = Path(os.environ["PSCAD_MCP_MASTER_LIBRARY"]).resolve()
        compiler_configuration = Path(
            os.environ["PSCAD_MCP_COMPILER_CONFIGURATION"]
        ).resolve()
        compiler_executable = Path(
            os.environ["PSCAD_MCP_COMPILER_EXECUTABLE"]
        ).resolve()
        commit = git(root, "rev-parse", "HEAD")
        branch = git(root, "branch", "--show-current")
        run_root = workspace / (
            "fixed-lcc-test-"
            + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        )
        report = run_root / "fixed-lcc-acceptance-report.json"
        baseline = root / "docs" / "acceptance" / "lcc-mmc-program-baseline.json"
        baseline_before = sha256_file(baseline)

        exit_code = main(
            [
                "run",
                "--repository-root",
                str(root),
                "--workspace-root",
                str(run_root),
                "--master-path",
                str(master),
                "--compiler-configuration",
                str(compiler_configuration),
                "--compiler-executable",
                str(compiler_executable),
                "--report",
                str(report),
                "--commit",
                commit,
                "--branch",
                branch,
                "--project-name",
                "WP1B_FIXED_LCC_TEST",
            ]
        )

        payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 0, payload)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["component_gate"]["status"], "PASS")
        self.assertEqual(
            [item["fixture"] for item in payload["component_gate"]["fixtures"]],
            [
                "bridge_rectifier",
                "bridge_inverter",
                "rectifier_control",
                "inverter_control",
                "initialization",
                "signal_interface",
            ],
        )
        self.assertEqual(payload["build"]["terminal_state"], "published")
        self.assertEqual(payload["smoke"]["verdict"], "PASS")
        self.assertTrue(all(payload["smoke"]["checks"].values()))
        self.assertEqual(payload["runtime"]["remaining_processes"], [])
        self.assertEqual(sha256_file(baseline), baseline_before)


__all__ = ["TestFixedLccAcceptanceReal", "git"]
