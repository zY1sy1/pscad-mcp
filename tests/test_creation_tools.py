import unittest
from unittest.mock import MagicMock, patch, AsyncMock

from pscad_mcp.tools.creation_tools import (
    create_case, create_library, save_project, save_project_as,
    build_project, build_all_projects, get_project_definitions,
)


class TestCreationTools(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_pscad = MagicMock()
        self.mock_project = MagicMock()
        self.mock_project.name = "TestProject"
        self.mock_project.filename = "TestProject.pscx"

        self.patcher_manager = patch("pscad_mcp.tools.creation_tools.pscad_manager")
        self.patcher_executor = patch("pscad_mcp.tools.creation_tools.robust_executor")
        self.mock_manager = self.patcher_manager.start()
        self.mock_executor = self.patcher_executor.start()

        self.mock_manager.pscad = self.mock_pscad
        self.mock_executor.run_safe = AsyncMock(
            side_effect=lambda f, *args, **kwargs: f(*args, **{k: v for k, v in kwargs.items() if k != "timeout"})
        )

    def tearDown(self):
        self.patcher_manager.stop()
        self.patcher_executor.stop()

    async def test_create_case(self):
        self.mock_pscad.create_case.return_value = self.mock_project
        result = await create_case("TestProject")
        self.assertEqual(result["name"], "TestProject")
        self.mock_pscad.create_case.assert_called_once_with(filename="TestProject")

    async def test_create_case_with_folder(self):
        self.mock_pscad.create_case.return_value = self.mock_project
        result = await create_case("TestProject", folder="C:\\projects")
        self.mock_pscad.create_case.assert_called_once_with(filename="TestProject", folder="C:\\projects")

    async def test_create_library(self):
        self.mock_pscad.create_library.return_value = self.mock_project
        self.mock_project.filename = "TestLib.pslx"
        result = await create_library("TestLib")
        self.assertEqual(result["name"], "TestProject")
        self.mock_pscad.create_library.assert_called_once_with(filename="TestLib")

    async def test_save_project(self):
        self.mock_pscad.project.return_value = self.mock_project
        result = await save_project("TestProject")
        self.assertIn("saved", result)
        self.mock_project.save.assert_called_once()

    async def test_save_project_as(self):
        self.mock_pscad.project.return_value = self.mock_project
        result = await save_project_as("TestProject", "NewName.pscx")
        self.assertIn("saved as", result)
        self.mock_project.save_as.assert_called_once_with(filename="NewName.pscx")

    async def test_build_project(self):
        self.mock_pscad.project.return_value = self.mock_project
        result = await build_project("TestProject")
        self.assertIn("built", result)
        self.mock_project.build.assert_called_once()

    async def test_build_all_projects(self):
        result = await build_all_projects()
        self.assertIn("built", result)
        self.mock_pscad.build_all.assert_called_once()

    async def test_get_project_definitions(self):
        mock_def1 = MagicMock()
        mock_def1.name = "source3"
        mock_def2 = MagicMock()
        mock_def2.name = "ground"
        self.mock_pscad.project.return_value = self.mock_project
        self.mock_project.definitions.return_value = [mock_def1, mock_def2]
        result = await get_project_definitions("TestProject")
        self.assertEqual(result, ["source3", "ground"])


if __name__ == "__main__":
    unittest.main()
