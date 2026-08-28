"""PSCAD 5.x backend implemented with the current MHI API."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import time
from typing import Any, Sequence

from ...topology.hashing import canonical_sha256
from ...topology.models import (
    DefinitionPortContract,
    EvidenceRef,
    TopologyBoundaryLink,
    TopologyCanvas,
    TopologyComponent,
    TopologyConductor,
    TopologyLabel,
    TopologyPort,
    TopologySnapshot,
)

from ..pscad_adapter import PscadAdapter
from ..pscad_config import _version_key
from .base import (
    BackendError,
    BackendInfo,
    ComponentInfo,
    ParameterGridRequest,
    PortInfo,
    ProjectMessage,
    ProjectInfo,
    RunState,
    SimulationSetInfo,
    SimulationTaskInfo,
    JsonDict,
)
from .run_control import (
    STOPPED_RUN_STATUSES,
    require_active_target,
    require_single_active_target,
)


class ModernBackend:
    name = "modern"
    _TASK_PARAMETER_ORDER = ("controlgroup", "volley", "affinity")
    RUN_CONTROL_TIMEOUT = 5.0
    RUN_CONTROL_POLL_INTERVAL = 0.1

    def __init__(
        self,
        executor: Any,
        *,
        version: str,
        x64: bool,
        pscad_module: Any = None,
        psout_module: Any = None,
        timeout: int = 30,
    ) -> None:
        self.executor = executor
        self.version = version
        self.x64 = x64
        self._app: Any = None
        self.adapter = PscadAdapter(
            executor,
            pscad_module=pscad_module,
            psout_module=psout_module,
            environ={
                "PSCAD_MCP_BACKEND": "modern",
                "PSCAD_MCP_VERSION": version,
                "PSCAD_MCP_X64": "true" if x64 else "false",
                "PSCAD_MCP_LAUNCH_TIMEOUT": str(timeout),
            },
        )

    @property
    def owns_process(self) -> bool:
        return self.adapter.owns_process

    def _info(
        self,
        *,
        alive: bool,
        busy: bool = False,
        licensed: bool | None = None,
    ) -> BackendInfo:
        return BackendInfo(
            backend=self.name,
            version=self.version,
            x64=self.x64,
            alive=alive,
            busy=busy,
            licensed=licensed,
            owns_process=self.owns_process,
        )

    async def attach(self) -> BackendInfo:
        key = _version_key(self.version)
        if not key or key[0] < 5:
            raise BackendError(
                "UNSUPPORTED_VERSION",
                f"The modern backend requires PSCAD 5.x; requested {self.version}.",
                self.name,
                "attach",
                {"version": self.version},
            )
        self._app = await self.adapter.attach_local()
        return await self.heartbeat()

    async def heartbeat(self) -> BackendInfo:
        if self._app is None:
            return self._info(alive=False)
        state = await self.adapter.heartbeat()
        licensed_method = getattr(self._app, "licensed", None)
        licensed = (
            bool(await self.executor.run_safe(licensed_method))
            if licensed_method is not None
            else None
        )
        return self._info(
            alive=bool(state["alive"]),
            busy=bool(state["busy"]),
            licensed=licensed,
        )

    async def disconnect(self) -> None:
        self._app = None
        self.adapter.disconnect()

    async def quit(self) -> None:
        app = self._app
        if app is not None:
            await self.adapter.call(app, "quit")
        await self.disconnect()

    async def _project(self, project_name: str) -> Any:
        if self._app is None:
            raise BackendError(
                "NOT_CONNECTED",
                "PSCAD is not connected.",
                self.name,
                "project",
            )
        return await self.adapter.call(self._app, "project", project_name)

    @staticmethod
    def _project_info(value: Any, fallback_type: str = "") -> ProjectInfo:
        if isinstance(value, dict):
            return ProjectInfo(
                str(value.get("name", "")),
                str(value.get("type", fallback_type)),
                str(value.get("description") or ""),
            )
        return ProjectInfo(
            str(getattr(value, "name", "")),
            str(getattr(value, "type", fallback_type)),
            str(getattr(value, "description", "")),
        )

    async def load_projects(self, filenames: Any) -> None:
        await self.adapter.call(self._app, "load", *filenames)

    async def unload_project(self, project_name: str) -> None:
        await self.adapter.call(await self._project(project_name), "unload")

    async def list_projects(self) -> list[ProjectInfo]:
        values = await self.adapter.call(self._app, "projects")
        return [self._project_info(value) for value in values]

    async def create_project(
        self, kind: str, filename: str, folder: str | None
    ) -> ProjectInfo:
        if kind not in {"case", "library"}:
            raise ValueError("kind must be case or library.")
        kwargs: dict[str, Any] = {"filename": filename}
        if folder is not None:
            kwargs["folder"] = folder
        project = await self.adapter.call(
            self._app,
            "create_case" if kind == "case" else "create_library",
            **kwargs,
        )
        return self._project_info(project, "Case" if kind == "case" else "Library")

    async def save_project(self, project_name: str) -> None:
        await self.adapter.call(await self._project(project_name), "save")

    async def save_project_as(
        self, project_name: str, filename: str, folder: str | None
    ) -> None:
        kwargs: dict[str, Any] = {"filename": filename}
        if folder is not None:
            kwargs["folder"] = folder
        await self.adapter.call(
            await self._project(project_name), "save_as", **kwargs
        )

    async def build_project(self, project_name: str) -> None:
        await self.adapter.call(
            await self._project(project_name), "build", timeout=300.0
        )

    async def build_all_projects(self) -> None:
        await self.adapter.call(self._app, "build_all", timeout=300.0)

    async def get_timed_control_capabilities(self, project_name: str) -> dict[str, Any]:
        project = await self._project(project_name)
        return {
            "native_schedule": callable(getattr(project, "schedule_timed_controls", None)),
            "simulation_clock": callable(getattr(project, "get_simulation_time", None)),
            "time_basis": "EMTDC",
        }

    async def schedule_timed_controls(self, project_name: str, events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        project = await self._project(project_name)
        provider = getattr(project, "schedule_timed_controls", None)
        if callable(provider):
            values = await self.executor.run_safe(provider, [dict(event) for event in events])
            if isinstance(values, (list, tuple)):
                return [dict(item) for item in values if isinstance(item, Mapping)]
        raise BackendError(
            "CAPABILITY_UNAVAILABLE",
            "Modern PSCAD backend does not expose verified timed-control scheduling.",
            self.name,
            "schedule_timed_controls",
            {"project_name": project_name, "backend_version": self.version},
        )

    async def get_simulation_time(self, project_name: str) -> float:
        project = await self._project(project_name)
        provider = getattr(project, "get_simulation_time", None)
        if callable(provider):
            return float(await self.executor.run_safe(provider))
        raise BackendError(
            "CAPABILITY_UNAVAILABLE",
            "Modern PSCAD backend does not expose a verified simulation clock.",
            self.name,
            "get_simulation_time",
            {"project_name": project_name, "backend_version": self.version},
        )

    async def run_project(self, project_name: str) -> None:
        await self.adapter.call(
            await self._project(project_name), "run", timeout=300.0
        )

    async def pause_project(self, project_name: str) -> None:
        states = await self._case_run_states()
        target = require_single_active_target(
            project_name,
            states,
            backend=self.name,
            operation="pause_project",
        )
        if target.status.casefold() == "paused":
            return
        await self.adapter.call(await self._project(project_name), "pause")
        await self._wait_for_project_state(
            project_name,
            frozenset({"paused"}),
            "pause_project",
        )

    async def stop_project(self, project_name: str) -> None:
        states = await self._case_run_states()
        require_active_target(
            project_name,
            states,
            backend=self.name,
            operation="stop_project",
        )
        project = await self._project(project_name)
        single_stop = getattr(self._app, "stop_single_project", None)
        if callable(single_stop):
            response = await self.adapter.call(
                self._app,
                "stop_single_project",
                project,
            )
            if response is False:
                raise BackendError(
                    "PSCAD_COMMAND_FAILED",
                    "PSCAD rejected the single-project stop command.",
                    self.name,
                    "stop_project",
                    {
                        "project_name": project_name,
                        "scope": "single-project",
                    },
                )
        else:
            await self.adapter.call(project, "stop")
        await self._wait_for_project_state(
            project_name,
            STOPPED_RUN_STATUSES,
            "stop_project",
        )

    async def _case_run_states(self) -> dict[str, RunState]:
        states: dict[str, RunState] = {}
        for project in await self.list_projects():
            if project.type.casefold() != "case":
                continue
            states[project.name] = await self.project_run_state(project.name)
        return states

    async def _wait_for_project_state(
        self,
        project_name: str,
        expected: frozenset[str],
        operation: str,
    ) -> RunState:
        deadline = time.monotonic() + self.RUN_CONTROL_TIMEOUT
        last_state: RunState | None = None
        while True:
            last_state = await self.project_run_state(project_name)
            if last_state.status.casefold() in expected:
                return last_state
            if time.monotonic() >= deadline:
                raise BackendError(
                    "POSTCONDITION_FAILED",
                    "PSCAD accepted the run-control command, but the requested "
                    "project state was not observed.",
                    self.name,
                    operation,
                    {
                        "project_name": project_name,
                        "expected_states": sorted(expected),
                        "last_state": last_state.status.casefold(),
                        "timeout_seconds": self.RUN_CONTROL_TIMEOUT,
                    },
                )
            await asyncio.sleep(self.RUN_CONTROL_POLL_INTERVAL)

    async def project_run_state(self, project_name: str) -> RunState:
        status, progress = await self.adapter.call(
            await self._project(project_name), "run_status"
        )
        return RunState(str(status), float(progress) if progress is not None else None)

    async def project_definitions(self, project_name: str) -> list[str]:
        values = await self.adapter.call(
            await self._project(project_name), "definitions"
        )
        return [str(value) for value in values]

    async def lcc_definition_inventory(self, catalog: Mapping[str, Any]) -> JsonDict:
        raise BackendError(
            "CAPABILITY_UNAVAILABLE",
            "The modern PSCAD backend does not expose the 4.6.2 LCC definition inventory contract.",
            self.name,
            "lcc_definition_inventory",
        )

    async def get_settings(self, project_name: str) -> dict[str, Any]:
        values = await self.adapter.call(self._app, "settings")
        return dict(values) if hasattr(values, "items") else {"value": str(values)}

    async def set_settings(self, project_name: str, settings: Any) -> None:
        await self.adapter.call(self._app, "settings", **dict(settings))

    async def project_output(self, project_name: str) -> str:
        return str(
            await self.adapter.call(await self._project(project_name), "output")
        )

    async def get_output_channels(self, project_name: str) -> list[dict[str, Any]]:
        project = await self._project(project_name)
        provider = getattr(project, "output_channels", None)
        if not callable(provider):
            raise BackendError(
                "CAPABILITY_UNAVAILABLE",
                "Modern PSCAD does not expose verified output-channel metadata.",
                self.name,
                "get_output_channels",
                {"project_name": project_name, "backend_version": self.version},
            )
        values = await self.executor.run_safe(provider)
        if isinstance(values, Mapping):
            values = values.get("channels", values.get("output_channels", []))
        if not isinstance(values, (list, tuple)):
            raise BackendError(
                "CAPABILITY_UNAVAILABLE",
                "Modern output-channel metadata has an invalid shape.",
                self.name,
                "get_output_channels",
                {"project_name": project_name},
            )
        return [
            {
                "path": str(item["path"]),
                "call_id": item.get("call_id"),
                "units": item.get("units"),
                "description": str(item.get("description", "")),
            }
            for item in values
            if isinstance(item, Mapping) and item.get("path")
        ]

    @staticmethod
    def _message_source_value(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Mapping):
            return {
                str(key): ModernBackend._message_source_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [ModernBackend._message_source_value(item) for item in value]
        return str(value)

    @staticmethod
    def _project_message(value: Any) -> ProjectMessage:
        source_fields = ("label", "scope", "name", "link", "group", "classid")
        if isinstance(value, Mapping):
            text = value.get("text", value.get("message", ""))
            severity = value.get(
                "severity",
                value.get("level", value.get("status", "normal")),
            )
            source = value.get("source")
            if source is None:
                source = {
                    field: value[field]
                    for field in source_fields
                    if value.get(field) not in (None, "")
                }
        else:
            text = getattr(value, "text", getattr(value, "message", value))
            severity = getattr(
                value,
                "severity",
                getattr(value, "level", getattr(value, "status", "normal")),
            )
            source = getattr(value, "source", None)
            if source is None:
                source = {
                    field: getattr(value, field)
                    for field in source_fields
                    if getattr(value, field, None) not in (None, "")
                }
        if isinstance(source, Mapping):
            normalized_source = ModernBackend._message_source_value(source)
        elif source:
            normalized_source = {
                "value": ModernBackend._message_source_value(source)
            }
        else:
            normalized_source = None
        return ProjectMessage(
            str(severity),
            str(text),
            normalized_source,
        )

    async def project_messages(self, project_name: str) -> list[ProjectMessage]:
        project = await self._project(project_name)
        messages_method = getattr(project, "messages", None)
        if messages_method is not None:
            values = await self.adapter.call(project, "messages")
            return [self._project_message(value) for value in values]
        output = getattr(project, "output", None)
        if output is not None:
            return [
                ProjectMessage(
                    "normal",
                    str(await self.adapter.call(project, "output")),
                    None,
                )
            ]
        return []

    async def parameter_grid(self, request: ParameterGridRequest) -> dict[str, Any]:
        if self._app is None:
            raise BackendError(
                "NOT_CONNECTED",
                "PSCAD is not connected.",
                self.name,
                "parameter_grid",
            )
        grid = getattr(self._app, "parameter_grid", None)
        if grid is None:
            try:
                from mhi.pscad.parameter_grid import ParameterGrid
            except ImportError as error:
                raise BackendError(
                    "CAPABILITY_UNAVAILABLE",
                    "The installed modern PSCAD API does not expose parameter-grid operations.",
                    self.name,
                    "parameter_grid",
                ) from error
            grid = ParameterGrid(self._app)
        elif not any(
            callable(getattr(grid, method_name, None))
            for method_name in ("view", "load", "save")
        ) and callable(grid):
            grid = grid()

        if request.action == "view_project":
            project = await self._project(request.project_name or "")
            await self.adapter.call(grid, "view", project)
        elif request.action in {"load", "save"}:
            await self.adapter.call(
                grid,
                request.action,
                request.filename,
                folder=request.folder,
            )
        else:
            raise BackendError(
                "INVALID_ARGUMENT",
                f"Unsupported parameter-grid action '{request.action}'.",
                self.name,
                "parameter_grid",
                {"action": request.action},
            )
        return {
            "action": request.action,
            "project": request.project_name,
            "filename": request.filename,
            "supported": True,
        }

    async def list_simulation_sets(self, project_name: str) -> list[str]:
        values = await self.adapter.call(self._app, "simulation_sets")
        return [str(value) for value in values]

    async def _simulation_set(self, set_name: str) -> Any:
        if self._app is None:
            raise BackendError("NOT_CONNECTED", "PSCAD is not connected.", self.name, "simulation_set")
        if set_name not in await self.list_simulation_sets(""):
            raise BackendError(
                "NOT_FOUND",
                f"Simulation set '{set_name}' was not found.",
                self.name,
                "simulation_set",
                {"sim_set_name": set_name},
            )
        return await self.adapter.call(self._app, "simulation_set", set_name)

    async def create_simulation_set(self, set_name: str) -> SimulationSetInfo:
        if set_name in await self.list_simulation_sets(""):
            raise BackendError(
                "ALREADY_EXISTS",
                f"Simulation set '{set_name}' already exists.",
                self.name,
                "create_simulation_set",
                {"sim_set_name": set_name},
            )
        await self.adapter.call(self._app, "create_simulation_set", set_name)
        if set_name not in await self.list_simulation_sets(""):
            raise BackendError(
                "POSTCONDITION_FAILED",
                "Created simulation set was not found after the command.",
                self.name,
                "create_simulation_set",
                {"sim_set_name": set_name},
            )
        return await self.get_simulation_set_details(set_name)

    async def remove_simulation_set(self, set_name: str) -> None:
        await self._simulation_set(set_name)
        await self.adapter.call(self._app, "remove_simulation_set", set_name)
        if set_name in await self.list_simulation_sets(""):
            raise BackendError(
                "POSTCONDITION_FAILED",
                "Removed simulation set is still present.",
                self.name,
                "remove_simulation_set",
                {"sim_set_name": set_name},
            )

    async def list_simulation_set_tasks(self, set_name: str) -> list[str]:
        simset = await self._simulation_set(set_name)
        values = await self.adapter.call(simset, "list_tasks")
        result = []
        for value in values:
            name = getattr(value, "name", value)
            if callable(name):
                name = await self.executor.run_safe(name)
            result.append(str(name))
        return result

    async def get_simulation_set_details(self, set_name: str) -> SimulationSetInfo:
        simset = await self._simulation_set(set_name)
        tasks = tuple(await self.list_simulation_set_tasks(set_name))
        dependency_method = getattr(simset, "depends_on", None)
        dependency = (
            await self.executor.run_safe(dependency_method)
            if dependency_method is not None
            else None
        )
        dependency = None if dependency in (None, "", "None") else str(dependency)
        return SimulationSetInfo(set_name, dependency, tasks)

    async def get_simulation_task_parameters(
        self, set_name: str, task_name: str
    ) -> SimulationTaskInfo:
        simset = await self._simulation_set(set_name)
        if task_name not in await self.list_simulation_set_tasks(set_name):
            raise BackendError(
                "NOT_FOUND",
                f"Simulation task '{task_name}' was not found.",
                self.name,
                "get_simulation_task_parameters",
                {"sim_set_name": set_name, "task_name": task_name},
            )
        task = await self.adapter.call(simset, "task", task_name)
        values = await self.adapter.call(task, "parameters")
        values = dict(values or {})
        return SimulationTaskInfo(
            task_name,
            None if values.get("namespace") is None else str(values.get("namespace")),
            None if values.get("controlgroup") is None else str(values.get("controlgroup")),
            None if values.get("volley") is None else int(values.get("volley")),
            None if values.get("affinity") is None else int(values.get("affinity")),
        )

    async def run_simulation_set(self, project_name: str, set_name: str) -> None:
        simset = await self._simulation_set(set_name)
        await self.adapter.call(simset, "run", timeout=300.0)

    async def add_task_to_set(
        self, project_name: str, set_name: str, task_project_name: str
    ) -> None:
        simset = await self._simulation_set(set_name)
        await self.adapter.call(simset, "add_tasks", task_project_name)
        if task_project_name not in await self.list_simulation_set_tasks(set_name):
            raise BackendError(
                "POSTCONDITION_FAILED",
                "Added simulation task was not found after the command.",
                self.name,
                "add_task_to_set",
                {"sim_set_name": set_name, "task_project_name": task_project_name},
            )

    async def remove_tasks_from_set(
        self, set_name: str, task_names: Sequence[str]
    ) -> None:
        simset = await self._simulation_set(set_name)
        before = await self.list_simulation_set_tasks(set_name)
        missing = [name for name in task_names if name not in before]
        if missing:
            raise BackendError(
                "NOT_FOUND",
                "One or more simulation tasks were not found.",
                self.name,
                "remove_tasks_from_set",
                {"sim_set_name": set_name, "missing": missing},
            )
        await self.adapter.call(simset, "remove_tasks", *task_names)
        remaining = set(await self.list_simulation_set_tasks(set_name))
        unexpected = [name for name in task_names if name in remaining]
        if unexpected:
            raise BackendError(
                "POSTCONDITION_FAILED",
                "Removed simulation tasks are still present.",
                self.name,
                "remove_tasks_from_set",
                {"sim_set_name": set_name, "remaining": unexpected},
            )

    async def set_simulation_task_parameters(
        self, set_name: str, task_name: str, parameters: Mapping[str, Any]
    ) -> SimulationTaskInfo:
        original_record = await self.get_simulation_task_parameters(set_name, task_name)
        unsupported = [
            key for key in parameters
            if key not in self._TASK_PARAMETER_ORDER
            or getattr(original_record, key, None) is None
        ]
        if unsupported:
            code = "CAPABILITY_UNAVAILABLE" if all(
                key in self._TASK_PARAMETER_ORDER for key in unsupported
            ) else "INVALID_ARGUMENT"
            raise BackendError(
                code,
                "Task parameters are unavailable." if code == "CAPABILITY_UNAVAILABLE" else "Unsupported task parameters.",
                self.name,
                "set_simulation_task_parameters",
                {"sim_set_name": set_name, "task_name": task_name, "unsupported": unsupported},
            )
        original = {key: getattr(original_record, key) for key in parameters}
        simset = await self._simulation_set(set_name)
        task = await self.adapter.call(simset, "task", task_name)
        try:
            await self.adapter.call(task, "parameters", **dict(parameters))
            observed = await self.get_simulation_task_parameters(set_name, task_name)
            mismatches = {
                key: getattr(observed, key)
                for key, expected in parameters.items()
                if getattr(observed, key) != expected
            }
            if mismatches:
                raise BackendError(
                    "POSTCONDITION_FAILED",
                    "Task parameter read-back differed.",
                    self.name,
                    "set_simulation_task_parameters",
                    {"expected": dict(parameters), "observed": mismatches},
                )
            return observed
        except Exception as operation_error:
            restore_error = None
            try:
                await self.adapter.call(task, "parameters", **original)
            except Exception as error:
                restore_error = type(error).__name__
            final = await self.get_simulation_task_parameters(set_name, task_name)
            unrestored = {
                key: getattr(final, key)
                for key, value in original.items()
                if getattr(final, key) != value
            }
            if restore_error is not None or unrestored:
                raise BackendError(
                    "PARTIAL_COMPLETION",
                    "Task parameters could not be restored.",
                    self.name,
                    "set_simulation_task_parameters",
                    {
                        "requested": dict(parameters),
                        "original": original,
                        "observed": {key: getattr(final, key) for key in original},
                        "restore_error": restore_error,
                    },
                ) from operation_error
            raise

    async def read_output_file(
        self,
        file_path: str,
        max_samples: int,
        *,
        channel: str | None = None,
        summary_only: bool = False,
    ) -> dict[str, Any]:
        return await self.adapter.read_psout(
            file_path,
            max_samples=max_samples,
            channel=channel,
            summary_only=summary_only,
        )

    async def _component(self, project_name: str, component_id: int) -> Any:
        return await self.adapter.call(
            await self._project(project_name), "component", component_id
        )

    async def _canvas(self, project_name: str, canvas_name: str) -> Any:
        return await self.adapter.call(
            await self._project(project_name), "canvas", canvas_name
        )

    async def inspect_canvas_topology(
        self, project_name: str, canvas_name: str
    ) -> TopologySnapshot:
        project = await self._project(project_name)
        definitions, definitions_supported = await self._topology_definitions(
            project, project_name
        )
        captures, unresolved = await self._topology_canvas_captures(
            project,
            project_name,
            canvas_name,
            definitions,
        )
        source_fingerprint = canonical_sha256(
            tuple(
                (capture["key"], capture["inventory"])
                for capture in captures
            )
        )
        observed_at_ns = time.time_ns()
        evidence = lambda reference: (
            EvidenceRef(
                "live",
                reference,
                fingerprint=source_fingerprint,
                observed_at_ns=observed_at_ns,
            ),
        )

        canvases = []
        components = []
        conductors = []
        labels = []
        boundary_links = []
        ports_supported = True
        conductors_supported = True
        captured_keys = {capture["key"] for capture in captures}
        for capture in captures:
            canvas_key = capture["key"]
            page_ports = capture["page_ports"]
            canvases.append(
                TopologyCanvas(
                    key=canvas_key,
                    name=capture["name"],
                    parent_key=capture["parent_key"],
                    page_ports=tuple(
                        f"{canvas_key}:{port.name}" for port in page_ports
                    ),
                )
            )
            canvas_components = []
            for value in sorted(
                capture["values"], key=self._topology_object_id
            ):
                object_id = self._topology_object_id(value)
                key = f"{canvas_key}:{object_id}"
                definition = await self._topology_definition(value)
                location = await self._topology_location(value)
                lowered_definition = definition.casefold()
                if self._is_topology_conductor(lowered_definition):
                    vertices = await self._topology_vertices(value)
                    if vertices is None:
                        conductors_supported = False
                        unresolved.add(
                            f"conductor_geometry_unreadable:{key}"
                        )
                        continue
                    conductors.append(
                        TopologyConductor(
                            key=key,
                            canvas_key=canvas_key,
                            object_id=object_id,
                            kind=(
                                "bus"
                                if "bus" in lowered_definition
                                else "wire"
                            ),
                            namespace=self._topology_namespace(
                                value, lowered_definition
                            ),
                            vertices=vertices,
                            evidence=evidence(key),
                        )
                    )
                    continue
                parameters = await self._topology_parameters(value)
                if self._is_topology_label(lowered_definition):
                    labels.append(
                        TopologyLabel(
                            key=key,
                            canvas_key=canvas_key,
                            object_id=object_id,
                            name=self._topology_name(value, parameters),
                            namespace=(
                                "data"
                                if "datalabel" in lowered_definition
                                else "electrical"
                            ),
                            scope=canvas_key,
                            location=location,
                            evidence=evidence(key),
                        )
                    )
                    continue
                ports_method = getattr(value, "ports", None)
                if ports_method is None:
                    ports_supported = False
                    raw_ports = {}
                else:
                    raw_ports = await self.executor.run_safe(ports_method)
                ports = tuple(
                    sorted(
                        (
                            TopologyPort(
                                key=f"{key}:{name}",
                                component_key=key,
                                name=str(getattr(port, "name", name)),
                                absolute=(int(port.x), int(port.y)),
                                kind=self._port_namespace(
                                    getattr(port, "type", None)
                                ),
                                dimension=self._optional_int(
                                    getattr(port, "dim", None)
                                ),
                                evidence=evidence(f"{key}:{name}"),
                            )
                            for name, port in dict(raw_ports or {}).items()
                        )
                        ,
                        key=lambda item: item.key,
                    ),
                )
                component = TopologyComponent(
                        key=key,
                        canvas_key=canvas_key,
                        object_id=object_id,
                        definition=definition,
                        name=self._topology_name(value, parameters) or None,
                        location=location,
                        orientation=self._topology_orientation(parameters),
                        active=await self._topology_active(value),
                        parameters=tuple(
                            sorted(
                                (str(name), item)
                                for name, item in parameters.items()
                            )
                        ),
                        ports=ports,
                        evidence=evidence(key),
                    )
                components.append(component)
                canvas_components.append(component)
            component_by_id = {
                component.object_id: component
                for component in canvas_components
            }
            for child in capture["children"]:
                if child["key"] not in captured_keys:
                    continue
                component = component_by_id.get(child["object_id"])
                if component is None:
                    continue
                links, missing = self._topology_boundary_links(
                    component,
                    child["key"],
                    child["page_ports"],
                    evidence,
                )
                boundary_links.extend(links)
                unresolved.update(missing)

        project_path = await self._topology_project_path(project)
        dirty_available, _dirty = await self._topology_dirty_state(project)
        if project_path is None:
            unresolved.add("project_path_unavailable")
        for capture in captures:
            after_values = list(
                await self.adapter.call(capture["canvas"], "components")
            )
            after_inventory = await self._topology_inventory(after_values)
            if capture["inventory"] != after_inventory:
                raise BackendError(
                    "TOPOLOGY_SNAPSHOT_UNSTABLE",
                    "Canvas changed during topology capture.",
                    self.name,
                    "inspect_canvas_topology",
                )
        hierarchy_supported = definitions_supported and not any(
            item.startswith(
                (
                    "definition_ports_unavailable:",
                    "hierarchy_boundary_unresolved:",
                    "hierarchy_cycle:",
                    "live_hierarchy_unavailable:",
                )
            )
            for item in unresolved
        )
        return TopologySnapshot(
            source="live",
            project_name=project_name,
            project_path=project_path,
            pscad_version=self.version,
            canvases=tuple(sorted(canvases, key=lambda item: item.key)),
            components=tuple(sorted(components, key=lambda item: item.key)),
            conductors=tuple(sorted(conductors, key=lambda item: item.key)),
            labels=tuple(sorted(labels, key=lambda item: item.key)),
            boundary_links=tuple(
                sorted(boundary_links, key=lambda item: item.key)
            ),
            unresolved=tuple(sorted(unresolved)),
            capabilities=(
                ("components", True),
                ("conductors", conductors_supported),
                ("dirty_state", dirty_available),
                ("hierarchy", hierarchy_supported),
                ("labels", True),
                ("ports", ports_supported),
                ("project_path", project_path is not None),
            ),
            source_fingerprint=source_fingerprint,
            grid_step=1,
        )

    async def _topology_definitions(
        self, project: Any, project_name: str
    ) -> tuple[dict[str, Any], bool]:
        method = getattr(project, "definitions", None)
        if method is None:
            return {}, False
        values = await self.executor.run_safe(method)
        if isinstance(values, dict):
            values = values.values()
        result = {}
        for value in values or ():
            scoped = str(
                getattr(value, "scoped_name", None)
                or getattr(value, "name", None)
                or value
            )
            if ":" in scoped:
                scope, name = scoped.split(":", 1)
                if scope.casefold() != project_name.casefold():
                    continue
                result[scoped.casefold()] = value
                result[name.casefold()] = value
            else:
                result[scoped.casefold()] = value
        return result, True

    async def _topology_canvas_captures(
        self,
        project: Any,
        project_name: str,
        canvas_name: str,
        definitions: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], set[str]]:
        captures = []
        unresolved = set()
        queue = [
            {
                "name": canvas_name,
                "key": canvas_name,
                "parent_key": None,
                "ancestry": (canvas_name.casefold(),),
                "page_ports": (),
            }
        ]
        while queue:
            request = queue.pop(0)
            try:
                canvas = await self._topology_canvas(
                    project, request["name"], request["parent_key"] is None
                )
                values = list(
                    await self.adapter.call(canvas, "components")
                )
                inventory = await self._topology_inventory(values)
            except (AttributeError, BackendError, KeyError, TypeError):
                if request["parent_key"] is None:
                    raise
                unresolved.add(
                    f"live_hierarchy_unavailable:{request['key']}"
                )
                continue
            capture = {
                **request,
                "canvas": canvas,
                "values": values,
                "inventory": inventory,
                "children": [],
            }
            captures.append(capture)
            for value in sorted(values, key=self._topology_object_id):
                definition = await self._topology_definition(value)
                local_name = self._topology_local_definition_name(
                    project_name, definition, definitions
                )
                if local_name is None:
                    continue
                object_id = self._topology_object_id(value)
                child_key = f"{request['key']}/{object_id}:{local_name}"
                if local_name.casefold() in request["ancestry"]:
                    unresolved.add(f"hierarchy_cycle:{child_key}")
                    continue
                definition_proxy = (
                    definitions.get(definition.casefold())
                    or definitions.get(local_name.casefold())
                )
                page_ports = await self._topology_definition_ports(
                    definition_proxy
                )
                if not page_ports:
                    unresolved.add(
                        f"definition_ports_unavailable:{child_key}"
                    )
                child = {
                    "name": local_name,
                    "key": child_key,
                    "parent_key": request["key"],
                    "ancestry": request["ancestry"]
                    + (local_name.casefold(),),
                    "page_ports": page_ports,
                }
                capture["children"].append(
                    {
                        "object_id": object_id,
                        "key": child_key,
                        "page_ports": page_ports,
                    }
                )
                queue.append(child)
        return captures, unresolved

    async def _topology_canvas(
        self, project: Any, name: str, root: bool
    ) -> Any:
        if not root and getattr(project, "user_canvas", None) is not None:
            return await self.adapter.call(project, "user_canvas", name)
        return await self.adapter.call(project, "canvas", name)

    @staticmethod
    def _topology_local_definition_name(
        project_name: str, definition: str, definitions: dict[str, Any]
    ) -> str | None:
        local_name = definition.rsplit(":", 1)[-1]
        if ":" in definition:
            scope, _name = definition.split(":", 1)
            if scope.casefold() == project_name.casefold():
                return local_name
            return None
        if definition.casefold() in definitions:
            return local_name
        return None

    async def _topology_definition_ports(
        self, definition: Any
    ) -> tuple[DefinitionPortContract, ...]:
        if definition is None:
            return ()
        method = getattr(definition, "ports", None)
        if method is None:
            return ()
        values = await self.executor.run_safe(method)
        items = dict(values).items() if isinstance(values, dict) else enumerate(values)
        result = []
        for fallback_name, port in items:
            try:
                offset = (int(port.x), int(port.y))
            except (AttributeError, TypeError, ValueError):
                continue
            result.append(
                DefinitionPortContract(
                    name=str(getattr(port, "name", fallback_name)),
                    kind=self._port_namespace(
                        getattr(port, "type", None)
                        or getattr(port, "kind", None)
                    ),
                    dimension=self._optional_int(
                        getattr(port, "dim", None)
                        or getattr(port, "dimension", None)
                    ),
                    offset=offset,
                )
            )
        return tuple(sorted(result, key=lambda item: item.name))

    @staticmethod
    def _topology_boundary_links(
        component: TopologyComponent,
        child_canvas_key: str,
        page_ports: tuple[DefinitionPortContract, ...],
        evidence,
    ) -> tuple[list[TopologyBoundaryLink], list[str]]:
        outer_ports = {port.name: port for port in component.ports}
        links = []
        unresolved = []
        for page_port in page_ports:
            outer = outer_ports.get(page_port.name)
            key = (
                f"{component.key}:{page_port.name}->"
                f"{child_canvas_key}:{page_port.name}"
            )
            if outer is None or outer.absolute is None:
                unresolved.append(f"hierarchy_boundary_unresolved:{key}")
                continue
            links.append(
                TopologyBoundaryLink(
                    key=key,
                    outer_port_key=outer.key,
                    outer_canvas_key=component.canvas_key,
                    outer_point=outer.absolute,
                    inner_port_key=f"{child_canvas_key}:{page_port.name}",
                    inner_canvas_key=child_canvas_key,
                    inner_point=page_port.offset,
                    namespace=page_port.kind,
                    dimension=page_port.dimension,
                    evidence=evidence(key),
                )
            )
        return links, unresolved

    async def _topology_inventory(self, values: list[Any]) -> tuple[tuple, ...]:
        result = []
        for value in sorted(values, key=self._topology_object_id):
            definition = await self._topology_definition(value)
            vertices = (
                await self._topology_vertices(value)
                if self._is_topology_conductor(definition.casefold())
                else None
            )
            result.append(
                (
                    self._topology_object_id(value),
                    definition,
                    await self._topology_location(value),
                    vertices,
                )
            )
        return tuple(result)

    @staticmethod
    def _topology_object_id(value: Any) -> str:
        raw = getattr(value, "id", None)
        if raw is None:
            raw = getattr(value, "_id", (type(value).__name__,))[0]
        return str(raw)

    async def _topology_definition(self, value: Any) -> str:
        definition = str(getattr(value, "defn_name", "") or "")
        method = getattr(value, "get_definition", None)
        if not definition and method is not None:
            proxy = await self.executor.run_safe(method)
            definition = str(getattr(proxy, "scoped_name", proxy) or "")
        return definition or type(value).__name__

    async def _topology_location(self, value: Any) -> tuple[int, int] | None:
        method = getattr(value, "get_location", None)
        location = (
            await self.executor.run_safe(method)
            if method is not None
            else getattr(value, "location", None)
        )
        if location is None:
            return None
        return int(location[0]), int(location[1])

    async def _topology_parameters(self, value: Any) -> dict[str, Any]:
        method = getattr(value, "parameters", None)
        if method is None:
            method = getattr(value, "get_parameters", None)
        if method is None:
            return {}
        return dict(await self.executor.run_safe(method) or {})

    async def _topology_active(self, value: Any) -> bool:
        candidate = getattr(value, "is_enabled", None)
        if candidate is None:
            return bool(getattr(value, "enabled", True))
        return bool(
            await self.executor.run_safe(candidate) if callable(candidate) else candidate
        )

    async def _topology_vertices(
        self, value: Any
    ) -> tuple[tuple[int, int], ...] | None:
        raw_vertices = getattr(value, "vertices", None)
        if callable(raw_vertices):
            raw_vertices = await self.executor.run_safe(raw_vertices)
        if raw_vertices is None:
            return None
        try:
            raw = tuple((int(point[0]), int(point[1])) for point in raw_vertices)
        except (TypeError, ValueError, IndexError):
            return None
        if len(raw) < 2:
            return None
        location = await self._topology_location(value)
        relative = (
            tuple((location[0] + x, location[1] + y) for x, y in raw)
            if location is not None
            else raw
        )
        endpoints_method = getattr(value, "endpoints", None)
        if endpoints_method is None:
            return relative if raw[0] == (0, 0) and location is not None else raw
        endpoints = await self.executor.run_safe(endpoints_method)
        try:
            expected = tuple((int(point.x), int(point.y)) for point in endpoints)
        except (AttributeError, TypeError, ValueError):
            return None
        for candidate in (raw, relative):
            if expected and candidate[0] == expected[0] and candidate[-1] == expected[-1]:
                return candidate
        return None

    async def _topology_project_path(self, project: Any) -> str | None:
        for name in ("filename", "path"):
            value = getattr(project, name, None)
            if callable(value):
                value = await self.executor.run_safe(value)
            if value:
                return str(value)
        return None

    async def _topology_dirty_state(self, project: Any) -> tuple[bool, bool | None]:
        for name in ("dirty", "is_dirty"):
            value = getattr(project, name, None)
            if value is None:
                continue
            if callable(value):
                value = await self.executor.run_safe(value)
            return True, bool(value)
        return False, None

    async def _has_local_topology_definitions(self, project: Any) -> bool:
        method = getattr(project, "definitions", None)
        if method is None:
            return False
        values = await self.executor.run_safe(method)
        return bool(values)

    @staticmethod
    def _is_topology_conductor(definition: str) -> bool:
        return "wire" in definition or definition == "bus" or definition.endswith(":bus")

    @staticmethod
    def _is_topology_label(definition: str) -> bool:
        return "nodelabel" in definition or "datalabel" in definition

    @staticmethod
    def _topology_namespace(value: Any, definition: str) -> str:
        raw = str(
            getattr(value, "namespace", None)
            or getattr(value, "kind", None)
            or ""
        ).casefold()
        if raw in {"data", "signal", "digital"} or "data" in definition:
            return "data"
        return "electrical"

    @staticmethod
    def _port_namespace(value: Any) -> str:
        raw = str(value or "").casefold()
        if raw in {"electrical", "power", "analog", "node"}:
            return "electrical"
        if raw in {"data", "signal", "digital"}:
            return "data"
        return "unknown"

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _topology_orientation(cls, parameters: Mapping[str, Any]) -> int | None:
        for name, value in parameters.items():
            if str(name).casefold() in {"orient", "orientation"}:
                return cls._optional_int(value)
        return None

    @staticmethod
    def _topology_name(value: Any, parameters: Mapping[str, Any]) -> str:
        for name, item in parameters.items():
            if str(name).casefold() == "name":
                return str(item)
        return str(getattr(value, "name", "") or "")

    async def _component_info(self, component: Any) -> ComponentInfo:
        location_method = getattr(component, "get_location", None)
        location = (
            await self.executor.run_safe(location_method)
            if location_method is not None
            else getattr(component, "location")
        )
        return ComponentInfo(
            int(component.id),
            str(getattr(component, "name", "")),
            str(getattr(component, "defn_name", "")),
            {"x": int(location[0]), "y": int(location[1])},
        )

    async def find_components(
        self,
        project_name: str,
        canvas_name: str,
        definition: str | None,
        name: str | None,
    ) -> list[ComponentInfo]:
        project = await self._project(project_name)
        components = await self.adapter.call(
            project, "find_all", definition=definition, name=name
        )
        return [await self._component_info(component) for component in components]

    async def get_component_parameters(
        self, project_name: str, component_id: int
    ) -> dict[str, Any]:
        values = await self.adapter.call(
            await self._component(project_name, component_id), "parameters"
        )
        return dict(values or {})

    async def set_component_parameters(
        self, project_name: str, component_id: int, parameters: Any
    ) -> None:
        await self.adapter.call(
            await self._component(project_name, component_id),
            "parameters",
            parameters=dict(parameters),
        )

    async def component_parameter_range(
        self, project_name: str, component_id: int, parameter_name: str
    ) -> Any:
        return await self.adapter.call(
            await self._component(project_name, component_id),
            "range",
            parameter_name,
        )

    async def get_component_location(
        self, project_name: str, component_id: int
    ) -> tuple[int, int]:
        component = await self._component(project_name, component_id)
        method = getattr(component, "get_location", None)
        value = (
            await self.executor.run_safe(method)
            if method is not None
            else getattr(component, "location")
        )
        return int(value[0]), int(value[1])

    async def set_component_location(
        self, project_name: str, component_id: int, location: tuple[int, int]
    ) -> None:
        component = await self._component(project_name, component_id)
        await self.adapter.call(component, "set_location", *location)
        if await self.get_component_location(project_name, component_id) != location:
            raise BackendError(
                "POSTCONDITION_FAILED",
                f"Component {component_id} did not move to {location}.",
                self.name,
                "set_component_location",
            )

    async def rotate_component(
        self, project_name: str, component_id: int, direction: str
    ) -> None:
        methods = {"right": "rotate_right", "left": "rotate_left", "180": "rotate_180"}
        if direction not in methods:
            raise ValueError("direction must be right, left, or 180.")
        await self.adapter.call(
            await self._component(project_name, component_id), methods[direction]
        )

    async def mirror_component(
        self, project_name: str, component_id: int, axis: str
    ) -> None:
        methods = {"horizontal": "mirror", "vertical": "flip"}
        if axis not in methods:
            raise ValueError("axis must be horizontal or vertical.")
        await self.adapter.call(
            await self._component(project_name, component_id), methods[axis]
        )

    async def clone_component(
        self, project_name: str, component_id: int, location: tuple[int, int]
    ) -> ComponentInfo:
        clone = await self.adapter.call(
            await self._component(project_name, component_id),
            "clone",
            *location,
        )
        info = await self._component_info(clone)
        if info.id == component_id or info.location != {"x": location[0], "y": location[1]}:
            raise BackendError(
                "POSTCONDITION_FAILED",
                "Cloned component identity or location could not be verified.",
                self.name,
                "clone_component",
            )
        return info

    async def get_component_ports(
        self, project_name: str, component_id: int
    ) -> list[PortInfo]:
        component = await self._component(project_name, component_id)
        values = await self.adapter.call(component, "ports")
        return [
            PortInfo(
                str(name),
                int(port.x),
                int(port.y),
                getattr(port, "dim", None),
                str(getattr(port, "type", "")) or None,
            )
            for name, port in values.items()
        ]

    async def set_component_enabled(
        self, project_name: str, component_id: int, enabled: bool
    ) -> None:
        component = await self._component(project_name, component_id)
        await self.adapter.call(component, "enable" if enabled else "disable")

    async def delete_component(self, project_name: str, component_id: int) -> None:
        await self.delete_components(project_name, [component_id])

    async def delete_components(
        self, project_name: str, component_ids: Sequence[int]
    ) -> None:
        unique_ids = list(dict.fromkeys(int(value) for value in component_ids))
        if not unique_ids:
            raise ValueError("component_ids must not be empty.")
        components = [
            await self._component(project_name, component_id)
            for component_id in unique_ids
        ]
        for component in components:
            await self.adapter.call(component, "delete")

    async def add_component(
        self,
        project_name: str,
        canvas_name: str,
        library: str,
        definition: str,
        location: tuple[int, int],
        orientation: int,
        parameters: Any,
    ) -> ComponentInfo:
        canvas = await self._canvas(project_name, canvas_name)
        component = await self.adapter.call(
            canvas,
            "add_component",
            library,
            definition,
            *location,
            orientation,
            **dict(parameters),
        )
        return await self._component_info(component)

    @staticmethod
    def _endpoints_payload(object_id: int, points: Any) -> dict[str, Any]:
        return {
            "id": int(object_id),
            "endpoints": [list(points[0]), list(points[-1])],
        }

    async def create_wire(
        self, project_name: str, canvas_name: str, points: Any
    ) -> dict[str, Any]:
        vertices = [tuple(point) for point in points]
        if len(vertices) < 2:
            raise ValueError("At least two wire vertices are required.")
        wire = await self.adapter.call(
            await self._canvas(project_name, canvas_name),
            "create_wire",
            *vertices,
        )
        return self._endpoints_payload(wire.id, vertices)

    async def create_bus(
        self,
        project_name: str,
        canvas_name: str,
        points: Any,
        parameters: Any,
    ) -> dict[str, Any]:
        vertices = [tuple(point) for point in points]
        if len(vertices) < 2:
            raise ValueError("At least two bus vertices are required.")
        bus = await self.adapter.call(
            await self._canvas(project_name, canvas_name),
            "create_bus",
            *vertices,
        )
        if parameters:
            await self.adapter.call(
                bus, "parameters", parameters=dict(parameters)
            )
        return self._endpoints_payload(bus.id, vertices)

    async def create_connection(
        self,
        project_name: str,
        canvas_name: str,
        p1: tuple[int, int],
        p2: tuple[int, int],
        label: str | None,
        electrical: bool | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if label is not None:
            kwargs["label"] = label
        if electrical is not None:
            kwargs["electrical"] = electrical
        result = await self.adapter.call(
            await self._canvas(project_name, canvas_name),
            "create_connection",
            p1,
            p2,
            **kwargs,
        )
        return {"label": str(result)} if result else {"connected": True}

    async def create_annotation(
        self,
        project_name: str,
        canvas_name: str,
        location: tuple[int, int],
        line1: str,
        line2: str,
    ) -> ComponentInfo:
        component = await self.adapter.call(
            await self._canvas(project_name, canvas_name),
            "create_annotation",
            *location,
            line1,
            line2,
        )
        return await self._component_info(component)

    async def create_graph_frame(
        self, project_name: str, canvas_name: str, location: tuple[int, int]
    ) -> dict[str, Any]:
        frame = await self.adapter.call(
            await self._canvas(project_name, canvas_name),
            "create_graph_frame",
            *location,
        )
        return {"id": int(frame.id)}

    async def create_control_frame(
        self, project_name: str, canvas_name: str, location: tuple[int, int]
    ) -> dict[str, Any]:
        frame, controls = await self.adapter.call(
            await self._canvas(project_name, canvas_name),
            "create_control_frame",
            *location,
        )
        return {
            "frame_id": int(frame.id),
            "control_ids": [int(control.id) for control in controls],
        }

    async def list_canvas_components(
        self, project_name: str, canvas_name: str
    ) -> list[dict[str, Any]]:
        values = await self.adapter.call(
            await self._canvas(project_name, canvas_name), "components"
        )
        result = []
        for value in values:
            location_method = getattr(value, "get_location", None)
            location = (
                await self.executor.run_safe(location_method)
                if location_method is not None
                else getattr(value, "location", None)
            )
            result.append(
                {
                    "id": int(value.id),
                    "name": str(getattr(value, "name", "")) or None,
                    "definition": str(getattr(value, "defn_name", "")) or None,
                    "location": list(location) if location is not None else None,
                    "orientation": getattr(value, "orientation", getattr(value, "orient", None)),
                }
            )
        return result

    async def find_empty_space(
        self,
        project_name: str,
        canvas_name: str,
        width: int,
        height: int,
        near: tuple[int, int],
    ) -> dict[str, int]:
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be positive.")
        rectangle = await self.adapter.call(
            await self._canvas(project_name, canvas_name),
            "closest_empty_rect",
            width,
            height,
            near,
        )
        return {
            "x": int(rectangle.x),
            "y": int(rectangle.y),
            "width": int(rectangle.width),
            "height": int(rectangle.height),
        }
