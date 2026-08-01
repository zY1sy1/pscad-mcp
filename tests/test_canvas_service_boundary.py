import inspect
import unittest
from unittest.mock import AsyncMock, patch

from pscad_mcp.tools import canvas_tools


class TestCanvasServiceBoundary(unittest.IsolatedAsyncioTestCase):
    def test_canvas_tools_do_not_access_vendor_proxies(self):
        source = inspect.getsource(canvas_tools)
        self.assertNotIn("pscad_manager.pscad", source)
        self.assertNotIn("robust_executor", source)

    async def test_connect_ports_routes_to_service(self):
        with patch.object(canvas_tools, "pscad_manager") as manager:
            manager.service.connect_ports = AsyncMock(
                return_value={"wire_id": 17}
            )

            result = await canvas_tools.connect_ports(
                "case", 1, "A", 2, "B", "Main"
            )

        self.assertEqual(result, {"wire_id": 17})
        manager.service.connect_ports.assert_awaited_once_with(
            "case", 1, "A", 2, "B", canvas_name="Main"
        )


if __name__ == "__main__":
    unittest.main()
