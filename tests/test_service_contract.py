import json
import unittest

from pscad_mcp.core.backend.base import BackendError, BackendInfo
from pscad_mcp.core.service import ConfirmationRequired, PscadService
from tests.backend_fakes import ImmediateExecutor


class FakeLifecycleBackend:
    def __init__(self, name="legacy", version="4.6.2"):
        self.name = name
        self.version = version
        self.x64 = True
        self.attached = False
        self.disconnect_count = 0
        self.quit_count = 0

    def info(self):
        return BackendInfo(
            self.name,
            self.version,
            self.x64,
            self.attached,
            False,
            True if self.attached else None,
            self.attached,
        )

    async def attach(self):
        self.attached = True
        return self.info()

    async def heartbeat(self):
        return self.info()

    async def disconnect(self):
        self.disconnect_count += 1
        self.attached = False

    async def quit(self):
        self.quit_count += 1
        self.attached = False


class TestPscadService(unittest.IsolatedAsyncioTestCase):
    async def test_backend_is_selected_lazily(self):
        created = []

        def factory():
            backend = FakeLifecycleBackend()
            created.append(backend)
            return backend

        service = PscadService(factory, executor=ImmediateExecutor())

        self.assertEqual(created, [])
        result = await service.attach_local()

        self.assertEqual(len(created), 1)
        self.assertIn("legacy", result)
        self.assertIn("4.6.2", result)

    async def test_status_is_json_safe(self):
        backend = FakeLifecycleBackend()
        service = PscadService(lambda: backend, executor=ImmediateExecutor())
        await service.attach_local()

        status = await service.status()

        self.assertTrue(status["connected"])
        self.assertEqual(status["backend"], "legacy")
        self.assertEqual(status["selected_version"], "4.6.2")
        json.dumps(status)

    async def test_status_before_attach_does_not_create_backend(self):
        created = []
        service = PscadService(
            lambda: created.append(FakeLifecycleBackend()),
            executor=ImmediateExecutor(),
        )

        status = await service.status()

        self.assertFalse(status["connected"])
        self.assertEqual(created, [])

    async def test_quit_requires_confirmation(self):
        backend = FakeLifecycleBackend()
        service = PscadService(lambda: backend, executor=ImmediateExecutor())
        await service.attach_local()

        with self.assertRaisesRegex(ConfirmationRequired, "confirm=true"):
            await service.quit_pscad(confirm=False)

        self.assertEqual(backend.quit_count, 0)

    async def test_repair_disconnects_resets_and_selects_fresh_backend(self):
        executor = ImmediateExecutor()
        backends = []

        def factory():
            backend = FakeLifecycleBackend()
            backends.append(backend)
            return backend

        service = PscadService(factory, executor=executor)
        await service.attach_local()

        result = await service.repair_connection()

        self.assertEqual(len(backends), 2)
        self.assertEqual(backends[0].disconnect_count, 1)
        self.assertEqual(executor.reset_count, 1)
        self.assertIn("4.6.2", result)

    def test_error_payload_preserves_backend_details(self):
        error = BackendError(
            "NOT_FOUND", "missing", "legacy", "project", {"name": "case"}
        )

        payload = PscadService.error_payload(error, "fallback")

        self.assertEqual(payload["error"]["code"], "NOT_FOUND")
        self.assertEqual(payload["error"]["details"], {"name": "case"})


if __name__ == "__main__":
    unittest.main()
