import unittest
from unittest.mock import AsyncMock

from pscad_mcp.core.service import (
    ConfirmationRequired,
    PscadService,
)
from tests.backend_fakes import ImmediateExecutor


class TestSafetyContract(unittest.IsolatedAsyncioTestCase):
    def test_open_ended_numeric_ranges_are_enforced(self):
        self.assertTrue(PscadService._value_in_range(5, (0, None)))
        self.assertFalse(PscadService._value_in_range(-1, (0, None)))
        self.assertTrue(PscadService._value_in_range(-5, (None, 0)))
        self.assertFalse(PscadService._value_in_range(1, (None, 0)))

    async def test_batch_delete_validates_all_ids_before_first_delete(self):
        backend = AsyncMock()
        backend.delete_components.side_effect = RuntimeError("missing")
        service = PscadService(lambda: backend, executor=ImmediateExecutor())
        service._backend = backend

        with self.assertRaisesRegex(RuntimeError, "missing"):
            await service.delete_components(
                "case", [1, 2, 1], confirm=True
            )

        backend.delete_components.assert_awaited_once_with("case", [1, 2])
        backend.delete_component.assert_not_awaited()
        backend.get_component_location.assert_not_awaited()

    async def test_single_delete_uses_aggregate_backend_operation(self):
        backend = AsyncMock()
        service = PscadService(lambda: backend, executor=ImmediateExecutor())
        service._backend = backend

        result = await service.delete_component("case", 7, confirm=True)

        self.assertEqual(result, "Component 7 deleted.")
        backend.delete_components.assert_awaited_once_with("case", [7])
        backend.delete_component.assert_not_awaited()

    async def test_destructive_service_operations_require_confirmation(self):
        backend = AsyncMock()
        service = PscadService(lambda: backend, executor=ImmediateExecutor())
        service._backend = backend

        for operation in (
            lambda: service.quit_pscad(confirm=False),
            lambda: service.save_project("case", confirm=False),
            lambda: service.delete_component("case", 1, confirm=False),
            lambda: service.delete_components("case", [1], confirm=False),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(ConfirmationRequired):
                    await operation()


if __name__ == "__main__":
    unittest.main()
