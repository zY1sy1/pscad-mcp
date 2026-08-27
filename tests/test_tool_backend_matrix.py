import inspect
from pathlib import Path
import unittest

from pscad_mcp.core.backend.base import PscadBackend
from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.backend.modern import ModernBackend
from pscad_mcp.core.connection_manager import PSCADConnectionManager
from pscad_mcp.main import create_server
from pscad_mcp.tools.catalog import FULL_TOOL_NAMES
from tests.backend_fakes import ImmediateExecutor


class TestToolBackendMatrix(unittest.TestCase):
    def test_generic_and_hvdc_tool_registration(self):
        names = {
            tool.name for tool in create_server()._tool_manager.list_tools()
        }
        self.assertEqual(names, FULL_TOOL_NAMES)

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
