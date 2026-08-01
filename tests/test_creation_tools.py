import unittest
from unittest.mock import patch, AsyncMock

from pscad_mcp.tools.creation_tools import (
    create_case, create_library, save_project, save_project_as,
    build_project, build_all_projects, get_project_definitions,
)


class TestCreationTools(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.patcher_manager = patch("pscad_mcp.tools.creation_tools.pscad_manager")
        self.mock_manager = self.patcher_manager.start()
        self.service = self.mock_manager.service

    def tearDown(self):
        self.patcher_manager.stop()

    async def test_create_case(self):
        self.service.create_project = AsyncMock(
            return_value={"name": "TestProject", "filename": "TestProject.pscx"}
        )
        result = await create_case("TestProject")
        self.assertEqual(result["name"], "TestProject")
        self.service.create_project.assert_awaited_once_with(
            "case", "TestProject", None, confirm=False
        )

    async def test_create_case_with_folder(self):
        self.service.create_project = AsyncMock(return_value={"name": "TestProject"})
        await create_case("TestProject", folder="C:\\projects", confirm=True)
        self.service.create_project.assert_awaited_once_with(
            "case", "TestProject", "C:\\projects", confirm=True
        )

    async def test_create_library(self):
        self.service.create_project = AsyncMock(
            return_value={"name": "TestProject", "filename": "TestLib.pslx"}
        )
        result = await create_library("TestLib")
        self.assertEqual(result["name"], "TestProject")
        self.service.create_project.assert_awaited_once_with(
            "library", "TestLib", None, confirm=False
        )

    async def test_save_project(self):
        self.service.save_project = AsyncMock(return_value="Project saved")
        result = await save_project("TestProject", confirm=True)
        self.assertIn("saved", result)
        self.service.save_project.assert_awaited_once_with(
            "TestProject", confirm=True
        )

    async def test_save_project_as(self):
        self.service.save_project_as = AsyncMock(return_value="saved as")
        result = await save_project_as("TestProject", "NewName.pscx")
        self.assertIn("saved as", result)
        self.service.save_project_as.assert_awaited_once_with(
            "TestProject", "NewName.pscx", None, confirm=False
        )

    async def test_build_project(self):
        self.service.build_project = AsyncMock(return_value="built")
        result = await build_project("TestProject")
        self.assertIn("built", result)
        self.service.build_project.assert_awaited_once_with("TestProject")

    async def test_build_all_projects(self):
        self.service.build_all_projects = AsyncMock(return_value="built")
        result = await build_all_projects()
        self.assertIn("built", result)
        self.service.build_all_projects.assert_awaited_once_with()

    async def test_get_project_definitions(self):
        self.service.get_project_definitions = AsyncMock(
            return_value=["source3", "ground"]
        )
        result = await get_project_definitions("TestProject")
        self.assertEqual(result, ["source3", "ground"])


if __name__ == "__main__":
    unittest.main()
