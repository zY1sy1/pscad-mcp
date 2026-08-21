"""Version-independent service boundary used by MCP tools."""

from __future__ import annotations

import asyncio
import math
import os
import re
from collections.abc import Mapping
from dataclasses import asdict
import inspect
from pathlib import Path
from typing import Any, Awaitable, Callable

from .backend.base import BackendError, BackendInfo, ParameterGridRequest
from .executor import (
    ExecutorTimeoutError,
    ExecutorUnhealthyError,
    robust_executor,
)
from .path_policy import PathPolicy, WorkspaceNotConfiguredError


BackendFactory = Callable[[], Any | Awaitable[Any]]
_ERROR_TEXT_LIMIT = 512
_DEFAULT_ERROR_GUIDANCE = (
    False,
    "Inspect get_pscad_status and server logs before retrying.",
)
_ERROR_GUIDANCE: dict[str, tuple[bool, str]] = {
    "ALREADY_EXISTS": (
        False,
        "Choose a different name or inspect the existing PSCAD object.",
    ),
    "CAPABILITY_UNAVAILABLE": (
        False,
        "Use a supported PSCAD 4.6 operation or adjust the requested workflow.",
    ),
    "CONFIRMATION_REQUIRED": (
        False,
        "Review the destructive operation, then call it again with confirm=true.",
    ),
    "DEPENDENCY_MISSING": (
        False,
        "Install the required PSCAD 4.6 Automation Library dependency.",
    ),
    "EXTERNAL_PSCAD_PRESENT": (
        False,
        "Close the existing PSCAD GUI, then let MCP launch a managed instance; "
        "or explicitly set PSCAD_MCP_LEGACY_EXISTING_POLICY=allow.",
    ),
    "EXECUTOR_UNHEALTHY": (
        True,
        "Call repair_connection before retrying the operation.",
    ),
    "INTERNAL_ERROR": _DEFAULT_ERROR_GUIDANCE,
    "INVALID_ARGUMENT": (
        False,
        "Correct the argument values and retry the operation.",
    ),
    "LEARNING_UNAVAILABLE": (
        False,
        "Local learning state is unavailable.",
    ),
    "WORKSPACE_NOT_CONFIGURED": (
        False,
        "Set PSCAD_MCP_WORKSPACE, then retry the file operation.",
    ),
    "NOT_CONNECTED": (
        True,
        "Call get_local_pscad or repair_connection before retrying.",
    ),
    "NOT_FOUND": (
        False,
        "Check names and list the current PSCAD objects.",
    ),
    "NOT_LICENSED": (
        False,
        "Activate or verify the PSCAD license before retrying the simulation.",
    ),
    "PARTIAL_COMPLETION": (
        False,
        "Inspect details and the current PSCAD state before retrying.",
    ),
    "POSTCONDITION_FAILED": (
        False,
        "Inspect details and verify the PSCAD project state before retrying.",
    ),
    "PSCAD_COMMAND_FAILED": (
        False,
        "Inspect error details and PSCAD project output before retrying.",
    ),
    "REPAIR_CLEANUP_FAILED": (
        False,
        "Close the owned PSCAD process manually, then call repair_connection.",
    ),
    "RUN_CONTROL_SCOPE_CONFLICT": (
        False,
        "Stop or finish the other active PSCAD projects, then retry with only "
        "the requested project active.",
    ),
    "RUN_NOT_ACTIVE": (
        False,
        "Run the requested project and wait for an active state before retrying.",
    ),
    "TIMEOUT": (
        True,
        "Call get_pscad_status, then repair_connection before retrying.",
    ),
    "HVDC_PROFILE_NOT_FOUND": (
        False,
        "Call list_hvdc_profiles or register a workspace-scoped profile.",
    ),
    "HVDC_TOPOLOGY_AMBIGUOUS": (
        False,
        "Inspect the evidence and provide an explicit HVDC profile.",
    ),
    "HVDC_RETURN_PATH_UNRESOLVED": (
        False,
        "Inspect the return-path evidence and provide a project-qualified profile.",
    ),
    "HVDC_MAPPING_MISSING": (
        False,
        "Add or configure the missing mapped channels/components before retrying.",
    ),
    "HVDC_MAPPING_CONFLICT": (
        False,
        "Remove duplicate aliases or correct the unit mapping before retrying.",
    ),
    "HVDC_SCENARIO_INVALID": (
        False,
        "Correct the declarative scenario and retry validation.",
    ),
    "HVDC_CAPABILITY_UNAVAILABLE": (
        False,
        "Use an existing mapped control; component insertion is not supported.",
    ),
    "INCOMPLETE_ANALYSIS": (
        False,
        "Map the required result channels and rerun the analysis.",
    ),
}


