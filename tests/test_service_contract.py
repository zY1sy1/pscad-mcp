import json
import unittest

from pscad_mcp.core.backend.base import BackendError, BackendInfo
from pscad_mcp.core.service import ConfirmationRequired, PscadService
from tests.backend_fakes import ImmediateExecutor


class FakeLifecycleBackend:
    def __init__(
        self,
        name="legacy",
        version="4.6.2",
        *,
        owns_process=True,
        events=None,
        label="backend",
        attach_error=None,
        disconnect_error=None,
        quit_error=None,
        heartbeat_error=None,
    ):
        self.name = name
        self.version = version
        self.x64 = True
        self.owns_process = owns_process
        self.events = events if events is not None else []
        self.label = label
        self.attach_error = attach_error
        self.disconnect_error = disconnect_error
        self.quit_error = quit_error
        self.heartbeat_error = heartbeat_error
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
            self.owns_process,
        )

    async def attach(self):
        self.events.append(("attach", self.label))
        if self.attach_error is not None:
            raise self.attach_error
        self.attached = True
        return self.info()

    async def heartbeat(self):
        if self.heartbeat_error is not None:
            raise self.heartbeat_error
        return self.info()

    async def disconnect(self):
        self.events.append(("disconnect", self.label))
        if self.disconnect_error is not None:
            raise self.disconnect_error
        self.disconnect_count += 1
        self.attached = False

    async def quit(self):
        self.events.append(("quit", self.label))
        if self.quit_error is not None:
            raise self.quit_error
        self.quit_count += 1
        self.attached = False


