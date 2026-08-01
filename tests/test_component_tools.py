import unittest
from unittest.mock import AsyncMock, patch

from pscad_mcp.core.service import ConfirmationRequired
from pscad_mcp.tools.component_tools import (
    clone_component,
    delete_component,
    disable_component,
    enable_component,
    get_component_location,
    get_component_port,
    get_component_ports,
    mirror_component,
    rotate_component,
    set_component_location,
)


class TestComponentTools(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager_patch = patch("pscad_mcp.tools.component_tools.pscad_manager")
        self.manager = self.manager_patch.start()
        self.service = self.manager.service

    def tearDown(self):
        self.manager_patch.stop()

    async def test_location_tools_route_to_service(self):
        self.service.get_component_location = AsyncMock(
            return_value={"id": 42, "x": 10, "y": 5}
        )
        self.service.set_component_location = AsyncMock(return_value="moved")

        self.assertEqual((await get_component_location("proj", 42))["x"], 10)
        self.assertEqual(await set_component_location("proj", 42, 20, 15), "moved")
        self.service.set_component_location.assert_awaited_once_with(
            "proj", 42, 20, 15
        )

    async def test_rotation_values_route_unchanged(self):
        self.service.rotate_component = AsyncMock(return_value="rotated")
        for direction in ("right", "left", "180"):
            self.assertEqual(
                await rotate_component("proj", 42, direction), "rotated"
            )
        self.assertEqual(self.service.rotate_component.await_count, 3)

    async def test_mirror_values_route_unchanged(self):
        self.service.mirror_component = AsyncMock(return_value="mirrored")
        for axis in ("horizontal", "vertical"):
            self.assertEqual(
                await mirror_component("proj", 42, axis), "mirrored"
            )
        self.assertEqual(self.service.mirror_component.await_count, 2)

    async def test_clone_and_ports_return_normalized_service_values(self):
        self.service.clone_component = AsyncMock(
            return_value={
                "id": 99,
                "name": "V1_copy",
                "definition": "master:source3",
                "location": {"x": 30, "y": 10},
            }
        )
        self.service.get_component_ports = AsyncMock(
            return_value={
                "A": {"name": "A", "x": 12, "y": 5, "dim": 1, "type": "DATA"}
            }
        )
        self.service.get_component_port = AsyncMock(
            return_value={"name": "A", "x": 12, "y": 5, "dim": 1, "type": "DATA"}
        )

        self.assertEqual((await clone_component("proj", 42, 30, 10))["id"], 99)
        self.assertIn("A", await get_component_ports("proj", 42))
        self.assertEqual((await get_component_port("proj", 42, "A"))["name"], "A")

    async def test_enable_and_disable_route_boolean_state(self):
        self.service.set_component_enabled = AsyncMock(
            side_effect=["enabled", "disabled"]
        )

        self.assertEqual(await enable_component("proj", 42), "enabled")
        self.assertEqual(await disable_component("proj", 42), "disabled")
        self.assertEqual(
            self.service.set_component_enabled.await_args_list[0].args,
            ("proj", 42, True),
        )
        self.assertEqual(
            self.service.set_component_enabled.await_args_list[1].args,
            ("proj", 42, False),
        )

    async def test_delete_passes_explicit_confirmation(self):
        self.service.delete_component = AsyncMock(return_value="deleted")

        self.assertEqual(
            await delete_component("proj", 42, confirm=True), "deleted"
        )
        self.service.delete_component.assert_awaited_once_with(
            "proj", 42, confirm=True
        )

    async def test_delete_without_confirmation_propagates_safety_error(self):
        self.service.delete_component = AsyncMock(
            side_effect=ConfirmationRequired("delete_component")
        )

        with self.assertRaises(ConfirmationRequired):
            await delete_component("proj", 42)


if __name__ == "__main__":
    unittest.main()