_TASK_PARAMETER_FIELDS = frozenset({"controlgroup", "volley", "affinity"})
_PARAMETER_GRID_FIELDS = frozenset(
    {"action", "project_name", "filename", "folder"}
)
_PARAMETER_GRID_ACTIONS = frozenset({"view_project", "load", "save"})


def _require_object_name(value: str, field: str, operation: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BackendError(
            "INVALID_ARGUMENT",
            f"{field} must be a non-empty string.",
            "service",
            operation,
            {"field": field},
        )
    return value


def _validated_task_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(parameters, dict) or not parameters:
        raise BackendError(
            "INVALID_ARGUMENT",
            "parameters must not be empty.",
            "service",
            "set_simulation_task_parameters",
        )
    if "namespace" in parameters:
        raise BackendError(
            "INVALID_ARGUMENT",
            "namespace is read-only.",
            "service",
            "set_simulation_task_parameters",
            {"read_only": ["namespace"]},
        )
    unsupported = sorted(set(parameters) - _TASK_PARAMETER_FIELDS)
    if unsupported:
        raise BackendError(
            "INVALID_ARGUMENT",
            "Unsupported task parameters.",
            "service",
            "set_simulation_task_parameters",
            {"unsupported": unsupported},
        )
    for key in ("volley", "affinity"):
        if key in parameters and (
            isinstance(parameters[key], bool)
            or not isinstance(parameters[key], int)
            or parameters[key] < 1
        ):
            raise BackendError(
                "INVALID_ARGUMENT",
                f"{key} must be an integer >= 1.",
                "service",
                "set_simulation_task_parameters",
                {"field": key},
            )
    if "controlgroup" in parameters and not isinstance(parameters["controlgroup"], str):
        raise BackendError(
            "INVALID_ARGUMENT",
            "controlgroup must be a string.",
            "service",
            "set_simulation_task_parameters",
            {"field": "controlgroup"},
        )
    return dict(parameters)


def _bounded_error_text(error: BaseException) -> str:
    value = f"{type(error).__name__}: {error}"
    if len(value) <= _ERROR_TEXT_LIMIT:
        return value
    return value[: _ERROR_TEXT_LIMIT - 3] + "..."


def _bounded_message(error: BaseException) -> str:
    value = str(error)
    if len(value) <= _ERROR_TEXT_LIMIT:
        return value
    return value[: _ERROR_TEXT_LIMIT - 3] + "..."


def _with_error_guidance(payload: dict[str, Any]) -> dict[str, Any]:
    retryable, suggested_action = _ERROR_GUIDANCE.get(
        str(payload.get("code")),
        _DEFAULT_ERROR_GUIDANCE,
    )
    payload["retryable"] = retryable
    payload["suggested_action"] = suggested_action
    return payload


class ConfirmationRequired(BackendError):
    def __init__(self, operation: str) -> None:
        super().__init__(
            "CONFIRMATION_REQUIRED",
            f"{operation} is destructive; call it again with confirm=true.",
            "service",
            operation,
        )


class PscadService:
    """Own backend selection, lifecycle, safety, and JSON normalization."""

    def __init__(
        self,
        backend_factory: BackendFactory,
        *,
        executor: Any = robust_executor,
        path_policy: PathPolicy | None = None,
    ) -> None:
        self._backend_factory = backend_factory
        self.executor = executor
        self.path_policy = path_policy or PathPolicy()
        self._backend: Any = None
        self._mutation_lock = asyncio.Lock()

    @property
    def backend(self) -> Any:
        if self._backend is None:
            raise RuntimeError("PSCAD is not connected. Call get_local_pscad first.")
        return self._backend

    def _resolve_path(
        self,
        candidate: str,
        *,
        suffixes: set[str],
        must_exist: bool = False,
        operation: str,
    ) -> Path:
        try:
            return self.path_policy.resolve(
                candidate,
                suffixes=suffixes,
                must_exist=must_exist,
            )
        except WorkspaceNotConfiguredError as error:
            raise BackendError(
                "WORKSPACE_NOT_CONFIGURED",
                str(error),
                "service",
                operation,
                {
                    "candidate": candidate,
                    "candidate_is_relative": not Path(candidate).expanduser().is_absolute(),
                    "environment": "PSCAD_MCP_WORKSPACE",
                    "allow_override": "PSCAD_MCP_ALLOW_UNSCOPED_PATHS",
                },
            ) from error

    async def _select_backend(self) -> Any:
        if self._backend is None:
            candidate = self._backend_factory()
            self._backend = (
                await candidate if inspect.isawaitable(candidate) else candidate
            )
            if self._backend is None:
                raise RuntimeError("The PSCAD backend factory returned no backend.")
        return self._backend

    async def attach_local(self) -> str:
        backend = await self._select_backend()
        try:
            info = await backend.attach()
        except BaseException:
            if self._backend is backend:
                self._backend = None
            raise
        architecture = "x64" if info.x64 else "x86"
        if info.backend == "legacy":
            session = getattr(backend, "session_details", None)
            minimized = bool(
                session.get("legacy_minimize", False)
                if isinstance(session, Mapping)
                else False
            )
            launch_mode = "minimized managed" if minimized else "visible managed"
            return (
                f"Successfully launched a {launch_mode} PSCAD automation instance using "
                f"legacy backend for PSCAD {info.version} ({architecture}); legacy "
                "automation does not attach to an already-open GUI."
            )
        return (
            f"Successfully attached using {info.backend} backend to "
            f"PSCAD {info.version} ({architecture})."
        )

    def executor_status(self) -> dict[str, Any]:
        """Return a bounded snapshot of the shared COM executor."""
        return dict(self.executor.snapshot())

    def learning_snapshot(self) -> dict[str, str | None]:
        backend = self._backend
        if backend is None:
            return {"backend": None, "pscad_version": None}
        return {
            "backend": getattr(backend, "name", None),
            "pscad_version": getattr(backend, "version", None),
        }

    async def status(self) -> dict[str, Any]:
        if self._backend is None:
            return {
                "connected": False,
                "backend": None,
                "version": None,
                "selected_version": None,
                "x64": None,
                "alive": False,
                "busy": False,
                "licensed": None,
                "owns_process": False,
                "executor": self.executor_status(),
            }
        info: BackendInfo = await self._backend.heartbeat()
        payload = asdict(info)
        payload["connected"] = bool(info.alive)
        payload["selected_version"] = info.version
        payload["executor"] = self.executor_status()
        session = getattr(self._backend, "session_details", None)
        if isinstance(session, Mapping):
            payload["session"] = dict(session)
        return payload

    async def disconnect(self) -> None:
        if self._backend is not None:
            await self._backend.disconnect()
        self._backend = None

    async def repair_connection(self) -> str:
        async with self._mutation_lock:
            return await self._repair_connection_unlocked()

    async def _repair_connection_unlocked(self) -> str:
        current = self._backend
        if current is not None:
            owns_process = bool(getattr(current, "owns_process", False))
            executor_was_unhealthy = not bool(
                getattr(self.executor, "healthy", True)
            )
            if owns_process:
                if executor_was_unhealthy:
                    self.executor.reset()
                try:
                    await current.quit()
                except Exception as cleanup_error:
                    if not executor_was_unhealthy:
                        raise
                    details = {
                        "cleanup_error": _bounded_error_text(cleanup_error),
                    }
                    try:
                        await current.disconnect()
                    except Exception as disconnect_error:
                        details["disconnect_error"] = _bounded_error_text(
                            disconnect_error
                        )
                    self._backend = None
                    self.executor.reset()
                    raise BackendError(
                        "REPAIR_CLEANUP_FAILED",
                        "The owned PSCAD process could not be closed after an "
                        "executor timeout. Close it manually, then call "
                        "repair_connection again.",
                        str(getattr(current, "name", "legacy")),
                        "repair_connection",
                        details,
                    ) from cleanup_error
            else:
                await current.disconnect()
            self._backend = None
        self.executor.reset()
        return await self.attach_local()

    async def quit_pscad(self, *, confirm: bool = False) -> str:
        if not confirm:
            raise ConfirmationRequired("quit_pscad")
        backend = self.backend
        await backend.quit()
        self._backend = None
        return "PSCAD terminated."

    async def load_projects(self, filenames: list[str]) -> str:
        if not filenames:
            raise ValueError("filenames must contain at least one project.")
        resolved = [
            str(
                self._resolve_path(
                    filename,
                    suffixes={".pscx", ".pslx", ".pswx"},
                    must_exist=True,
                    operation="load_projects",
                )
            )
            for filename in filenames
        ]
        await self.backend.load_projects(resolved)
        return f"Loaded: {', '.join(resolved)}"

    async def list_projects(self) -> list[dict[str, Any]]:
        return [asdict(item) for item in await self.backend.list_projects()]

    async def run_project(self, project_name: str) -> str:
        async with self._mutation_lock:
            info = await self.backend.heartbeat()
            if info.licensed is False:
                raise BackendError(
                    "NOT_LICENSED",
                    "PSCAD is not licensed; simulation was not started.",
                    getattr(self.backend, "name", "backend"),
                    "run_project",
                    {"project_name": project_name},
                )
            await self.backend.run_project(project_name)
            return f"Simulation started for '{project_name}'."

    async def get_timed_control_capabilities(self, project_name: str) -> dict[str, Any]:
        return await self.backend.get_timed_control_capabilities(project_name)

    async def schedule_timed_controls(self, project_name: str, events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return await self.backend.schedule_timed_controls(project_name, events)

    async def get_simulation_time(self, project_name: str) -> float:
        return await self.backend.get_simulation_time(project_name)

    async def get_run_status(self, project_name: str) -> dict[str, Any]:
        return asdict(await self.backend.project_run_state(project_name))

    async def pause_simulation(self, project_name: str) -> str:
        async with self._mutation_lock:
            await self.backend.pause_project(project_name)
            return f"Simulation paused for '{project_name}'."

    async def stop_simulation(self, project_name: str) -> str:
        async with self._mutation_lock:
            await self.backend.stop_project(project_name)
            return f"Simulation stopped for '{project_name}'."

    async def parameter_grid(
        self, request: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise BackendError(
                "INVALID_ARGUMENT",
                "parameter_grid must be a mapping.",
                "service",
                "parameter_grid",
            )
        unknown = sorted(set(request) - _PARAMETER_GRID_FIELDS)
        if unknown:
            raise BackendError(
                "INVALID_ARGUMENT",
                "Unsupported parameter-grid fields.",
                "service",
                "parameter_grid",
                {"unsupported": unknown},
            )
        action = request.get("action")
        if action not in _PARAMETER_GRID_ACTIONS:
            raise BackendError(
                "INVALID_ARGUMENT",
                "action must be one of: view_project, load, save.",
                "service",
                "parameter_grid",
                {"action": action},
            )
        project_name = request.get("project_name")
        filename = request.get("filename")
        folder = request.get("folder")
        if action == "view_project":
            if not isinstance(project_name, str) or not project_name.strip():
                raise BackendError(
                    "INVALID_ARGUMENT",
                    "project_name is required for view_project.",
                    "service",
                    "parameter_grid",
                )
            if filename is not None or folder is not None:
                raise BackendError(
                    "INVALID_ARGUMENT",
                    "filename and folder are not valid for view_project.",
                    "service",
                    "parameter_grid",
                )
            normalized = ParameterGridRequest(
                action,
                project_name.strip(),
                None,
                None,
            )
        else:
            if not isinstance(filename, str) or not filename.strip():
                raise BackendError(
                    "INVALID_ARGUMENT",
                    f"filename is required for {action}.",
                    "service",
                    "parameter_grid",
                )
            if folder is not None and not isinstance(folder, str):
                raise BackendError(
                    "INVALID_ARGUMENT",
                    "folder must be a string when provided.",
                    "service",
                    "parameter_grid",
                )
            candidate = str(Path(folder) / filename) if folder else filename
            resolved = self._resolve_path(
                candidate,
                suffixes={".csv"},
                must_exist=action == "load",
                operation="parameter_grid",
            )
            normalized = ParameterGridRequest(
                action,
                None,
                str(resolved),
                None,
            )
        return await self.backend.parameter_grid(normalized)

    async def get_project_settings(
        self,
        project_name: str,
        mode: str = "project",
        parameter_grid: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if mode == "parameter_grid":
            request = dict(parameter_grid or {})
            request.setdefault("action", "view_project")
            request.setdefault("project_name", project_name)
            return await self.parameter_grid(request)
        if mode != "project":
            raise BackendError(
                "INVALID_ARGUMENT",
                "mode must be 'project' or 'parameter_grid'.",
                "service",
                "get_project_settings",
                {"mode": mode},
            )
        return await self.backend.get_settings(project_name)

    async def set_project_settings(
        self,
        project_name: str,
        settings: dict[str, Any],
        mode: str = "project",
        parameter_grid: Mapping[str, Any] | None = None,
    ) -> str | dict[str, Any]:
        if mode == "parameter_grid":
            request = dict(parameter_grid or settings)
            request.setdefault("project_name", project_name)
            return await self.parameter_grid(request)
        if mode != "project":
            raise BackendError(
                "INVALID_ARGUMENT",
                "mode must be 'project' or 'parameter_grid'.",
                "service",
                "set_project_settings",
                {"mode": mode},
            )
        await self.backend.set_settings(project_name, settings)
        return f"Settings updated for project '{project_name}'."

    def _resolve_destination(
        self,
        filename: str,
        folder: str | None,
        suffixes: set[str],
        *,
        operation: str,
    ) -> Path:
        candidate = str(Path(folder) / filename) if folder else filename
        return self._resolve_path(
            candidate,
            suffixes=suffixes,
            operation=operation,
        )

    async def create_project(
        self,
        kind: str,
        filename: str,
        folder: str | None,
        *,
        confirm: bool = False,
    ) -> dict[str, str]:
        suffixes = {".pscx"} if kind == "case" else {".pslx"}
        destination = self._resolve_destination(
            filename,
            folder,
            suffixes,
            operation=f"create_{kind}",
        )
        if destination.exists() and not confirm:
            raise ConfirmationRequired(f"create_{kind}")
        info = await self.backend.create_project(
            kind,
            destination.name,
            str(destination.parent),
        )
        return {"name": info.name, "filename": str(destination)}

    async def save_project(
        self, project_name: str, *, confirm: bool = False
    ) -> str:
        if not confirm:
            raise ConfirmationRequired("save_project")
        await self.backend.save_project(project_name)
        return f"Project '{project_name}' saved."

    async def save_project_as(
        self,
        project_name: str,
        filename: str,
        folder: str | None,
        *,
        confirm: bool = False,
    ) -> str:
        suffixes = {".pscx", ".pslx"}
        destination = self._resolve_destination(
            filename,
            folder,
            suffixes,
            operation="save_project_as",
        )
        if destination.exists() and not confirm:
            raise ConfirmationRequired("save_project_as")
        await self.backend.save_project_as(
            project_name,
            destination.name,
            str(destination.parent),
        )
        return f"Project '{project_name}' saved as '{destination}'."

    async def build_project(self, project_name: str) -> str:
        await self.backend.build_project(project_name)
        return f"Project '{project_name}' built successfully."

    async def build_all_projects(self) -> str:
        await self.backend.build_all_projects()
        return "All projects built successfully."

    async def get_project_definitions(self, project_name: str) -> list[str]:
        return await self.backend.project_definitions(project_name)

    async def list_simulation_sets(self, project_name: str) -> list[str]:
        return await self.backend.list_simulation_sets(project_name)

    async def create_simulation_set(self, sim_set_name: str) -> dict[str, Any]:
        name = _require_object_name(
            sim_set_name, "sim_set_name", "create_simulation_set"
        )
        return asdict(await self.backend.create_simulation_set(name))

    async def remove_simulation_set(
        self, sim_set_name: str, *, confirm: bool = False
    ) -> dict[str, str]:
        if not confirm:
            raise ConfirmationRequired("remove_simulation_set")
        name = _require_object_name(
            sim_set_name, "sim_set_name", "remove_simulation_set"
        )
        await self.backend.remove_simulation_set(name)
        return {"removed": name}

    async def list_simulation_set_tasks(self, sim_set_name: str) -> list[str]:
        name = _require_object_name(
            sim_set_name, "sim_set_name", "list_simulation_set_tasks"
        )
        return await self.backend.list_simulation_set_tasks(name)

    async def remove_tasks_from_set(
        self,
        sim_set_name: str,
        task_names: list[str],
        *,
        confirm: bool = False,
    ) -> dict[str, list[str]]:
        if not confirm:
            raise ConfirmationRequired("remove_tasks_from_set")
        name = _require_object_name(
            sim_set_name, "sim_set_name", "remove_tasks_from_set"
        )
        if not isinstance(task_names, list):
            raise BackendError(
                "INVALID_ARGUMENT",
                "task_names must be a list.",
                "service",
                "remove_tasks_from_set",
            )
        unique = list(dict.fromkeys(task_names))
        if not unique:
            raise BackendError(
                "INVALID_ARGUMENT",
                "task_names must not be empty.",
                "service",
                "remove_tasks_from_set",
            )
        for task_name in unique:
            _require_object_name(task_name, "task_name", "remove_tasks_from_set")
        await self.backend.remove_tasks_from_set(name, unique)
        return {"removed": unique}

    async def get_simulation_task_parameters(
        self, sim_set_name: str, task_name: str
    ) -> dict[str, Any]:
        set_name = _require_object_name(
            sim_set_name,
            "sim_set_name",
            "get_simulation_task_parameters",
        )
        task = _require_object_name(
            task_name, "task_name", "get_simulation_task_parameters"
        )
        return asdict(await self.backend.get_simulation_task_parameters(set_name, task))

    async def set_simulation_task_parameters(
        self,
        sim_set_name: str,
        task_name: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        set_name = _require_object_name(
            sim_set_name,
            "sim_set_name",
            "set_simulation_task_parameters",
        )
        task = _require_object_name(
            task_name, "task_name", "set_simulation_task_parameters"
        )
        values = _validated_task_parameters(parameters)
        return asdict(
            await self.backend.set_simulation_task_parameters(set_name, task, values)
        )

    async def get_simulation_set_details(self, sim_set_name: str) -> dict[str, Any]:
        name = _require_object_name(
            sim_set_name, "sim_set_name", "get_simulation_set_details"
        )
        return asdict(await self.backend.get_simulation_set_details(name))

    async def run_simulation_set(
        self, project_name: str, sim_set_name: str
    ) -> str:
        async with self._mutation_lock:
            await self.backend.get_simulation_set_details(sim_set_name)
            await self.backend.run_simulation_set(project_name, sim_set_name)
            return (
                f"Simulation set '{sim_set_name}' in project "
                f"'{project_name}' started."
            )

    async def add_task_to_set(
        self,
        project_name: str,
        sim_set_name: str,
        task_project_name: str,
    ) -> str:
        async with self._mutation_lock:
            await self.backend.get_simulation_set_details(sim_set_name)
            projects = {item.name for item in await self.backend.list_projects()}
            if task_project_name not in projects:
                raise BackendError(
                    "NOT_FOUND",
                    f"Project '{task_project_name}' is not loaded.",
                    getattr(self.backend, "name", "backend"),
                    "add_task_to_set",
                    {"task_project_name": task_project_name},
                )
            await self.backend.add_task_to_set(
                project_name,
                sim_set_name,
                task_project_name,
            )
            return f"Task '{task_project_name}' added to set '{sim_set_name}'."

    async def get_project_output(
        self, project_name: str, structured: bool = False
    ) -> str | list[dict[str, Any]]:
        if structured:
            return [
                asdict(message)
                for message in await self.backend.project_messages(project_name)
            ]
        return await self.backend.project_output(project_name)

    async def get_output_channels(self, project_name: str) -> list[dict[str, Any]]:
        return [dict(item) for item in await self.backend.get_output_channels(project_name)]

    async def read_output_file(
        self,
        file_path: str,
        max_samples: int = 10_000,
        channel: str | None = None,
        summary_only: bool = False,
    ) -> dict[str, Any]:
        if not 1 <= max_samples <= 1_000_000:
            raise ValueError("max_samples must be between 1 and 1000000.")
        if channel is not None and (not isinstance(channel, str) or not channel):
            raise ValueError("channel must be a non-empty string when provided.")
        if not isinstance(summary_only, bool):
            raise ValueError("summary_only must be a boolean.")
        resolved = self._resolve_path(
            file_path,
            suffixes={".psout", ".out"},
            must_exist=True,
            operation="read_output_file",
        )
        return await self.backend.read_output_file(
            str(resolved),
            max_samples,
            channel=channel,
            summary_only=summary_only,
        )

    async def discover_output_files(
        self,
        project_name: str,
        *,
        started_after: float,
        max_files: int = 100,
    ) -> list[str]:
        """Find bounded, project-scoped result files created by a run."""
        if (
            isinstance(started_after, bool)
            or not isinstance(started_after, (int, float))
            or not math.isfinite(float(started_after))
            or float(started_after) < 0
        ):
            raise BackendError(
                "INVALID_ARGUMENT",
                "started_after must be a finite non-negative Unix timestamp.",
                "service",
                "discover_output_files",
            )
        if isinstance(max_files, bool) or not isinstance(max_files, int) or not 1 <= max_files <= 1_000:
            raise BackendError(
                "INVALID_ARGUMENT",
                "max_files must be between 1 and 1000.",
                "service",
                "discover_output_files",
            )
        project_candidate = Path(project_name).expanduser()
        if not project_candidate.suffix:
            project_candidate = project_candidate.with_suffix(".pscx")
        project_path = self._resolve_path(
            str(project_candidate),
            suffixes={".pscx"},
            must_exist=True,
            operation="discover_output_files",
        )

        def scan() -> list[str]:
            candidates: list[Path] = []
            for suffix in (".out", ".psout"):
                direct = project_path.with_suffix(suffix)
                if direct.is_file():
                    candidates.append(direct)
            generated_name = re.compile(rf"{re.escape(project_path.stem)}\.gf\d+", re.IGNORECASE)
            generated = sorted(
                (
                    child
                    for child in project_path.parent.iterdir()
                    if child.is_dir() and generated_name.fullmatch(child.name)
                ),
                key=lambda item: item.name.casefold(),
            )
            scanned = 0
            for directory in generated[:32]:
                for root, directories, filenames in os.walk(directory):
                    directories[:] = sorted(directories, key=str.casefold)[:64]
                    for filename in sorted(filenames, key=str.casefold):
                        scanned += 1
                        if scanned > 10_000:
                            break
                        path = Path(root) / filename
                        if path.suffix.casefold() in {".out", ".psout"}:
                            candidates.append(path)
                    if scanned > 10_000:
                        break
                if scanned > 10_000:
                    break
            found: list[str] = []
            for candidate in sorted(set(candidates), key=lambda item: str(item).casefold()):
                try:
                    if candidate.stat().st_mtime < float(started_after):
                        continue
                    resolved = self._resolve_path(
                        str(candidate),
                        suffixes={".out", ".psout"},
                        must_exist=True,
                        operation="discover_output_files",
                    )
                except FileNotFoundError:
                    continue
                found.append(str(resolved))
                if len(found) >= max_files:
                    break
            return found

        return await asyncio.to_thread(scan)

    async def find_components(
        self,
        project_name: str,
        definition: str | None = None,
        name: str | None = None,
        canvas_name: str = "Main",
    ) -> list[dict[str, Any]]:
        values = await self.backend.find_components(
            project_name, canvas_name, definition, name
        )
        return [asdict(value) for value in values]

    async def get_component_parameters(
        self, project_name: str, component_id: int
    ) -> dict[str, Any]:
        return await self.backend.get_component_parameters(
            project_name, component_id
        )

    async def set_component_parameters(
        self,
        project_name: str,
        component_id: int,
        parameters: dict[str, Any],
    ) -> str:
        await self.backend.set_component_parameters(
            project_name, component_id, parameters
        )
        return f"Parameters updated for component {component_id}."

    @staticmethod
    def _value_in_range(value: Any, legal_range: Any) -> bool:
        if isinstance(legal_range, range):
            return value in legal_range
        if isinstance(legal_range, (tuple, list)) and len(legal_range) == 2:
            lower, upper = legal_range
            numeric_bounds = all(
                item is None or isinstance(item, (int, float))
                for item in (lower, upper)
            )
            if numeric_bounds and isinstance(value, (int, float)):
                return (
                    (lower is None or lower <= value)
                    and (upper is None or value <= upper)
                )
        try:
            return value in legal_range
        except (TypeError, ValueError):
            return False

    async def validate_component_parameters(
        self,
        project_name: str,
        component_id: int,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        result = {}
        for parameter_name, value in parameters.items():
            try:
                legal_range = await self.backend.component_parameter_range(
                    project_name, component_id, parameter_name
                )
                result[parameter_name] = {
                    "valid": self._value_in_range(value, legal_range),
                    "range": str(legal_range),
                }
            except Exception as error:
                result[parameter_name] = {
                    "valid": False,
                    "error": str(error),
                }
        return result

    async def get_component_location(
        self, project_name: str, component_id: int
    ) -> dict[str, int]:
        x, y = await self.backend.get_component_location(
            project_name, component_id
        )
        return {"id": component_id, "x": x, "y": y}

    async def set_component_location(
        self, project_name: str, component_id: int, x: int, y: int
    ) -> str:
        await self.backend.set_component_location(
            project_name, component_id, (x, y)
        )
        return f"Component {component_id} moved to ({x}, {y})."

    async def rotate_component(
        self, project_name: str, component_id: int, direction: str
    ) -> str:
        await self.backend.rotate_component(project_name, component_id, direction)
        return f"Component {component_id} rotated {direction}."

    async def mirror_component(
        self, project_name: str, component_id: int, axis: str
    ) -> str:
        await self.backend.mirror_component(project_name, component_id, axis)
        return f"Component {component_id} mirrored along {axis} axis."

    async def clone_component(
        self, project_name: str, component_id: int, x: int, y: int
    ) -> dict[str, Any]:
        return asdict(
            await self.backend.clone_component(
                project_name, component_id, (x, y)
            )
        )

    async def get_component_ports(
        self, project_name: str, component_id: int
    ) -> dict[str, dict[str, Any]]:
        ports = await self.backend.get_component_ports(
            project_name, component_id
        )
        return {port.name: asdict(port) for port in ports}

    async def get_component_port(
        self, project_name: str, component_id: int, port_name: str
    ) -> dict[str, Any]:
        ports = await self.get_component_ports(project_name, component_id)
        try:
            return ports[port_name]
        except KeyError as error:
            raise BackendError(
                "NOT_FOUND",
                f"Port '{port_name}' not found on component {component_id}.",
                self.backend.name,
                "get_component_port",
                {"component_id": component_id, "port_name": port_name},
            ) from error

    async def set_component_enabled(
        self, project_name: str, component_id: int, enabled: bool
    ) -> str:
        await self.backend.set_component_enabled(
            project_name, component_id, enabled
        )
        state = "enabled" if enabled else "disabled"
        return f"Component {component_id} {state}."

    async def delete_component(
        self,
        project_name: str,
        component_id: int,
        *,
        confirm: bool = False,
    ) -> str:
        if not confirm:
            raise ConfirmationRequired("delete_component")
        await self.backend.delete_components(project_name, [component_id])
        return f"Component {component_id} deleted."

    async def delete_components(
        self,
        project_name: str,
        component_ids: list[int],
        *,
        confirm: bool = False,
    ) -> str:
        if not confirm:
            raise ConfirmationRequired("delete_components")
        unique_ids = list(dict.fromkeys(int(value) for value in component_ids))
        if not unique_ids:
            raise ValueError("component_ids must not be empty.")
        await self.backend.delete_components(project_name, unique_ids)
        return f"Deleted {len(unique_ids)} component(s)."

    async def add_canvas_component(
        self,
        project_name: str,
        library: str,
        name: str,
        x: int,
        y: int,
        orientation: int,
        parameters: dict[str, Any] | None,
        *,
        canvas_name: str = "Main",
    ) -> dict[str, Any]:
        return asdict(
            await self.backend.add_component(
                project_name,
                canvas_name,
                library,
                name,
                (x, y),
                orientation,
                dict(parameters or {}),
            )
        )

    async def create_canvas_component(
        self,
        project_name: str,
        definition: str,
        x: int,
        y: int,
        orientation: int,
        parameters: dict[str, Any] | None,
        *,
        canvas_name: str = "Main",
    ) -> dict[str, Any]:
        if ":" not in definition:
            raise ValueError("definition must use the 'library:name' form.")
        library, name = definition.split(":", 1)
        return await self.add_canvas_component(
            project_name,
            library,
            name,
            x,
            y,
            orientation,
            parameters,
            canvas_name=canvas_name,
        )

    @staticmethod
    def _canvas_points(points: list[list[int]]) -> list[tuple[int, int]]:
        if len(points) < 2:
            raise ValueError("At least two vertices are required.")
        if any(len(point) != 2 for point in points):
            raise ValueError("Each vertex must contain exactly two coordinates.")
        return [(int(point[0]), int(point[1])) for point in points]

    async def create_wire(
        self,
        project_name: str,
        vertices: list[list[int]],
        *,
        canvas_name: str = "Main",
    ) -> dict[str, Any]:
        return await self.backend.create_wire(
            project_name, canvas_name, self._canvas_points(vertices)
        )

    async def create_bus(
        self,
        project_name: str,
        vertices: list[list[int]],
        parameters: dict[str, Any] | None,
        *,
        canvas_name: str = "Main",
    ) -> dict[str, Any]:
        return await self.backend.create_bus(
            project_name,
            canvas_name,
            self._canvas_points(vertices),
            dict(parameters or {}),
        )

    async def create_connection(
        self,
        project_name: str,
        p1: list[int],
        p2: list[int],
        label: str | None,
        electrical: bool | None,
        *,
        canvas_name: str = "Main",
    ) -> dict[str, Any]:
        if len(p1) != 2 or len(p2) != 2:
            raise ValueError("p1 and p2 must contain exactly two coordinates.")
        return await self.backend.create_connection(
            project_name,
            canvas_name,
            (int(p1[0]), int(p1[1])),
            (int(p2[0]), int(p2[1])),
            label,
            electrical,
        )

    async def connect_ports(
        self,
        project_name: str,
        component1_id: int,
        port1_name: str,
        component2_id: int,
        port2_name: str,
        *,
        canvas_name: str = "Main",
    ) -> dict[str, Any]:
        async with self._mutation_lock:
            port1 = await self.get_component_port(
                project_name, component1_id, port1_name
            )
            port2 = await self.get_component_port(
                project_name, component2_id, port2_name
            )
            wire = await self.backend.create_wire(
                project_name,
                canvas_name,
                [(port1["x"], port1["y"]), (port2["x"], port2["y"])],
            )
            return {
                "wire_id": wire["id"],
                "from": {
                    "component_id": component1_id,
                    "port": port1_name,
                    "x": port1["x"],
                    "y": port1["y"],
                },
                "to": {
                    "component_id": component2_id,
                    "port": port2_name,
                    "x": port2["x"],
                    "y": port2["y"],
                },
            }

    async def create_annotation(
        self,
        project_name: str,
        x: int,
        y: int,
        line1: str,
        line2: str,
        *,
        canvas_name: str = "Main",
    ) -> dict[str, Any]:
        return asdict(
            await self.backend.create_annotation(
                project_name, canvas_name, (x, y), line1, line2
            )
        )

    async def create_graph_frame(
        self,
        project_name: str,
        x: int,
        y: int,
        *,
        canvas_name: str = "Main",
    ) -> dict[str, Any]:
        return await self.backend.create_graph_frame(
            project_name, canvas_name, (x, y)
        )

    async def create_control_frame(
        self,
        project_name: str,
        x: int,
        y: int,
        *,
        canvas_name: str = "Main",
    ) -> dict[str, Any]:
        return await self.backend.create_control_frame(
            project_name, canvas_name, (x, y)
        )

    async def list_canvas_components(
        self, project_name: str, *, canvas_name: str = "Main"
    ) -> list[dict[str, Any]]:
        return await self.backend.list_canvas_components(
            project_name, canvas_name
        )

    async def find_empty_space(
        self,
        project_name: str,
        width: int,
        height: int,
        near_x: int,
        near_y: int,
        *,
        canvas_name: str = "Main",
    ) -> dict[str, int]:
        return await self.backend.find_empty_space(
            project_name,
            canvas_name,
            width,
            height,
            (near_x, near_y),
        )

    @staticmethod
    def error_payload(error: Exception, operation: str) -> dict[str, Any]:
        if isinstance(error, BackendError):
            return {"error": _with_error_guidance(error.to_dict())}
        if isinstance(error, ExecutorTimeoutError):
            code = "TIMEOUT"
            backend = "executor"
        elif isinstance(error, ExecutorUnhealthyError):
            code = "EXECUTOR_UNHEALTHY"
            backend = "executor"
        else:
            code = "INTERNAL_ERROR"
            backend = "service"
        return {
            "error": _with_error_guidance({
                "code": code,
                "message": _bounded_message(error),
                "backend": backend,
                "operation": operation,
                "details": {},
            })
        }