class RecordingExecutor(ImmediateExecutor):
    def __init__(self, events):
        super().__init__()
        self.events = events

    def reset(self):
        self.events.append(("reset", "executor"))
        super().reset()


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

    async def test_repair_quits_owned_process_before_reset_and_fresh_attach(self):
        events = []
        executor = RecordingExecutor(events)
        backends = []

        def factory():
            label = f"backend-{len(backends) + 1}"
            events.append(("factory", label))
            backend = FakeLifecycleBackend(
                owns_process=True,
                events=events,
                label=label,
            )
            backends.append(backend)
            return backend

        service = PscadService(factory, executor=executor)
        await service.attach_local()
        events.clear()

        result = await service.repair_connection()

        self.assertEqual(len(backends), 2)
        self.assertEqual(backends[0].quit_count, 1)
        self.assertEqual(backends[0].disconnect_count, 0)
        self.assertEqual(executor.reset_count, 1)
        self.assertEqual(
            events,
            [
                ("quit", "backend-1"),
                ("reset", "executor"),
                ("factory", "backend-2"),
                ("attach", "backend-2"),
            ],
        )
        self.assertIn("4.6.2", result)

    async def test_repair_disconnects_non_owned_process_before_fresh_attach(self):
        events = []
        executor = RecordingExecutor(events)
        backends = []

        def factory():
            label = f"backend-{len(backends) + 1}"
            events.append(("factory", label))
            backend = FakeLifecycleBackend(
                owns_process=False,
                events=events,
                label=label,
            )
            backends.append(backend)
            return backend

        service = PscadService(factory, executor=executor)
        await service.attach_local()
        events.clear()

        await service.repair_connection()

        self.assertEqual(backends[0].disconnect_count, 1)
        self.assertEqual(backends[0].quit_count, 0)
        self.assertEqual(
            events,
            [
                ("disconnect", "backend-1"),
                ("reset", "executor"),
                ("factory", "backend-2"),
                ("attach", "backend-2"),
            ],
        )

    async def test_repair_unhealthy_owned_process_resets_before_cleanup(self):
        events = []
        executor = RecordingExecutor(events)
        backends = []

        def factory():
            label = f"backend-{len(backends) + 1}"
            events.append(("factory", label))
            backend = FakeLifecycleBackend(
                owns_process=True,
                events=events,
                label=label,
                heartbeat_error=AssertionError("repair must not call heartbeat"),
            )
            backends.append(backend)
            return backend

        service = PscadService(factory, executor=executor)
        await service.attach_local()
        events.clear()
        executor.healthy = False

        result = await service.repair_connection()

        self.assertEqual(
            events,
            [
                ("reset", "executor"),
                ("quit", "backend-1"),
                ("reset", "executor"),
                ("factory", "backend-2"),
                ("attach", "backend-2"),
            ],
        )
        self.assertEqual(len(backends), 2)
        self.assertIn("4.6.2", result)

    async def test_repair_unhealthy_external_process_disconnects_without_heartbeat(self):
        events = []
        executor = RecordingExecutor(events)
        backends = []

        def factory():
            label = f"backend-{len(backends) + 1}"
            events.append(("factory", label))
            backend = FakeLifecycleBackend(
                owns_process=False,
                events=events,
                label=label,
                heartbeat_error=AssertionError("repair must not call heartbeat"),
            )
            backends.append(backend)
            return backend

        service = PscadService(factory, executor=executor)
        await service.attach_local()
        events.clear()
        executor.healthy = False

        await service.repair_connection()

        self.assertEqual(
            events,
            [
                ("disconnect", "backend-1"),
                ("reset", "executor"),
                ("factory", "backend-2"),
                ("attach", "backend-2"),
            ],
        )
        self.assertEqual(backends[0].quit_count, 0)

    async def test_repair_unhealthy_owned_cleanup_failure_does_not_reattach(self):
        events = []
        executor = RecordingExecutor(events)
        cleanup_failure = RuntimeError("cleanup failed")
        backend = FakeLifecycleBackend(
            owns_process=True,
            events=events,
            label="backend-1",
            quit_error=cleanup_failure,
            heartbeat_error=AssertionError("repair must not call heartbeat"),
        )
        created = []
        service = PscadService(
            lambda: created.append(FakeLifecycleBackend()),
            executor=executor,
        )
        service._backend = backend
        backend.attached = True
        executor.healthy = False

        with self.assertRaises(BackendError) as raised:
            await service.repair_connection()

        self.assertEqual(raised.exception.code, "REPAIR_CLEANUP_FAILED")
        self.assertEqual(raised.exception.backend, "legacy")
        self.assertIsNone(service._backend)
        self.assertTrue(executor.healthy)
        self.assertEqual(created, [])
        self.assertEqual(
            events,
            [
                ("reset", "executor"),
                ("quit", "backend-1"),
                ("disconnect", "backend-1"),
                ("reset", "executor"),
            ],
        )

    async def test_repair_shutdown_failure_preserves_original_backend(self):
        for owns_process in (True, False):
            with self.subTest(owns_process=owns_process):
                failure = BackendError(
                    "SHUTDOWN_FAILED",
                    "shutdown failed",
                    "legacy",
                    "repair_connection",
                )
                backend = FakeLifecycleBackend(
                    owns_process=owns_process,
                    quit_error=failure if owns_process else None,
                    disconnect_error=None if owns_process else failure,
                )
                created = [backend]
                executor = ImmediateExecutor()
                service = PscadService(
                    lambda: created.append(FakeLifecycleBackend()),
                    executor=executor,
                )
                service._backend = backend
                backend.attached = True

                with self.assertRaises(BackendError) as raised:
                    await service.repair_connection()

                self.assertIs(raised.exception, failure)
                self.assertIs(service._backend, backend)
                self.assertEqual(executor.reset_count, 0)
                self.assertEqual(len(created), 1)

    async def test_repair_fresh_attach_failure_clears_failed_candidate(self):
        failure = BackendError(
            "ATTACH_FAILED",
            "attach failed",
            "legacy",
            "attach",
        )
        first = FakeLifecycleBackend(owns_process=False, label="backend-1")
        second = FakeLifecycleBackend(
            owns_process=True,
            label="backend-2",
            attach_error=failure,
        )
        backends = [first, second]
        service = PscadService(
            lambda: backends.pop(0),
            executor=ImmediateExecutor(),
        )
        await service.attach_local()

        with self.assertRaises(BackendError) as raised:
            await service.repair_connection()

        self.assertIs(raised.exception, failure)
        self.assertIsNone(service._backend)
        self.assertEqual(service.executor.reset_count, 1)

    async def test_legacy_attach_wording_describes_launch_only_behavior(self):
        backend = FakeLifecycleBackend(name="legacy", version="4.6.2")
        service = PscadService(lambda: backend, executor=ImmediateExecutor())

        result = await service.attach_local()

        self.assertIn("launched a new PSCAD automation instance", result)
        self.assertIn("does not attach to an already-open GUI", result)

    def test_error_payload_preserves_backend_details(self):
        error = BackendError(
            "NOT_FOUND", "missing", "legacy", "project", {"name": "case"}
        )

        payload = PscadService.error_payload(error, "fallback")

        self.assertEqual(payload["error"]["code"], "NOT_FOUND")
        self.assertEqual(payload["error"]["details"], {"name": "case"})


if __name__ == "__main__":
    unittest.main()
