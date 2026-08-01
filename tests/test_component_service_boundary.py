import inspect
from pathlib import Path
import unittest

from pscad_mcp.tools.canvas_tools import delete_components
from pscad_mcp.tools.component_tools import delete_component
from pscad_mcp.tools.project_tools import (
    find_components,
    get_component_parameters,
    set_component_parameters,
    validate_component_parameters,
)


class TestComponentServiceBoundary(unittest.TestCase):
    def test_component_tools_use_service_only(self):
        root = Path(__file__).parents[1] / "pscad_mcp" / "tools"
        source = (root / "component_tools.py").read_text(encoding="utf-8")
        self.assertNotIn("pscad_manager.pscad", source)
        self.assertNotIn("robust_executor", source)

        for function in (
            find_components,
            get_component_parameters,
            set_component_parameters,
            validate_component_parameters,
        ):
            function_source = inspect.getsource(function)
            with self.subTest(function=function.__name__):
                self.assertNotIn("pscad_manager.pscad", function_source)
                self.assertNotIn("robust_executor", function_source)
                self.assertIn("pscad_manager.service", function_source)

    def test_deletion_tools_require_explicit_confirmation(self):
        for function in (delete_component, delete_components):
            with self.subTest(function=function.__name__):
                parameter = inspect.signature(function).parameters.get("confirm")
                self.assertIsNotNone(parameter)
                self.assertFalse(parameter.default)


if __name__ == "__main__":
    unittest.main()
