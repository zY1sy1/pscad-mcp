import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from pscad_mcp.core.connection_manager import PSCADConnectionManager
from pscad_mcp.tools.app_tools import get_pscad_status


class TestConnectionMetadata(unittest.IsolatedAsyncioTestCase):
    async def test_status_uses_manager_service_metadata(self):
        expected = {
            "connected": True,
            "backend": "legacy",
            "version": "4.6.2",
            "selected_version": "4.6.2",
            "x64": True,
            "alive": True,
            "busy": False,
            "licensed": True,
            "owns_process": True,
        }
        with patch("pscad_mcp.tools.app_tools.pscad_manager") as manager:
            manager.get_status = AsyncMock(return_value=expected)

            result = await get_pscad_status()

        self.assertTrue(result["connected"])
        self.assertEqual(result["backend"], "legacy")
        self.assertEqual(result["selected_version"], "4.6.2")
        self.assertTrue(result["x64"])
        manager.get_status.assert_awaited_once_with()

    def test_raw_pscad_proxy_is_not_exposed(self):
        self.assertFalse(hasattr(PSCADConnectionManager, "pscad"))

    def test_connection_info_serializes_selected_installation(self):
        manager = object.__new__(PSCADConnectionManager)
        manager._adapter = SimpleNamespace(
            owns_process=True,
            selected_installation=("5.0.2", False),
        )

        self.assertEqual(
            manager.connection_info,
            {
                "owns_process": True,
                "selected_version": "5.0.2",
                "x64": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
