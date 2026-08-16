import inspect
from pathlib import Path
import unittest

from pscad_mcp.core.backend.base import PscadBackend
from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.backend.modern import ModernBackend
from pscad_mcp.core.connection_manager import PSCADConnectionManager
from pscad_mcp.main import create_server
from tests.backend_fakes import ImmediateExecutor


EXPECTED_TOOLS = {
    "get_local_pscad", "get_pscad_status", "sync_documentation",
    "list_documentation", "read_documentation", "repair_connection",
    "quit_pscad", "load_projects", "list_projects", "run_project",
    "get_run_status", "find_components", "get_component_parameters",
    "set_component_parameters", "validate_component_parameters",
    "pause_simulation", "stop_simulation", "get_project_settings",
    "set_project_settings", "get_project_output", "read_output_file",
    "list_simulation_sets", "run_simulation_set", "add_task_to_set",
    "create_simulation_set", "remove_simulation_set",
    "list_simulation_set_tasks", "remove_tasks_from_set",
    "get_simulation_task_parameters", "set_simulation_task_parameters",
    "get_simulation_set_details",
    "create_case", "create_library", "save_project", "save_project_as",
    "build_project", "build_all_projects", "get_project_definitions",
    "add_component", "create_component", "create_wire", "create_bus",
    "create_connection", "connect_ports", "create_annotation",
    "create_graph_frame", "create_control_frame", "list_canvas_components",
    "find_empty_space", "delete_components", "get_component_location",
    "set_component_location", "rotate_component", "mirror_component",
    "clone_component", "get_component_ports", "get_component_port",
    "enable_component", "disable_component", "delete_component",
    "inspect_hvdc_project", "get_hvdc_assets", "get_hvdc_mappings",
    "validate_hvdc_project", "run_hvdc_scenario", "get_hvdc_scenario_status",
    "analyze_hvdc_results", "compare_hvdc_scenarios", "list_hvdc_profiles",
    "register_hvdc_profile",
}


class TestToolBackendMatrix(unittest.TestCase):
    def test_generic_and_hvdc_tool_registration(self):
        names = {
            tool.name for tool in create_server()._tool_manager.list_tools()
        }
        self.assertEqual(names, EXPECTED_TOOLS)
        self.assertEqual(len(names), 70)

    def test_both_backends_implement_complete_protocol(self):
        legacy = LegacyBackend(
            ImmediateExecutor(), version="4.6.2", x64=True,
            automation_module=False,
        )
        modern = ModernBackend(
            ImmediateExecutor(), version="5.0.2", x64=True,
            pscad_module=False, psout_module=False,
        )
        self.assertIsInstance(legacy, PscadBackend)
        self.assertIsInstance(modern, PscadBackend)

    def test_tool_modules_do_not_access_vendor_or_raw_pscad_proxies(self):
        tools_directory = Path(inspect.getfile(create_server)).parent / "tools"
        for path in tools_directory.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("mhrc.automation", source)
                self.assertNotIn("import mhi.pscad", source)
                self.assertNotIn("pscad_manager.pscad", source)

    def test_connection_manager_does_not_expose_raw_pscad_proxy(self):
        self.assertFalse(hasattr(PSCADConnectionManager, "pscad"))

    def test_documentation_describes_simulation_set_management(self):
        root = Path(__file__).parents[1]
        english = (root / "README.md").read_text(encoding="utf-8")
        chinese = (root / "docs" / "zh-CN" / "README.md").read_text(encoding="utf-8")
        for text in (english, chinese):
            self.assertIn("60", text)
            self.assertIn("create_simulation_set", text)
            self.assertIn("remove_tasks_from_set", text)
        self.assertIn("workspace-level", english)
        self.assertIn("工作区级", chinese)


if __name__ == "__main__":
    unittest.main()
