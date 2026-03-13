import pscad_mcp_server
import unittest
from unittest.mock import MagicMock, patch

class TestPSCADMCP(unittest.TestCase):
    """
    Unit tests for PSCAD MCP server tools.
    Note: These tests mock the mhi.pscad library to verify the tool logic.
    Actual system testing must be done on a Windows machine with PSCAD installed.
    """
    
    @patch('mhi.pscad.launch')
    def test_launch_pscad(self, mock_launch):
        mock_instance = MagicMock()
        mock_instance.version = "5.0.0"
        mock_launch.return_value = mock_instance
        
        result = pscad_mcp_server.launch_pscad(version="5.0.0")
        self.assertIn("PSCAD 5.0.0 launched successfully.", result)
        self.assertEqual(pscad_mcp_server.pscad_instance, mock_instance)

    @patch('pscad_mcp_server.get_pscad')
    def test_list_projects(self, mock_get_pscad):
        mock_pscad = MagicMock()
        mock_pscad.projects.return_value = [{"name": "test_prj", "type": "Case"}]
        mock_get_pscad.return_value = mock_pscad
        
        result = pscad_mcp_server.list_projects()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "test_prj")

    @patch('pscad_mcp_server.get_pscad')
    def test_run_project(self, mock_get_pscad):
        mock_pscad = MagicMock()
        mock_project = MagicMock()
        mock_pscad.project.return_value = mock_project
        mock_get_pscad.return_value = mock_pscad
        
        result = pscad_mcp_server.run_project("test_prj")
        self.assertIn("Project 'test_prj' run initiated.", result)
        mock_project.run.assert_called_once()

if __name__ == "__main__":
    print("Running mock tests...")
    unittest.main()
