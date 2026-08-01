import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import os
from pscad_mcp.tools.project_tools import register_project_tools, run_project, load_projects, find_components
from pscad_mcp.tools.app_tools import register_app_tools, get_pscad_status
from pscad_mcp.core.connection_manager import pscad_manager
from mcp.server.fastmcp import FastMCP

class TestAllTools(unittest.IsolatedAsyncioTestCase):
    """
    Comprehensive tool logic testing covering edge and error cases.
    """

    async def asyncSetUp(self):
        self.mcp = FastMCP("Test")
        # Registering tools is not strictly necessary for unit tests if we call functions directly,
        # but it validates registration logic.
        register_project_tools(self.mcp)
        register_app_tools(self.mcp)
        self.original_service = pscad_manager._service
        self.mock_service = MagicMock()
        pscad_manager._service = self.mock_service

    async def asyncTearDown(self):
        pscad_manager._service = self.original_service

    # --- Connection Tools ---
    
    async def test_get_status_unresponsive(self):
        """Edge case: PSCAD is running but RMI call fails."""
        self.mock_service.status = AsyncMock(side_effect=Exception("COM Error"))
        result = await get_pscad_status()
        self.assertEqual(result["connected"], False)

    # --- Project Tools ---

    async def test_load_nonexistent_project(self):
        """Edge case: Loading a file that doesn't exist on disk."""
        self.mock_service.load_projects = AsyncMock(
            side_effect=FileNotFoundError("File not found")
        )
        with self.assertRaises(Exception): 
             await load_projects(filenames=["C:\\missing.pscx"])

    async def test_run_unlicensed_project(self):
        """Edge case: Attempting simulation without a valid license."""
        self.mock_service.run_project = AsyncMock(
            return_value="Error: PSCAD is not licensed."
        )
        result = await run_project(project_name="test")
        self.assertIn("not licensed", result)

    async def test_find_no_components(self):
        """Edge case: Searching for components that don't exist."""
        self.mock_service.find_components = AsyncMock(return_value=[])
        result = await find_components(project_name="test", name="Ghost")
        self.assertEqual(len(result), 0)

    async def test_invalid_project_name(self):
        """Edge case: Using a project name that isn't loaded."""
        self.mock_service.run_project = AsyncMock(
            side_effect=Exception("Project not found")
        )
        with self.assertRaises(Exception):
             await run_project(project_name="unknown")

if __name__ == "__main__":
    unittest.main()
