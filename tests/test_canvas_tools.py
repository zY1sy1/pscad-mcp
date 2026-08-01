import unittest
from unittest.mock import AsyncMock, patch

from pscad_mcp.tools import canvas_tools


class TestCanvasTools(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.patcher = patch.object(canvas_tools, "pscad_manager")
        self.manager = self.patcher.start()
        self.service = self.manager.service

    def tearDown(self):
        self.patcher.stop()

    async def test_add_component(self):
        self.service.add_canvas_component = AsyncMock(return_value={"id": 42})
        result = await canvas_tools.add_component(
            "proj", "master", "source3", 10, 5, 1, {"V": 230}, "Main"
        )
        self.assertEqual(result, {"id": 42})
        self.service.add_canvas_component.assert_awaited_once_with(
            "proj", "master", "source3", 10, 5, 1, {"V": 230},
            canvas_name="Main",
        )

    async def test_create_component(self):
        self.service.create_canvas_component = AsyncMock(return_value={"id": 43})
        result = await canvas_tools.create_component(
            "proj", "master:source3", 10, 5, 0, None, "Main"
        )
        self.assertEqual(result, {"id": 43})
        self.service.create_canvas_component.assert_awaited_once_with(
            "proj", "master:source3", 10, 5, 0, None, canvas_name="Main"
        )

    async def test_create_wire(self):
        self.service.create_wire = AsyncMock(return_value={"id": 100})
        vertices = [[1, 1], [2, 1], [3, 3]]
        self.assertEqual(
            await canvas_tools.create_wire("proj", vertices), {"id": 100}
        )
        self.service.create_wire.assert_awaited_once_with(
            "proj", vertices, canvas_name="Main"
        )

    async def test_create_bus(self):
        self.service.create_bus = AsyncMock(return_value={"id": 200})
        vertices = [[1, 1], [10, 1]]
        result = await canvas_tools.create_bus(
            "proj", vertices, {"BaseKV": 138.0}
        )
        self.assertEqual(result, {"id": 200})
        self.service.create_bus.assert_awaited_once_with(
            "proj", vertices, {"BaseKV": 138.0}, canvas_name="Main"
        )

    async def test_create_connection(self):
        self.service.create_connection = AsyncMock(return_value={"label": "NodeA"})
        result = await canvas_tools.create_connection(
            "proj", [10, 5], [20, 5], "NodeA", True
        )
        self.assertEqual(result, {"label": "NodeA"})
        self.service.create_connection.assert_awaited_once_with(
            "proj", [10, 5], [20, 5], "NodeA", True, canvas_name="Main"
        )

    async def test_connect_ports(self):
        self.service.connect_ports = AsyncMock(return_value={"wire_id": 300})
        result = await canvas_tools.connect_ports("proj", 1, "Out", 2, "In")
        self.assertEqual(result, {"wire_id": 300})

    async def test_create_annotation(self):
        self.service.create_annotation = AsyncMock(return_value={"id": 500})
        result = await canvas_tools.create_annotation(
            "proj", 5, 5, "Line 1", "Line 2"
        )
        self.assertEqual(result, {"id": 500})

    async def test_create_graph_frame(self):
        self.service.create_graph_frame = AsyncMock(return_value={"id": 600})
        self.assertEqual(
            await canvas_tools.create_graph_frame("proj", 5, 10), {"id": 600}
        )

    async def test_create_control_frame(self):
        expected = {"frame_id": 700, "control_ids": []}
        self.service.create_control_frame = AsyncMock(return_value=expected)
        self.assertEqual(
            await canvas_tools.create_control_frame("proj", 5, 10), expected
        )

    async def test_list_canvas_components(self):
        expected = [{"id": 1}, {"id": 2}]
        self.service.list_canvas_components = AsyncMock(return_value=expected)
        self.assertEqual(await canvas_tools.list_canvas_components("proj"), expected)

    async def test_find_empty_space(self):
        expected = {"x": 15, "y": 15, "width": 10, "height": 8}
        self.service.find_empty_space = AsyncMock(return_value=expected)
        self.assertEqual(
            await canvas_tools.find_empty_space("proj", 10, 8, 10, 10),
            expected,
        )

    async def test_delete_components(self):
        self.service.delete_components = AsyncMock(
            return_value="Deleted 2 component(s)."
        )
        result = await canvas_tools.delete_components(
            "proj", [1, 2], confirm=True
        )
        self.assertIn("2", result)
        self.service.delete_components.assert_awaited_once_with(
            "proj", [1, 2], confirm=True
        )


if __name__ == "__main__":
    unittest.main()
