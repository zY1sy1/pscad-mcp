import inspect
from pathlib import Path
import unittest

from pscad_mcp.tools.creation_tools import (
    create_case,
    create_library,
    save_project,
    save_project_as,
)
from pscad_mcp.tools.project_tools import (
    get_project_settings,
    get_run_status,
    list_projects,
    load_projects,
    pause_simulation,
    run_project,
    set_project_settings,
    stop_simulation,
)


class TestProjectToolServiceBoundary(unittest.TestCase):
    def test_project_related_tools_do_not_access_vendor_proxies(self):
        root = Path(__file__).parents[1] / "pscad_mcp" / "tools"
        for filename in ("creation_tools.py", "simset_tools.py", "data_tools.py"):
            source = (root / filename).read_text(encoding="utf-8")
            with self.subTest(filename=filename):
                self.assertNotIn("pscad_manager.pscad", source)
                self.assertNotIn("robust_executor", source)
                self.assertNotIn("pscad_manager.adapter", source)

        for function in (
            load_projects,
            list_projects,
            run_project,
            get_run_status,
            pause_simulation,
            stop_simulation,
            get_project_settings,
            set_project_settings,
        ):
            source = inspect.getsource(function)
            with self.subTest(function=function.__name__):
                self.assertNotIn("pscad_manager.pscad", source)
                self.assertNotIn("robust_executor", source)
                self.assertIn("pscad_manager.service", source)

    def test_overwrite_capable_tools_expose_confirmation(self):
        for function in (create_case, create_library, save_project, save_project_as):
            with self.subTest(function=function.__name__):
                parameter = inspect.signature(function).parameters.get("confirm")
                self.assertIsNotNone(parameter)
                self.assertFalse(parameter.default)


if __name__ == "__main__":
    unittest.main()
