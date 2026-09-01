"""Opt-in licensed PSCAD 4.6.2 program preflight."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from pscad_mcp.acceptance.preflight import run_licensed_session_preflight
from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.executor import robust_executor
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.process_inventory import list_pscad_processes
from pscad_mcp.core.service import PscadService


@unittest.skipUnless(
    os.getenv("PSCAD_MCP_PROGRAM_PREFLIGHT") == "1",
    "Set PSCAD_MCP_PROGRAM_PREFLIGHT=1 for licensed PSCAD preflight.",
)
class TestLccMmcProgramPreflightReal(unittest.IsolatedAsyncioTestCase):
    async def test_attach_license_runtime_and_cleanup(self):
        workspace = Path(os.environ["PSCAD_MCP_WORKSPACE"])
        backend = LegacyBackend(
            robust_executor,
            version="4.6.2",
            x64=True,
            process_probe=list_pscad_processes,
        )
        service = PscadService(
            lambda: backend,
            executor=robust_executor,
            path_policy=PathPolicy(workspace_root=str(workspace)),
        )

        result = await run_licensed_session_preflight(
            service,
            workspace_root=workspace,
        )

        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["remaining_processes"], [])
