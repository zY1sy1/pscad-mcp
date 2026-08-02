import unittest
from unittest.mock import AsyncMock, patch

from pscad_mcp.core.service import ConfirmationRequired
from pscad_mcp.tools.app_tools import (
    get_local_pscad,
    get_pscad_status,
    quit_pscad,
    repair_connection,
)


class TestApplicationToolServiceRouting(unittest.IsolatedAsyncioTestCase):
    async def test_get_local_pscad_routes_to_manager_service(self):
        with patch("pscad_mcp.tools.app_tools.pscad_manager") as manager:
            manager.attach_local = AsyncMock(return_value="attached")

            self.assertEqual(await get_local_pscad(), "attached")

        manager.attach_local.assert_awaited_once_with()

    async def test_status_returns_manager_normalized_status(self):
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

        self.assertEqual(result, expected)
        manager.get_status.assert_awaited_once_with()

    async def test_status_failure_includes_executor_diagnostics(self):
        diagnostics = {
            "healthy": False,
            "last_operation": "is_alive",
            "last_error": "ExecutorTimeoutError: timed out",
            "last_timeout_seconds": 30,
        }
        with patch("pscad_mcp.tools.app_tools.pscad_manager") as manager:
            manager.get_status = AsyncMock(side_effect=RuntimeError("offline"))
            manager.service.executor_status.return_value = diagnostics
            manager.error_payload.return_value = {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "offline",
                }
            }

            result = await get_pscad_status()

        self.assertFalse(result["connected"])
        self.assertEqual(result["executor"], diagnostics)
        self.assertEqual(result["error"]["code"], "INTERNAL_ERROR")

    async def test_repair_routes_to_manager_service(self):
        with patch("pscad_mcp.tools.app_tools.pscad_manager") as manager:
            manager.repair_connection = AsyncMock(return_value="repaired")

            self.assertEqual(await repair_connection(), "repaired")

        manager.repair_connection.assert_awaited_once_with()

    async def test_quit_passes_confirmation_to_manager_service(self):
        with patch("pscad_mcp.tools.app_tools.pscad_manager") as manager:
            manager.quit_pscad = AsyncMock(return_value="PSCAD terminated.")

            result = await quit_pscad(confirm=True)

        self.assertEqual(result, "PSCAD terminated.")
        manager.quit_pscad.assert_awaited_once_with(confirm=True)

    async def test_confirmation_error_is_returned_as_stable_error(self):
        error = ConfirmationRequired("quit_pscad")
        with patch("pscad_mcp.tools.app_tools.pscad_manager") as manager:
            manager.quit_pscad = AsyncMock(side_effect=error)
            manager.error_payload.return_value = {"error": error.to_dict()}

            result = await quit_pscad(confirm=False)

        self.assertEqual(result["error"]["code"], "CONFIRMATION_REQUIRED")
        manager.error_payload.assert_called_once_with(error, "quit_pscad")


if __name__ == "__main__":
    unittest.main()
