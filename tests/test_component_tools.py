import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from collections import namedtuple

from pscad_mcp.tools.component_tools import (
    get_component_location, set_component_location, rotate_component,
    mirror_component, clone_component, get_component_ports,
    get_component_port, enable_component, disable_component, delete_component,
)

Port = namedtuple("Port", ["x", "y", "name", "dim", "type"])


class TestComponentTools(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_pscad = MagicMock()
        self.mock_project = MagicMock()
        self.mock_component = MagicMock()
        self.mock_component.id = 42
        self.mock_component.name = "V1"
        self.mock_component.defn_name = "master:source3"
        self.mock_component.location = (10, 5)

        self.patcher_manager = patch("pscad_mcp.tools.component_tools.pscad_manager")
        self.patcher_executor = patch("pscad_mcp.tools.component_tools.robust_executor")
        self.mock_manager = self.patcher_manager.start()
        self.mock_executor = self.patcher_executor.start()

        self.mock_manager.pscad = self.mock_pscad
        self.mock_pscad.project.return_value = self.mock_project
        self.mock_project.component.return_value = self.mock_component

        self.mock_executor.run_safe = AsyncMock(
            side_effect=lambda f, *args, **kwargs: f(*args, **{k: v for k, v in kwargs.items() if k != "timeout"})
        )

    def tearDown(self):
        self.patcher_manager.stop()
        self.patcher_executor.stop()

    async def test_get_component_location(self):
        self.mock_component.get_location.return_value = (10, 5)
        result = await get_component_location("proj", 42)
        self.assertEqual(result["x"], 10)
        self.assertEqual(result["y"], 5)
        self.assertEqual(result["id"], 42)

    async def test_set_component_location(self):
        result = await set_component_location("proj", 42, 20, 15)
        self.assertIn("moved", result)
        self.mock_component.set_location.assert_called_once_with(20, 15)

    async def test_rotate_component_right(self):
        result = await rotate_component("proj", 42, "right")
        self.assertIn("rotated", result)
        self.mock_component.rotate_right.assert_called_once()

    async def test_rotate_component_left(self):
        await rotate_component("proj", 42, "left")
        self.mock_component.rotate_left.assert_called_once()

    async def test_rotate_component_180(self):
        await rotate_component("proj", 42, "180")
        self.mock_component.rotate_180.assert_called_once()

    async def test_rotate_component_invalid(self):
        with self.assertRaises(ValueError):
            await rotate_component("proj", 42, "upside_down")

    async def test_mirror_horizontal(self):
        result = await mirror_component("proj", 42, "horizontal")
        self.assertIn("mirrored", result)
        self.mock_component.mirror.assert_called_once()

    async def test_mirror_vertical(self):
        await mirror_component("proj", 42, "vertical")
        self.mock_component.flip.assert_called_once()

    async def test_mirror_invalid(self):
        with self.assertRaises(ValueError):
            await mirror_component("proj", 42, "diagonal")

    async def test_clone_component(self):
        new_comp = MagicMock()
        new_comp.id = 99
        new_comp.name = "V1_copy"
        new_comp.defn_name = "master:source3"
        new_comp.location = (30, 10)
        self.mock_component.clone.return_value = new_comp
        result = await clone_component("proj", 42, 30, 10)
        self.assertEqual(result["id"], 99)
        self.mock_component.clone.assert_called_once_with(30, 10)

    async def test_get_component_ports(self):
        port_a = Port(x=12, y=5, name="A", dim=1, type="ELECTRICAL")
        port_b = Port(x=12, y=9, name="B", dim=1, type="ELECTRICAL")
        self.mock_component.ports.return_value = {"A": port_a, "B": port_b}
        result = await get_component_ports("proj", 42)
        self.assertIn("A", result)
        self.assertEqual(result["A"]["x"], 12)
        self.assertEqual(result["B"]["y"], 9)
        self.assertEqual(result["A"]["type"], "ELECTRICAL")

    async def test_get_component_port(self):
        port = Port(x=12, y=5, name="A", dim=1, type="DATA")
        self.mock_component.port.return_value = port
        result = await get_component_port("proj", 42, "A")
        self.assertEqual(result["x"], 12)
        self.assertEqual(result["name"], "A")

    async def test_get_component_port_not_found(self):
        self.mock_component.port.return_value = None
        with self.assertRaises(ValueError):
            await get_component_port("proj", 42, "BadPort")

    async def test_enable_component(self):
        result = await enable_component("proj", 42)
        self.assertIn("enabled", result)
        self.mock_component.enable.assert_called_once()

    async def test_disable_component(self):
        result = await disable_component("proj", 42)
        self.assertIn("disabled", result)
        self.mock_component.disable.assert_called_once()

    async def test_delete_component(self):
        result = await delete_component("proj", 42)
        self.assertIn("deleted", result)
        self.mock_component.delete.assert_called_once()


if __name__ == "__main__":
    unittest.main()
