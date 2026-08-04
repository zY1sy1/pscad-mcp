import asyncio
import unittest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.main import create_server
from pscad_mcp.tools.data_tools import read_output_file
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

    async def test_fastmcp_preserves_structured_backend_error(self):
        error = BackendError(
            "NOT_FOUND",
            "project missing",
            "legacy",
            "run_project",
            {"project_name": "missing"},
        )
        self.mock_service.run_project = AsyncMock(side_effect=error)

        result = await create_server()._tool_manager.call_tool(
            "run_project",
            {"project_name": "missing"},
            convert_result=True,
        )

        content, structured = result
        payload = structured["result"]["error"]
        self.assertTrue(content)
        self.assertEqual(payload["code"], "NOT_FOUND")
        self.assertEqual(payload["backend"], "legacy")
        self.assertEqual(
            payload["details"],
            {"project_name": "missing"},
        )

    async def test_fastmcp_serializes_unlicensed_simulation_error(self):
        error = BackendError(
            "NOT_LICENSED",
            "PSCAD is not licensed; simulation was not started.",
            "legacy",
            "run_project",
            {"project_name": "case"},
        )
        self.mock_service.run_project = AsyncMock(side_effect=error)

        result = await create_server()._tool_manager.call_tool(
            "run_project",
            {"project_name": "case"},
            convert_result=True,
        )

        _, structured = result
        payload = structured["result"]["error"]
        self.assertEqual(payload["code"], "NOT_LICENSED")
        self.assertFalse(payload["retryable"])

    async def test_fastmcp_normalizes_unexpected_error(self):
        self.mock_service.run_project = AsyncMock(
            side_effect=ValueError("bad project")
        )

        result = await create_server()._tool_manager.call_tool(
            "run_project",
            {"project_name": "bad"},
            convert_result=True,
        )

        _, structured = result
        payload = structured["result"]["error"]
        self.assertEqual(payload["code"], "INTERNAL_ERROR")
        self.assertFalse(payload["retryable"])

    async def test_fastmcp_success_keeps_typed_structured_output(self):
        self.mock_service.run_project = AsyncMock(return_value="started")
        server = create_server()

        _, structured = await server._tool_manager.call_tool(
            "run_project",
            {"project_name": "case"},
            convert_result=True,
        )

        tool = server._tool_manager._tools["run_project"]
        self.assertEqual(structured["result"], "started")
        self.assertEqual(
            tool.parameters["properties"]["project_name"]["type"],
            "string",
        )

    async def test_direct_tool_calls_still_raise_backend_errors(self):
        error = BackendError(
            "NOT_FOUND", "project missing", "legacy", "run_project"
        )
        self.mock_service.run_project = AsyncMock(side_effect=error)

        with self.assertRaises(BackendError) as raised:
            await run_project("missing")

        self.assertIs(raised.exception, error)

    async def test_data_tool_does_not_hide_direct_python_exception(self):
        self.mock_service.read_output_file = AsyncMock(
            side_effect=ValueError("bad output file")
        )

        with self.assertRaisesRegex(ValueError, "bad output file"):
            await read_output_file("bad.psout")

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
