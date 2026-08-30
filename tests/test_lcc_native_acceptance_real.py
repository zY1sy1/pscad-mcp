from __future__ import annotations

import json
import os
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pscad_mcp.acceptance import index_explicit_reports
from pscad_mcp.core.process_inventory import list_pscad_processes
from pscad_mcp.hvdc.builders.lcc.assets import sha256_file
from pscad_mcp.hvdc.builders.lcc.native_acceptance_cli import main


@unittest.skipUnless(
    os.getenv("PSCAD_MCP_LCC_WP1A_ACCEPTANCE") == "1",
    "Set PSCAD_MCP_LCC_WP1A_ACCEPTANCE=1 for licensed native LCC acceptance.",
)
class TestNativeLccAcceptanceReal(unittest.TestCase):
    def test_current_commit_native_build_simulates_and_reports_pass(self):
        root = Path(__file__).parents[1]
        workspace = Path(os.environ["PSCAD_MCP_WORKSPACE"])
        template = Path(os.environ["PSCAD_MCP_LCC_TEMPLATE"])
        master = Path(os.environ["PSCAD_MCP_MASTER_LIBRARY"])
        compiler_configuration = Path(
            os.environ["PSCAD_MCP_COMPILER_CONFIGURATION"]
        )
        compiler_executable = Path(os.environ["PSCAD_MCP_COMPILER_EXECUTABLE"])
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        run_root = workspace / (
            "native-lcc-test-"
            + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        )
        report_path = run_root / "native-lcc-acceptance-report.json"
        baseline = root / "docs" / "acceptance" / "lcc-mmc-program-baseline.json"
        baseline_before = sha256_file(baseline)

        exit_code = main(
            [
                "run",
                "--repository-root",
                str(root),
                "--workspace-root",
                str(run_root),
                "--template-path",
                str(template),
                "--master-path",
                str(master),
                "--compiler-configuration",
                str(compiler_configuration),
                "--compiler-executable",
                str(compiler_executable),
                "--report",
                str(report_path),
                "--commit",
                commit,
                "--branch",
                branch,
                "--project-name",
                "WP1A_NATIVE_LCC_TEST",
            ]
        )

        payload = json.loads(report_path.read_text(encoding="utf-8"))
        indexed = index_explicit_reports([{"path": str(report_path)}])[0]
        self.assertEqual(exit_code, 0, payload)
        self.assertEqual(indexed["status"], "PASS")
        self.assertEqual(indexed["commit"], commit)
        self.assertEqual(payload["build"]["terminal_state"], "published")
        self.assertTrue(all(payload["acceptance"]["checks"].values()))
        self.assertEqual(
            payload["sources"]["template"]["before"],
            payload["sources"]["template"]["after"],
        )
        self.assertEqual(
            payload["sources"]["master"]["before"],
            payload["sources"]["master"]["after"],
        )
        self.assertEqual(list_pscad_processes(), [])
        self.assertEqual(sha256_file(baseline), baseline_before)
