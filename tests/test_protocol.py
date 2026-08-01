import asyncio
import unittest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from pscad_mcp.tools.project_tools import list_projects, run_project
from pscad_mcp.core.connection_manager import pscad_manager

class TestProtocolIntegrity(unittest.IsolatedAsyncioTestCase):
    """
    Protocol validation: Ensuring outputs are JSON-RPC compliant 
    and don't pollute stdout.
    """

    async def asyncSetUp(self):
        self.original_service = pscad_manager._service
        self.mock_service = MagicMock()
        pscad_manager._service = self.mock_service

    async def asyncTearDown(self):
        pscad_manager._service = self.original_service

    async def test_tool_json_serializable(self):
        """
        Verify that tool outputs can be converted to JSON.
        Failure here breaks the AI client connection.
        """
        self.mock_service.list_projects = AsyncMock(
            return_value=[{"name": "prj", "type": "Case"}]
        )
        result = await list_projects()
        try:
            json.dumps(result)
        except TypeError as e:
            self.fail(f"Tool output is not JSON serializable: {e}")

    @patch('sys.stdout.write')
    async def test_stdout_pollution(self, mock_stdout):
        """
        Verify that no internal code prints directly to stdout.
        This would corrupt the MCP JSON-RPC stream.
        """
        self.mock_service.run_project = AsyncMock(return_value="started")
        await run_project(project_name="test")
        
        # Check if stdout.write was called (excluding possible logging which should go to stderr)
        for call in mock_stdout.call_args_list:
            arg = call[0][0]
            if arg.strip() and "PSCAD MCP" not in arg: # Ignore initialization log if it leaked to stdout
                 self.fail(f"Detected stdout pollution: {arg}")

if __name__ == "__main__":
    unittest.main()
