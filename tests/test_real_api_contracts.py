import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from pscad_mcp.tools.creation_tools import get_project_definitions
from pscad_mcp.tools.project_tools import find_components, validate_component_parameters


class TestRealApiContracts(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.pscad = MagicMock()
        self.project = MagicMock()
        self.component = SimpleNamespace(
            id=7,
            name="V1",
            defn_name="master:source3",
        )
        self.pscad.project.return_value = self.project
        self.project.find_all.return_value = [self.component]
        self.project.definitions.return_value = ["source3", "ground"]

        self.manager_patch = patch("pscad_mcp.tools.project_tools.pscad_manager")
        self.manager = self.manager_patch.start()
        self.manager.pscad = self.pscad
        self.manager.service.find_components = AsyncMock(
            return_value=[
                {"id": 7, "name": "V1", "definition": "master:source3"}
            ]
        )
        self.manager.service.validate_component_parameters = AsyncMock(
            return_value={"Gain": {"valid": False, "range": "(0, 10)"}}
        )
        self.creation_manager_patch = patch(
            "pscad_mcp.tools.creation_tools.pscad_manager"
        )
        self.creation_manager = self.creation_manager_patch.start()
        self.creation_manager.service.get_project_definitions = AsyncMock(
            return_value=["source3", "ground"]
        )
        self.executor_patch = patch(
            "pscad_mcp.tools.project_tools.robust_executor"
        )
        self.executor = self.executor_patch.start()
        self.executor.run_safe = AsyncMock(
            side_effect=lambda func, *args, **kwargs: func(
                *args,
                **{key: value for key, value in kwargs.items() if key != "timeout"},
            )
        )

    def tearDown(self):
        self.manager_patch.stop()
        self.creation_manager_patch.stop()
        self.executor_patch.stop()

    async def test_find_components_uses_defn_name(self):
        result = await find_components("case", definition="source3")

        self.assertEqual(
            result,
            [{"id": 7, "name": "V1", "definition": "master:source3"}],
        )

    async def test_project_definitions_are_strings(self):
        result = await get_project_definitions("case")

        self.assertEqual(result, ["source3", "ground"])

    async def test_parameter_validation_rejects_out_of_range_value(self):
        result = await validate_component_parameters("case", 7, {"Gain": 11})

        self.assertFalse(result["Gain"]["valid"])


if __name__ == "__main__":
    unittest.main()
