import asyncio
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from pscad_mcp.core.backend.base import (
    BackendError,
    BackendInfo,
    ProjectInfo,
    SimulationSetInfo,
    SimulationTaskInfo,
)
from pscad_mcp.core.executor import (
    ExecutorTimeoutError,
    ExecutorUnhealthyError,
)
from pscad_mcp.core.service import ConfirmationRequired, PscadService
from pscad_mcp.core.path_policy import PathPolicy
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
        licensed=True,
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
        self.licensed = licensed
        self.attached = False
        self.disconnect_count = 0
        self.quit_count = 0
        self.run_calls = []

    def info(self):
        return BackendInfo(
            self.name,
            self.version,
            self.x64,
            self.attached,
            False,
            self.licensed if self.attached else None,
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

    async def run_project(self, project_name):
        self.run_calls.append(project_name)


class FakeSimulationBackend:
    name = "legacy"

    def __init__(self):
        self.calls = []

    async def create_simulation_set(self, name):
        self.calls.append(("create", name))
        return SimulationSetInfo(name, None, ())

    async def remove_simulation_set(self, name):
        self.calls.append(("remove", name))

    async def list_simulation_set_tasks(self, name):
        self.calls.append(("tasks", name))
        return ["case"]

    async def remove_tasks_from_set(self, name, task_names):
        self.calls.append(("remove_tasks", name, list(task_names)))

    async def get_simulation_task_parameters(self, set_name, task_name):
        self.calls.append(("get_task", set_name, task_name))
        return SimulationTaskInfo(task_name, task_name, "", 1, 1)

    async def set_simulation_task_parameters(self, set_name, task_name, parameters):
        self.calls.append(("set_task", set_name, task_name, dict(parameters)))
        current = SimulationTaskInfo(task_name, task_name, "", 1, 1)
        return SimulationTaskInfo(
            task_name,
            current.namespace,
            parameters.get("controlgroup", current.controlgroup),
            parameters.get("volley", current.volley),
            parameters.get("affinity", current.affinity),
        )

    async def get_simulation_set_details(self, name):
        self.calls.append(("details", name))
        return SimulationSetInfo(name, None, ("case",))

    async def run_simulation_set(self, project_name, set_name):
        self.calls.append(("run", project_name, set_name))

    async def add_task_to_set(self, project_name, set_name, task_name):
        self.calls.append(("add", project_name, set_name, task_name))

    async def list_projects(self):
        self.calls.append(("projects",))
        return [ProjectInfo("case", "Case", "")]


class RecordingExecutor(ImmediateExecutor):
    def __init__(self, events):
        super().__init__()
        self.events = events

    def reset(self):
        self.events.append(("reset", "executor"))
        super().reset()


def service_with_backend(backend):
    service = PscadService(lambda: backend, executor=ImmediateExecutor())
    service._backend = backend
    return service


def service_with_unconfigured_path_policy():
    with patch.dict(
        os.environ,
        {
            "PSCAD_MCP_WORKSPACE": "",
            "PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "false",
        },
        clear=False,
    ):
        return PscadService(
            lambda: FakeLifecycleBackend(),
            executor=ImmediateExecutor(),
            path_policy=PathPolicy(),
        )


class TestPscadService(unittest.IsolatedAsyncioTestCase):
    async def test_workspace_error_marks_relative_candidate(self):
        service = service_with_unconfigured_path_policy()

        with self.assertRaises(BackendError) as raised:
            await service.load_projects(["case.pscx"])

        self.assertTrue(raised.exception.details["candidate_is_relative"])

    async def test_workspace_error_marks_absolute_candidate(self):
        service = service_with_unconfigured_path_policy()

        with self.assertRaises(BackendError) as raised:
            await service.load_projects([str(Path.cwd() / "case.pscx")])

        self.assertFalse(raised.exception.details["candidate_is_relative"])

    async def test_file_operation_without_workspace_returns_structured_error(self):
        backend = FakeLifecycleBackend()
        with patch.dict(
            os.environ,
            {
                "PSCAD_MCP_WORKSPACE": "",
                "PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "false",
            },
            clear=False,
        ):
            service = PscadService(
                lambda: backend,
                executor=ImmediateExecutor(),
                path_policy=PathPolicy(),
            )
            with self.assertRaises(BackendError) as raised:
                await service.load_projects(["case.pscx"])

        self.assertEqual(raised.exception.code, "WORKSPACE_NOT_CONFIGURED")
        self.assertEqual(raised.exception.operation, "load_projects")

    async def test_run_project_raises_structured_error_when_license_is_false(self):
        backend = FakeLifecycleBackend(licensed=False)
        backend.attached = True
        service = service_with_backend(backend)

        with self.assertRaises(BackendError) as raised:
            await service.run_project("case")

        self.assertEqual(raised.exception.code, "NOT_LICENSED")
        self.assertEqual(raised.exception.operation, "run_project")
        self.assertEqual(backend.run_calls, [])

    async def test_run_project_allows_unknown_license_state(self):
        backend = FakeLifecycleBackend(licensed=None)
        backend.attached = True
        service = service_with_backend(backend)

        self.assertIn("Simulation started", await service.run_project("case"))
        self.assertEqual(backend.run_calls, ["case"])

    async def test_remove_tasks_requires_confirmation_before_backend_call(self):
        backend = FakeSimulationBackend()
        service = service_with_backend(backend)
        with self.assertRaises(ConfirmationRequired):
            await service.remove_tasks_from_set("Batch1", ["case"])
        self.assertEqual(backend.calls, [])

    async def test_remove_tasks_deduplicates_before_backend_call(self):
        backend = FakeSimulationBackend()
        service = service_with_backend(backend)
        result = await service.remove_tasks_from_set(
            "Batch1", ["case", "case"], confirm=True
        )
        self.assertEqual(result, {"removed": ["case"]})
        self.assertEqual(backend.calls, [("remove_tasks", "Batch1", ["case"])])

    async def test_task_parameters_reject_bool_as_integer(self):
        service = service_with_backend(FakeSimulationBackend())
        with self.assertRaises(BackendError) as raised:
            await service.set_simulation_task_parameters(
                "Batch1", "case", {"volley": True}
            )
        self.assertEqual(raised.exception.code, "INVALID_ARGUMENT")

    async def test_task_parameters_reject_values_below_one(self):
        service = service_with_backend(FakeSimulationBackend())
        with self.assertRaises(BackendError) as raised:
            await service.set_simulation_task_parameters(
                "Batch1", "case", {"affinity": 0}
            )
        self.assertEqual(raised.exception.code, "INVALID_ARGUMENT")

    async def test_task_parameters_reject_read_only_and_unknown_fields(self):
        service = service_with_backend(FakeSimulationBackend())
        for values in ({"namespace": "other"}, {"unknown": 1}):
            with self.subTest(values=values):
                with self.assertRaises(BackendError) as raised:
                    await service.set_simulation_task_parameters(
                        "Batch1", "case", values
                    )
                self.assertEqual(raised.exception.code, "INVALID_ARGUMENT")

    async def test_simulation_set_results_are_normalized(self):
        backend = FakeSimulationBackend()
        service = service_with_backend(backend)
        self.assertEqual(
            await service.create_simulation_set("Batch1"),
            {"name": "Batch1", "depends_on": None, "tasks": ()},
        )
        self.assertEqual(
            await service.get_simulation_task_parameters("Batch1", "case"),
            {
                "name": "case",
                "namespace": "case",
                "controlgroup": "",
                "volley": 1,
                "affinity": 1,
            },
        )

    async def test_simulation_set_names_must_be_non_empty(self):
        service = service_with_backend(FakeSimulationBackend())
        with self.assertRaises(BackendError) as raised:
            await service.create_simulation_set(" ")
        self.assertEqual(raised.exception.code, "INVALID_ARGUMENT")

    async def test_run_simulation_set_verifies_set_before_backend_run(self):
        backend = FakeSimulationBackend()
        service = service_with_backend(backend)
        await service.run_simulation_set("compat", "Batch1")
        self.assertEqual(
            backend.calls[:2],
            [("details", "Batch1"), ("run", "compat", "Batch1")],
        )

    async def test_add_task_rejects_unloaded_project(self):
        backend = FakeSimulationBackend()
        backend.list_projects = lambda: None

        async def no_projects():
            backend.calls.append(("projects",))
            return []

        backend.list_projects = no_projects
        service = service_with_backend(backend)
        with self.assertRaises(BackendError) as raised:
            await service.add_task_to_set("compat", "Batch1", "missing")
        self.assertEqual(raised.exception.code, "NOT_FOUND")
        self.assertNotIn(("add", "compat", "Batch1", "missing"), backend.calls)

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
        self.assertEqual(
            status["executor"],
            {
                "healthy": True,
                "last_operation": None,
                "last_error": None,
                "last_timeout_seconds": None,
            },
        )
        json.dumps(status)

    async def test_status_includes_bounded_session_details(self):
        backend = FakeLifecycleBackend()
        backend.session_details = {
            "mode": "managed-launch",
            "managed_pid": 1234,
            "ordinary_gui_attach_supported": False,
        }
        service = PscadService(
            lambda: backend,
            executor=ImmediateExecutor(),
        )
        await service.attach_local()

        status = await service.status()

        self.assertEqual(status["session"]["managed_pid"], 1234)
        self.assertFalse(
            status["session"]["ordinary_gui_attach_supported"]
        )
        json.dumps(status)

    async def test_pause_and_stop_are_serialized_by_mutation_lock(self):
        class SerialRunControlBackend(FakeLifecycleBackend):
            def __init__(self):
                super().__init__()
                self.active_calls = 0
                self.max_active = 0
                self.entered = asyncio.Event()
                self.release = asyncio.Event()

            async def _record(self):
                self.active_calls += 1
                self.max_active = max(self.max_active, self.active_calls)
                self.entered.set()
                await self.release.wait()
                self.active_calls -= 1

            async def pause_project(self, _project_name):
                await self._record()

            async def stop_project(self, _project_name):
                await self._record()

        backend = SerialRunControlBackend()
        service = PscadService(
            lambda: backend,
            executor=ImmediateExecutor(),
        )
        await service.attach_local()
        pause = asyncio.create_task(service.pause_simulation("case"))
        await backend.entered.wait()
        stop = asyncio.create_task(service.stop_simulation("case"))
        await asyncio.sleep(0)

        backend.release.set()
        messages = await asyncio.gather(pause, stop)

        self.assertEqual(
            messages,
            [
                "Simulation paused for 'case'.",
                "Simulation stopped for 'case'.",
            ],
        )
        self.assertEqual(backend.max_active, 1)

    async def test_status_before_attach_does_not_create_backend(self):
        created = []
        service = PscadService(
            lambda: created.append(FakeLifecycleBackend()),
            executor=ImmediateExecutor(),
        )

        status = await service.status()

        self.assertFalse(status["connected"])
        self.assertEqual(created, [])
        self.assertEqual(
            status["executor"],
            {
                "healthy": True,
                "last_operation": None,
                "last_error": None,
                "last_timeout_seconds": None,
            },
        )

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

        self.assertIn("launched a visible managed PSCAD automation instance", result)
        self.assertIn("does not attach to an already-open GUI", result)

    def test_error_payload_guides_run_control_recovery(self):
        cases = (
            (
                "EXTERNAL_PSCAD_PRESENT",
                "close",
            ),
            (
                "RUN_CONTROL_SCOPE_CONFLICT",
                "active",
            ),
            (
                "RUN_NOT_ACTIVE",
                "run",
            ),
        )
        for code, phrase in cases:
            with self.subTest(code=code):
                error = BackendError(code, "blocked", "legacy", "operation")
                payload = PscadService.error_payload(error, "fallback")["error"]
                self.assertFalse(payload["retryable"])
                self.assertIn(phrase, payload["suggested_action"].lower())

    def test_error_payload_preserves_backend_details(self):
        error = BackendError(
            "NOT_FOUND", "missing", "legacy", "project", {"name": "case"}
        )

        payload = PscadService.error_payload(error, "fallback")

        self.assertEqual(payload["error"]["code"], "NOT_FOUND")
        self.assertEqual(payload["error"]["details"], {"name": "case"})
        self.assertFalse(payload["error"]["retryable"])
        self.assertEqual(
            payload["error"]["suggested_action"],
            "Check names and list the current PSCAD objects.",
        )

    def test_error_payload_guides_unlicensed_simulation_recovery(self):
        error = BackendError(
            "NOT_LICENSED",
            "PSCAD is not licensed",
            "legacy",
            "run_project",
        )

        payload = PscadService.error_payload(error, "run_project")["error"]

        self.assertFalse(payload["retryable"])
        self.assertIn("license", payload["suggested_action"].lower())

    def test_error_payload_guides_workspace_configuration(self):
        error = BackendError(
            "WORKSPACE_NOT_CONFIGURED",
            "workspace required",
            "service",
            "load_projects",
        )

        payload = PscadService.error_payload(error, "load_projects")["error"]

        self.assertFalse(payload["retryable"])
        self.assertIn("PSCAD_MCP_WORKSPACE", payload["suggested_action"])

    def test_error_payload_classifies_executor_failures(self):
        timeout = PscadService.error_payload(
            ExecutorTimeoutError("timed out"),
            "run_project",
        )["error"]
        unhealthy = PscadService.error_payload(
            ExecutorUnhealthyError("reset required"),
            "run_project",
        )["error"]

        self.assertEqual(timeout["code"], "TIMEOUT")
        self.assertEqual(timeout["backend"], "executor")
        self.assertTrue(timeout["retryable"])
        self.assertIn("repair_connection", timeout["suggested_action"])
        self.assertEqual(unhealthy["code"], "EXECUTOR_UNHEALTHY")
        self.assertTrue(unhealthy["retryable"])

    def test_error_payload_requires_inspection_after_partial_completion(self):
        error = BackendError(
            "PARTIAL_COMPLETION",
            "some objects were deleted",
            "legacy",
            "delete_components",
            {"deleted_component_ids": [7]},
        )

        payload = PscadService.error_payload(error, "fallback")["error"]

        self.assertFalse(payload["retryable"])
        self.assertIn("Inspect details", payload["suggested_action"])

    def test_error_payload_normalizes_unknown_exception_without_traceback(self):
        payload = PscadService.error_payload(
            ValueError("invalid value"),
            "set_project_settings",
        )["error"]

        self.assertEqual(payload["code"], "INTERNAL_ERROR")
        self.assertEqual(payload["message"], "invalid value")
        self.assertFalse(payload["retryable"])
        self.assertIn("server logs", payload["suggested_action"])
        self.assertNotIn("traceback", payload)


if __name__ == "__main__":
    unittest.main()
