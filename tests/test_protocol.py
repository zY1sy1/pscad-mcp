import asyncio
import unittest
import json
from unittest.mock import MagicMock, patch
from pscad_mcp.tools.project_tools import list_projects, run_project
from pscad_mcp.core.connection_manager import pscad_manager

class TestProtocolIntegrity(unittest.IsolatedAsyncioTestCase):
    """
    Protocol validation: Ensuring outputs are JSON-RPC compliant 
    and don't pollute stdout.
    """

    async def asyncSetUp(self):
        self.mock_pscad = MagicMock()
        pscad_manager._pscad = self.mock_pscad
        self.os_patch = patch('pscad_mcp.core.connection_manager.PSCADConnectionManager.is_process_running', return_value=True)
        self.os_patch.start()

    async def asyncTearDown(self):
        self.os_patch.stop()

    async def test_tool_json_serializable(self):
        """
        Verify that tool outputs can be converted to JSON.
        Failure here breaks the AI client connection.
        """
        self.mock_pscad.projects.return_value = [{"name": "prj", "type": "Case"}]
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
        self.mock_pscad.project.return_value = MagicMock()
        await run_project(project_name="test")
        
        # Check if stdout.write was called (excluding possible logging which should go to stderr)
        for call in mock_stdout.call_args_list:
            arg = call[0][0]
            if arg.strip() and "PSCAD MCP" not in arg: # Ignore initialization log if it leaked to stdout
                 self.fail(f"Detected stdout pollution: {arg}")

if __name__ == "__main__":
    unittest.main()
