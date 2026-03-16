import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from collections import namedtuple

from pscad_mcp.tools.canvas_tools import (
    add_component, create_component, create_wire, create_bus,
    create_connection, connect_ports, create_annotation,
    create_graph_frame, create_control_frame, list_canvas_components,
    find_empty_space, delete_components,
)

Port = namedtuple("Port", ["x", "y", "name", "dim", "type"])


class TestCanvasTools(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_pscad = MagicMock()
        self.mock_project = MagicMock()
        self.mock_canvas = MagicMock()
        self.mock_component = MagicMock()

        # Default component attributes
        self.mock_component.id = 42
        self.mock_component.name = "V1"
        self.mock_component.defn_name = "master:source3"
        self.mock_component.location = (10, 5)

        self.patcher_manager = patch("pscad_mcp.tools.canvas_tools.pscad_manager")
        self.patcher_executor = patch("pscad_mcp.tools.canvas_tools.robust_executor")
        self.mock_manager = self.patcher_manager.start()
        self.mock_executor = self.patcher_executor.start()

        self.mock_manager.pscad = self.mock_pscad
        self.mock_pscad.project.return_value = self.mock_project
        self.mock_project.canvas.return_value = self.mock_canvas

        self.mock_executor.run_safe = AsyncMock(
            side_effect=lambda f, *args, **kwargs: f(*args, **{k: v for k, v in kwargs.items() if k != "timeout"})
        )

    def tearDown(self):
        self.patcher_manager.stop()
        self.patcher_executor.stop()

    async def test_add_component(self):
        self.mock_canvas.add_component.return_value = self.mock_component
        result = await add_component("proj", "master", "source3", 10, 5)
        self.assertEqual(result["id"], 42)
        self.assertEqual(result["name"], "V1")
        self.mock_canvas.add_component.assert_called_once_with("master", "source3", 10, 5, 0)

    async def test_create_component(self):
        self.mock_canvas.create_component.return_value = self.mock_component
        result = await create_component("proj", "master:source3", 10, 5)
        self.assertEqual(result["id"], 42)
        self.assertEqual(result["definition"], "master:source3")
        self.mock_canvas.create_component.assert_called_once_with("master:source3", 10, 5, 0)

    async def test_create_component_with_parameters(self):
        self.mock_canvas.create_component.return_value = self.mock_component
        result = await create_component("proj", "master:source3", 10, 5, parameters={"V": 230})
        self.mock_canvas.create_component.assert_called_once_with("master:source3", 10, 5, 0, V=230)

    async def test_create_wire(self):
        mock_wire = MagicMock()
        mock_wire.id = 100
        mock_ep1 = MagicMock(x=10, y=5)
        mock_ep2 = MagicMock(x=20, y=5)
        mock_wire.endpoints.return_value = (mock_ep1, mock_ep2)
        self.mock_canvas.create_wire.return_value = mock_wire
        result = await create_wire("proj", [[10, 5], [20, 5]])
        self.assertEqual(result["id"], 100)
        self.assertEqual(result["endpoints"], [[10, 5], [20, 5]])
        self.mock_canvas.create_wire.assert_called_once_with((10, 5), (20, 5))

    async def test_create_wire_multi_vertex(self):
        mock_wire = MagicMock()
        mock_wire.id = 101
        mock_wire.endpoints.return_value = (MagicMock(x=1, y=1), MagicMock(x=3, y=3))
        self.mock_canvas.create_wire.return_value = mock_wire
        await create_wire("proj", [[1, 1], [2, 1], [3, 3]])
        self.mock_canvas.create_wire.assert_called_once_with((1, 1), (2, 1), (3, 3))

    async def test_create_bus(self):
        mock_bus = MagicMock()
        mock_bus.id = 200
        mock_bus.name = "Bus1"
        self.mock_canvas.create_bus.return_value = mock_bus
        result = await create_bus("proj", [[1, 1], [10, 1]])
        self.assertEqual(result["id"], 200)
        self.assertEqual(result["name"], "Bus1")

    async def test_create_bus_with_parameters(self):
        mock_bus = MagicMock()
        mock_bus.id = 201
        mock_bus.name = "Bus2"
        self.mock_canvas.create_bus.return_value = mock_bus
        await create_bus("proj", [[1, 1], [10, 1]], parameters={"BaseKV": 138.0})
        mock_bus.parameters.assert_called_once_with(parameters={"BaseKV": 138.0})

    async def test_create_connection_wire(self):
        self.mock_canvas.create_connection.return_value = None
        result = await create_connection("proj", [10, 5], [20, 5])
        self.assertTrue(result["connected"])

    async def test_create_connection_label(self):
        self.mock_canvas.create_connection.return_value = "NodeA"
        result = await create_connection("proj", [10, 5], [20, 5], label="NodeA", electrical=True)
        self.assertEqual(result["label"], "NodeA")

    async def test_connect_ports(self):
        port1 = Port(x=12, y=5, name="Out", dim=1, type="DATA")
        port2 = Port(x=20, y=5, name="In", dim=1, type="DATA")
        comp1 = MagicMock()
        comp1.port.return_value = port1
        comp2 = MagicMock()
        comp2.port.return_value = port2

        self.mock_canvas.component.side_effect = lambda iid: comp1 if iid == 1 else comp2

        mock_wire = MagicMock()
        mock_wire.id = 300
        self.mock_canvas.create_wire.return_value = mock_wire

        result = await connect_ports("proj", 1, "Out", 2, "In")
        self.assertEqual(result["wire_id"], 300)
        self.assertEqual(result["from"]["x"], 12)
        self.assertEqual(result["to"]["x"], 20)
        self.mock_canvas.create_wire.assert_called_once_with((12, 5), (20, 5))

    async def test_connect_ports_invalid_port(self):
        comp1 = MagicMock()
        comp1.port.return_value = None
        self.mock_canvas.component.return_value = comp1
        with self.assertRaises(ValueError):
            await connect_ports("proj", 1, "BadPort", 2, "In")

    async def test_create_annotation(self):
        mock_ann = MagicMock()
        mock_ann.id = 500
        mock_ann.name = None
        mock_ann.defn_name = "Annotation"
        mock_ann.location = (5, 5)
        self.mock_canvas.create_annotation.return_value = mock_ann
        result = await create_annotation("proj", 5, 5, "Line 1", "Line 2")
        self.assertEqual(result["id"], 500)

    async def test_create_graph_frame(self):
        mock_gf = MagicMock()
        mock_gf.id = 600
        self.mock_canvas.create_graph_frame.return_value = mock_gf
        result = await create_graph_frame("proj", 5, 10)
        self.assertEqual(result["id"], 600)

    async def test_create_control_frame(self):
        mock_frame = MagicMock()
        mock_frame.id = 700
        mock_ctrl = MagicMock()
        mock_ctrl.id = 701
        self.mock_canvas.create_control_frame.return_value = (mock_frame, [mock_ctrl])
        result = await create_control_frame("proj", 5, 10)
        self.assertEqual(result["frame_id"], 700)
        self.assertEqual(result["control_ids"], [701])

    async def test_list_canvas_components(self):
        c1 = MagicMock(id=1, defn_name="master:source3", location=(10, 5))
        c1.configure_mock(name="V1")
        c2 = MagicMock(id=2, defn_name="master:resistor", location=(20, 5))
        c2.configure_mock(name="R1")
        self.mock_canvas.components.return_value = [c1, c2]
        result = await list_canvas_components("proj")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], 1)
        self.assertEqual(result[1]["name"], "R1")

    async def test_list_canvas_components_empty(self):
        self.mock_canvas.components.return_value = []
        result = await list_canvas_components("proj")
        self.assertEqual(result, [])

    async def test_find_empty_space(self):
        mock_rect = MagicMock(x=15, y=15, width=10, height=8)
        self.mock_canvas.closest_empty_rect.return_value = mock_rect
        result = await find_empty_space("proj", 10, 8, near_x=10, near_y=10)
        self.assertEqual(result["x"], 15)
        self.assertEqual(result["width"], 10)

    async def test_delete_components(self):
        c1 = MagicMock()
        c2 = MagicMock()
        self.mock_canvas.component.side_effect = lambda iid: c1 if iid == 1 else c2
        result = await delete_components("proj", [1, 2])
        self.assertIn("2", result)
        self.mock_canvas.delete.assert_called_once_with(c1, c2)


if __name__ == "__main__":
    unittest.main()
