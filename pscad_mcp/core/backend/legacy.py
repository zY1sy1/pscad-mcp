"""PSCAD 4.x backend implemented with the legacy Automation Library."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import math
import os
import re
import shutil
import tempfile
import time
from collections.abc import Mapping as MappingABC
from decimal import Decimal, InvalidOperation
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
import xml.etree.ElementTree as ET

from ...topology.geometry import GeometryError, absolute_port
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
from ..definition_metadata import DefinitionMetadata, read_definition_metadata
from ..process_inventory import bounded_process_records
from ..pscad_adapter import PscadAdapter
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
)
from . import legacy_support
from .run_control import (
    STOPPED_RUN_STATUSES,
    require_single_active_target,
)


_RUN_STATE_MISSING = object()
_SavedTopologyRecord = tuple[
    str | None,
    tuple[int, int] | None,
    str | None,
]


class LegacyBackend:
    name = "legacy"
    _canvas_grid = 18
    _disabled_layer = "PSCAD_MCP_DISABLED"
    RUN_STATUS_TIMEOUT = 5.0
    RUN_START_GRACE = 5.0
    RUN_TRANSITION_GRACE = 2.0
    RUN_CONTROL_TIMEOUT = 5.0
    RUN_CONTROL_POLL_INTERVAL = 0.1
    PAUSE_READY_TIMEOUT = 120.0
    SETTING_DETAIL_TEXT_LIMIT = 64
    SETTING_DETAIL_MAX_DEPTH = 2
    SETTING_DETAIL_MAX_ENTRIES = 2
    SETTING_DETAIL_MAX_MISMATCHES = 4
    SETTING_DETAIL_MAX_SERIALIZED_CHARS = 4096
    SETTING_DETAIL_MAX_INTEGER_BITS = 4096
    _TASK_PARAMETER_ORDER = ("controlgroup", "volley", "affinity")

    def __init__(
        self,
        executor: Any,
        *,
        version: str,
        x64: bool,
        automation_module: Any = None,
        legacy_wheel: str | None = None,
        psout_module: Any = None,
        definition_paths: Mapping[str, str | Path] | None = None,
        legacy_minimize: bool = False,
        legacy_existing_policy: str = "reject",
        process_probe: Callable[[], Sequence[Mapping[str, Any]]] | None = None,
    ) -> None:
        self.executor = executor
        self.version = version
        self.x64 = x64
        self.legacy_wheel = legacy_wheel
        self.legacy_minimize = legacy_minimize
        self.legacy_existing_policy = legacy_existing_policy
        self.process_probe = process_probe or (lambda: ())
        if automation_module is False:
            self.automation = None
        elif automation_module is not None:
            self.automation = automation_module
        else:
            try:
                self.automation = importlib.import_module("mhrc.automation")
            except ImportError:
                self.automation = None
        self._app: Any = None
        self.owns_process = False
        self._managed_pid: int | None = None
        self._managed_executable: str | None = None
        self.definition_paths = {
            str(name): Path(path).resolve()
            for name, path in (definition_paths or {}).items()
        }
        self._component_orientations: dict[tuple[str, int], int] = {}
        self._topology_definition_cache: dict[
            tuple[str, str, str], DefinitionMetadata
        ] = {}
        self._running_projects: set[str] = set()
        self._paused_projects: set[str] = set()
        self._run_activity_seen: set[str] = set()
        self._run_submitted_at: dict[str, float] = {}
        self._run_last_active_at: dict[str, float] = {}
        self._run_last_active_status: dict[str, str] = {}
        self._known_managed_layers: set[tuple[str, str]] = set()
        self.result_adapter = PscadAdapter(
            executor,
            pscad_module=False,
            psout_module=psout_module,
            environ={},
        )

    @property
    def session_details(self) -> dict[str, object]:
        return {
            "mode": "managed-launch",
            "managed_pid": self._managed_pid,
            "managed_executable": self._managed_executable,
            "legacy_minimize": self.legacy_minimize,
            "existing_process_policy": self.legacy_existing_policy,
            "ordinary_gui_attach_supported": False,
            "paused_state_source": "command-tracked",
            "tracked_paused_projects": sorted(self._paused_projects),
        }

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
        if self.automation is None:
            hint = (
                f" Install the official wheel from {self.legacy_wheel}."
                if self.legacy_wheel
                else " Install mhrc.automation from the PSCAD 4.6 Automation Library media."
            )
            raise BackendError(
                "DEPENDENCY_MISSING",
                "mhrc.automation is required for PSCAD 4.6.x." + hint,
                self.name,
                "attach",
                {"legacy_wheel": self.legacy_wheel},
            )

        existing = bounded_process_records(
            await self.executor.run_safe(self.process_probe)
        )
        if existing and self.legacy_existing_policy == "reject":
            raise BackendError(
                "EXTERNAL_PSCAD_PRESENT",
                "An existing PSCAD process cannot be attached by the legacy "
                "automation API. Close it or explicitly allow a parallel "
                "managed instance.",
                self.name,
                "attach",
                {
                    "processes": existing,
                    "policy": self.legacy_existing_policy,
                    "ordinary_gui_attach_supported": False,
                },
            )

        display_name = (
            f"PSCAD {self.version} ({'x64' if self.x64 else 'x86'})"
        )

        def launch() -> Any:
            return self.automation.launch_pscad(
                pscad_version=display_name,
                silence=True,
                minimize=self.legacy_minimize,
                certificate=False,
            )

        self._app = await self.executor.run_safe(launch)
        self.owns_process = True
        process = getattr(self._app, "_proc", None)
        raw_pid = getattr(process, "pid", None)
        try:
            self._managed_pid = int(raw_pid) if raw_pid is not None else None
        except (TypeError, ValueError, OverflowError):
            self._managed_pid = None
        after_launch = bounded_process_records(
            await self.executor.run_safe(self.process_probe)
        )
        managed_record = next(
            (
                item
                for item in after_launch
                if item["pid"] == self._managed_pid
            ),
            None,
        )
        self._managed_executable = (
            str(managed_record["exe"]) if managed_record else None
        )
        return await self.heartbeat()

    async def heartbeat(self) -> BackendInfo:
        if self._app is None:
            return self._info(alive=False)
        alive = bool(await self.executor.run_safe(self._app.is_alive))
        busy_method = getattr(self._app, "is_busy", None)
        busy = (
            bool(await self.executor.run_safe(busy_method))
            if busy_method is not None
            else False
        )
        licensed_method = getattr(self._app, "licensed", None)
        licensed = (
            bool(await self.executor.run_safe(licensed_method))
            if licensed_method is not None
            else None
        )
        return self._info(alive=alive, busy=busy, licensed=licensed)

    async def disconnect(self) -> None:
        self._app = None
        self.owns_process = False
        self._managed_pid = None
        self._managed_executable = None
        self._component_orientations.clear()
        self._running_projects.clear()
        self._paused_projects.clear()
        self._run_activity_seen.clear()
        self._run_submitted_at.clear()
        self._run_last_active_at.clear()
        self._run_last_active_status.clear()
        self._known_managed_layers.clear()

    async def quit(self) -> None:
        app = self._app
        if app is not None:
            await self.executor.run_safe(app.quit)
            is_alive = getattr(app, "is_alive", None)
            if callable(is_alive):
                try:
                    alive = bool(await self.executor.run_safe(is_alive))
                except Exception as error:
                    raise BackendError(
                        "SHUTDOWN_UNVERIFIED",
                        "PSCAD quit returned, but shutdown could not be verified.",
                        self.name,
                        "quit",
                    ) from error
                if alive:
                    raise BackendError(
                        "SHUTDOWN_UNVERIFIED",
                        "PSCAD quit returned, but the application is still alive.",
                        self.name,
                        "quit",
                        {"owns_process": self.owns_process},
                    )
        await self.disconnect()

    def _require_app(self) -> Any:
        if self._app is None:
            raise BackendError(
                "NOT_CONNECTED",
                "PSCAD is not connected.",
                self.name,
                "application",
            )
        return self._app

    async def _project(self, project_name: str) -> Any:
        app = self._require_app()
        return await self.executor.run_safe(app.project, project_name)

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
        await self.executor.run_safe(self._require_app().load, *filenames)
        for filename in filenames:
            path = Path(filename).resolve()
            if path.suffix.lower() in {".pslx", ".pscx"}:
                self.definition_paths[path.stem] = path
                try:
                    tree = await asyncio.to_thread(ET.parse, path)
                    project_name = (
                        tree.getroot().get("name") or ""
                    ).strip()
                except (OSError, ET.ParseError):
                    project_name = ""
                if project_name:
                    self.definition_paths[project_name] = path

    async def list_projects(self) -> list[ProjectInfo]:
        values = await self.executor.run_safe(self._require_app().list_projects)
        return [self._project_info(value) for value in values]

    @staticmethod
    def _project_destination(filename: str, folder: str | None) -> Path:
        path = Path(folder) / filename if folder else Path(filename)
        return path.resolve()

    @staticmethod
    def _require_project_suffix(destination: Path, kind: str) -> None:
        expected_suffix = ".pscx" if kind == "case" else ".pslx"
        if destination.suffix.casefold() != expected_suffix:
            raise ValueError(
                f"{kind} projects require a {expected_suffix} destination."
            )

    @staticmethod
    def _loaded_project_kind(project: Any, source: Path | None) -> str:
        project_type = str(getattr(project, "type", "")).casefold()
        if project_type == "case":
            return "case"
        if project_type == "library":
            return "library"

        known_path = source
        if known_path is None:
            filename = getattr(project, "filename", None)
            known_path = Path(str(filename)) if filename else None
        if known_path is not None:
            marker = ET.Element("project")
            try:
                return legacy_support.project_kind(marker, known_path.suffix)
            except ValueError:
                pass
        raise BackendError(
            "CAPABILITY_UNAVAILABLE",
            "The PSCAD 4.6.2 project kind could not be determined.",
            "legacy",
            "save_project_as",
            {"project_type": project_type},
        )

    @staticmethod
    def _temporary_path(destination: Path, suffix: str) -> Path:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=suffix,
            dir=destination.parent,
        )
        os.close(descriptor)
        return Path(temporary)

    @classmethod
    def _backup_destination(cls, destination: Path) -> Path | None:
        if not destination.exists():
            return None
        backup = cls._temporary_path(destination, ".bak")
        try:
            shutil.copyfile(destination, backup)
        except BaseException:
            backup.unlink(missing_ok=True)
            raise
        return backup

    @staticmethod
    def _restore_destination(
        destination: Path, backup: Path | None
    ) -> None:
        if backup is None:
            destination.unlink(missing_ok=True)
        else:
            os.replace(backup, destination)

    @staticmethod
    def _validate_rewritten_project(
        destination: Path, kind: str, expected_name: str
    ) -> None:
        root = ET.parse(destination).getroot()
        if root.tag != "project":
            raise ValueError(
                f"Expected root <project> but found <{root.tag}>."
            )
        actual_kind = legacy_support.project_kind(root, destination.suffix)
        if actual_kind != kind:
            raise ValueError(
                f"Expected a {kind} project but found {actual_kind}."
            )
        if root.get("name") != expected_name:
            raise ValueError("Rewritten project root identity is invalid.")
        if any(
            output.get("name") != expected_name
            for output in root.findall("./output")
        ):
            raise ValueError("Rewritten project output identity is invalid.")

    async def _load_and_verify_project(
        self, destination: Path, kind: str, operation: str
    ) -> ProjectInfo:
        await self.executor.run_safe(
            self._require_app().load, str(destination)
        )
        expected_name = destination.stem
        expected_type = "Case" if kind == "case" else "Library"
        projects = await self.list_projects()
        match = next(
            (item for item in projects if item.name == expected_name), None
        )
        if match is None or match.type.casefold() != expected_type.casefold():
            raise BackendError(
                "POSTCONDITION_FAILED",
                "PSCAD did not load the expected project.",
                self.name,
                operation,
                {
                    "path": str(destination),
                    "expected_name": expected_name,
                    "expected_type": expected_type,
                },
            )
        return match

    async def _copy_rewrite_load_verify(
        self,
        source: Path,
        destination: Path,
        kind: str,
        operation: str,
    ) -> ProjectInfo:
        temporary: Path | None = self._temporary_path(
            destination, destination.suffix
        )
        backup: Path | None = None
        replaced = False
        try:
            shutil.copyfile(source, temporary)
            legacy_support.rewrite_template_identity(
                temporary, temporary, destination.stem
            )
            self._validate_rewritten_project(
                temporary, kind, destination.stem
            )

            backup = self._backup_destination(destination)
            os.replace(temporary, destination)
            temporary = None
            replaced = True

            info = await self._load_and_verify_project(
                destination, kind, operation
            )
            if backup is not None:
                backup.unlink(missing_ok=True)
                backup = None
            self.definition_paths[info.name] = destination
            return info
        except BaseException:
            if replaced:
                if backup is not None:
                    recovery_backup = backup
                    backup = None
                    self._restore_destination(
                        destination, recovery_backup
                    )
                else:
                    self._restore_destination(destination, None)
            raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            if backup is not None:
                backup.unlink(missing_ok=True)

    async def create_project(
        self, kind: str, filename: str, folder: str | None
    ) -> ProjectInfo:
        if kind not in {"case", "library"}:
            raise ValueError("kind must be case or library.")
        destination = self._project_destination(filename, folder)
        self._require_project_suffix(destination, kind)
        template_name = (
            "empty_case.pscx" if kind == "case" else "empty_library.pslx"
        )
        template = (
            files("pscad_mcp")
            .joinpath("assets")
            .joinpath("templates")
            .joinpath(template_name)
        )
        with as_file(template) as template_path:
            return await self._copy_rewrite_load_verify(
                template_path,
                destination,
                kind,
                "create_project",
            )

    async def save_project(self, project_name: str) -> None:
        project = await self._project(project_name)
        await self.executor.run_safe(project.save)

    async def save_project_as(
        self, project_name: str, filename: str, folder: str | None
    ) -> None:
        project = await self._project(project_name)
        source = self.definition_paths.get(project_name)
        kind = self._loaded_project_kind(project, source)
        destination = self._project_destination(filename, folder)
        self._require_project_suffix(destination, kind)
        native_info: ProjectInfo | None = None
        tried_native = not destination.exists()
        if tried_native:
            try:
                response = await self.executor.run_safe(
                    project.save_as, str(destination)
                )

                if response is not None:
                    try:
                        legacy_support.require_success(
                            response,
                            "save_project_as",
                            {
                                "project": project_name,
                                "destination": str(destination),
                            },
                        )
                    except BackendError as error:
                        if error.code != "PSCAD_COMMAND_FAILED":
                            raise
                    else:
                        if destination.is_file():
                            self._validate_rewritten_project(
                                destination, kind, destination.stem
                            )
                            native_info = await self._load_and_verify_project(
                                destination, kind, "save_project_as"
                            )
            except BaseException:
                self._restore_destination(destination, None)
                raise

        if native_info is not None:
            self.definition_paths[native_info.name] = destination
            return

        if tried_native:
            self._restore_destination(destination, None)

        await self.save_project(project_name)
        source = self.definition_paths.get(project_name)
        if source is None or not source.is_file():
            raise BackendError(
                "CAPABILITY_UNAVAILABLE",
                "The source project file is unavailable for the PSCAD 4.6.2 "
                "save-as fallback.",
                self.name,
                "save_project_as",
                {
                    "project": project_name,
                    "destination": str(destination),
                },
            )
        await self._copy_rewrite_load_verify(
            source,
            destination,
            kind,
            "save_project_as",
        )

    async def build_project(self, project_name: str) -> None:
        project = await self._project(project_name)
        await self.executor.run_safe(project.build, timeout=300.0)

    async def build_all_projects(self) -> None:
        await self.executor.run_safe(
            self._require_app().build_all,
            timeout=300.0,
        )

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
                return [dict(item) for item in values if isinstance(item, MappingABC)]
        raise BackendError(
            "CAPABILITY_UNAVAILABLE",
            "Legacy PSCAD backend does not expose verified timed-control scheduling.",
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
            "Legacy PSCAD backend does not expose a verified simulation clock.",
            self.name,
            "get_simulation_time",
            {"project_name": project_name, "backend_version": self.version},
        )

    async def run_project(self, project_name: str) -> None:
        project = await self._project(project_name)

        def start() -> None:
            command = project.command("run")
            command.execute(False)

        await self.executor.run_safe(start)
        self._paused_projects.discard(project_name)
        self._running_projects.add(project_name)
        self._run_activity_seen.discard(project_name)
        self._run_submitted_at[project_name] = time.monotonic()
        self._run_last_active_at.pop(project_name, None)
        self._run_last_active_status.pop(project_name, None)

    async def pause_project(self, project_name: str) -> None:
        target = await self._wait_for_pauseable_target(project_name)
        if target.status.casefold() == "paused":
            return
        await self._run_control_command(
            "ID_RIBBON_HOME_RUN_PAUSE", "pause_project"
        )
        self._paused_projects.add(project_name)
        await self._wait_for_project_state(
            project_name,
            frozenset({"paused"}),
            "pause_project",
        )

    async def stop_project(self, project_name: str) -> None:
        states = await self._case_run_states()
        require_single_active_target(
            project_name,
            states,
            backend=self.name,
            operation="stop_project",
        )
        await self._run_control_command(
            "ID_RIBBON_HOME_RUN_STOP", "stop_project"
        )
        self._paused_projects.discard(project_name)
        await self._wait_for_project_state(
            project_name,
            STOPPED_RUN_STATUSES,
            "stop_project",
        )
        self._running_projects.discard(project_name)
        self._run_activity_seen.discard(project_name)
        self._run_submitted_at.pop(project_name, None)

    async def _case_run_states(self) -> dict[str, RunState]:
        projects = await self.list_projects()
        states: dict[str, RunState] = {}
        for project in projects:
            if project.type.casefold() != "case":
                continue
            states[project.name] = await self.project_run_state(project.name)
        return states

    async def _wait_for_pauseable_target(
        self, project_name: str
    ) -> RunState:
        deadline = time.monotonic() + self.PAUSE_READY_TIMEOUT
        while True:
            states = await self._case_run_states()
            target = require_single_active_target(
                project_name,
                states,
                backend=self.name,
                operation="pause_project",
            )
            status = target.status.casefold()
            if status in {"running", "paused"}:
                return target
            if time.monotonic() >= deadline:
                raise BackendError(
                    "POSTCONDITION_FAILED",
                    "The project remained active but did not become pauseable.",
                    self.name,
                    "pause_project",
                    {
                        "project_name": project_name,
                        "expected_states": ["paused", "running"],
                        "last_state": status,
                        "timeout_seconds": self.PAUSE_READY_TIMEOUT,
                    },
                )
            await asyncio.sleep(self.RUN_CONTROL_POLL_INTERVAL)

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

    async def _run_control_command(
        self, command_id: str, operation: str
    ) -> None:
        app = self._require_app()
        command = await self.executor.run_safe(app._command_id_cmd, command_id)
        response = await self.executor.run_safe(command.execute)
        legacy_support.require_success(
            response,
            operation,
            {"scope": "single-active-project"},
        )

    @staticmethod
    def _resolve_run_status_future(
        future: asyncio.Future[Any], payload: tuple[Any, tuple[Any, ...], dict[str, Any]]
    ) -> None:
        if not future.done():
            future.set_result(payload)

    @staticmethod
    def _normalized_run_status(value: Any) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        raw = value.strip().casefold()
        aliases = {
            "build": "building",
            "building": "building",
            "run": "running",
            "running": "running",
            "pause": "paused",
            "paused": "paused",
            "complete": "completed",
            "completed": "completed",
            "done": "completed",
            "stop": "stopped",
            "stopped": "stopped",
            "fail": "failed",
            "failed": "failed",
            "error": "failed",
            "idle": "idle",
            "ready": "idle",
        }
        return aliases.get(raw, raw)

    @staticmethod
    def _run_progress(value: Any) -> float | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise ValueError("Run progress cannot be boolean.")
        progress = float(value)
        if not math.isfinite(progress):
            raise ValueError("Run progress must be finite.")
        return progress

    @classmethod
    def _raise_failed_run_status_response(cls, value: Any) -> None:
        if isinstance(value, ET.Element):
            for node in value.iter():
                success = node.get("success")
                if success is not None and success.casefold() != "true":
                    legacy_support.require_success(
                        node,
                        "get_run_status",
                        {"response_scope": "callback"},
                    )
            return
        if not isinstance(value, MappingABC):
            return
        try:
            lowered = {str(key).casefold(): item for key, item in value.items()}
        except Exception:
            return
        success = lowered.get("success")
        has_failed_success = success is not None and (
            success is not True
            and (not isinstance(success, str) or success.casefold() != "true")
        )
        error = None
        for key in ("error", "exception", "failure"):
            if key not in lowered:
                continue
            candidate = lowered[key]
            if candidate is None or candidate is False:
                continue
            if isinstance(candidate, str) and not candidate:
                continue
            error = candidate
            break
        if not has_failed_success and error is None:
            return
        raise BackendError(
            "PSCAD_COMMAND_FAILED",
            "PSCAD 4.6.2 command 'get_run_status' failed.",
            cls.name,
            "get_run_status",
            {"response": legacy_support.response_payload(value)},
        )

    @classmethod
    def _run_state_values(
        cls, value: Any, depth: int = 0
    ) -> tuple[Any, Any]:
        missing = _RUN_STATE_MISSING
        if depth >= 4:
            return missing, missing
        if isinstance(value, ET.Element):
            status: Any = missing
            progress: Any = missing
            status_keys = {"status", "state", "run-status", "run_status", "runstate"}
            progress_keys = {"progress", "percent", "percentage", "completion"}
            legacy_flags: dict[str, bool] = {}
            for node in value.iter():
                tag = str(node.tag).split("}")[-1].casefold()
                attributes = {
                    str(key).casefold(): item for key, item in node.attrib.items()
                }
                if tag in {"build", "run"} and "value" in attributes:
                    flag = str(attributes["value"]).casefold()
                    if flag in {"true", "false"}:
                        legacy_flags[tag] = flag == "true"
                if status is missing:
                    for key in status_keys:
                        if key in attributes:
                            status = attributes[key]
                            break
                    if status is missing and "status" in tag:
                        status = attributes.get("value", node.text)
                if progress is missing:
                    for key in progress_keys:
                        if key in attributes:
                            progress = attributes[key]
                            break
                    if progress is missing and tag in progress_keys:
                        progress = attributes.get("value", node.text)
                if status is not missing and progress is not missing:
                    break
            if status is missing and {"build", "run"} <= legacy_flags.keys():
                if legacy_flags["run"]:
                    status = "running"
                elif legacy_flags["build"]:
                    status = "building"
                else:
                    status = "idle"
            return status, progress

        if isinstance(value, MappingABC):
            try:
                lowered = {
                    str(key).casefold(): item for key, item in value.items()
                }
            except Exception:
                return missing, missing
            status = next(
                (
                    lowered[key]
                    for key in ("status", "state", "run-status", "run_status", "runstate")
                    if key in lowered
                ),
                missing,
            )
            progress = next(
                (
                    lowered[key]
                    for key in ("progress", "percent", "percentage", "completion")
                    if key in lowered
                ),
                missing,
            )
            if status is not missing:
                return status, progress
            for index, item in enumerate(lowered.values()):
                if index >= 16:
                    break
                nested_status, nested_progress = cls._run_state_values(
                    item, depth + 1
                )
                if nested_status is not missing:
                    return nested_status, nested_progress
            return missing, missing

        if isinstance(value, (tuple, list)):
            if value and isinstance(value[0], str):
                return value[0], value[1] if len(value) > 1 else missing
            for item in value[:16]:
                status, progress = cls._run_state_values(item, depth + 1)
                if status is not missing:
                    return status, progress
        return missing, missing

    @classmethod
    def _parse_run_state(
        cls,
        response: Any,
        callback_args: tuple[Any, ...],
        callback_kwargs: dict[str, Any],
    ) -> RunState:
        candidates = (response, callback_args, callback_kwargs)
        for candidate in candidates:
            cls._raise_failed_run_status_response(candidate)

        missing = _RUN_STATE_MISSING
        status: Any = missing
        progress: Any = missing
        for candidate in candidates:
            candidate_status, candidate_progress = cls._run_state_values(candidate)
            if status is missing and candidate_status is not missing:
                status = candidate_status
            if progress is missing and candidate_progress is not missing:
                progress = candidate_progress
            if status is not missing and progress is not missing:
                break

        normalized = cls._normalized_run_status(status)
        try:
            normalized_progress = (
                None if progress is missing else cls._run_progress(progress)
            )
        except (TypeError, ValueError, OverflowError) as error:
            raise BackendError(
                "UNEXPECTED_RESPONSE",
                "PSCAD returned an invalid run progress value.",
                cls.name,
                "get_run_status",
                {"response": legacy_support.response_payload(response)},
            ) from error
        if normalized is None:
            raise BackendError(
                "UNEXPECTED_RESPONSE",
                "PSCAD did not return a recognizable run status.",
                cls.name,
                "get_run_status",
                {"response": legacy_support.response_payload(response)},
            )
        return RunState(normalized, normalized_progress)

    async def project_run_state(self, project_name: str) -> RunState:
        project = await self._project(project_name)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[
            tuple[Any, tuple[Any, ...], dict[str, Any]]
        ] = loop.create_future()

        def receive(
            response: Any,
            *callback_args: Any,
            **callback_kwargs: Any,
        ) -> None:
            payload = (response, callback_args, callback_kwargs)
            loop.call_soon_threadsafe(
                self._resolve_run_status_future, future, payload
            )

        app = self._require_app()

        def request_and_pump() -> None:
            project.get_run_status(receive)
            # Legacy post_command() has no background receiver. A synchronous,
            # read-only command drives its socket dispatcher and invokes receive.
            app.list_projects()

        await self.executor.run_safe(request_and_pump)
        try:
            response, callback_args, callback_kwargs = await asyncio.wait_for(
                future, self.RUN_STATUS_TIMEOUT
            )
        except asyncio.TimeoutError as error:
            raise BackendError(
                "PSCAD_COMMAND_TIMEOUT",
                "PSCAD did not return run status within 5 seconds.",
                self.name,
                "get_run_status",
                {"project": project_name},
            ) from error

        state = self._parse_run_state(
            response, callback_args, callback_kwargs
        )
        observed_at = time.monotonic()
        if (
            state.status == "idle"
            and project_name in self._running_projects
            and project_name not in self._run_activity_seen
            and time.monotonic()
            - self._run_submitted_at.get(project_name, 0.0)
            < self.RUN_START_GRACE
        ):
            return RunState("starting", state.progress)
        if (
            state.status == "idle"
            and project_name in self._running_projects
            and project_name in self._run_activity_seen
            and self._run_last_active_status.get(project_name) == "building"
            and observed_at
            - self._run_last_active_at.get(project_name, 0.0)
            < self.RUN_TRANSITION_GRACE
        ):
            return RunState(
                self._run_last_active_status.get(project_name, "starting"),
                state.progress,
            )
        if state.status in {"building", "running", "paused"}:
            self._run_activity_seen.add(project_name)
            self._run_last_active_at[project_name] = observed_at
            self._run_last_active_status[project_name] = state.status
        terminal = state.status.casefold() in {
            "complete",
            "completed",
            "stopped",
            "failed",
            "idle",
        }
        if terminal:
            self._running_projects.discard(project_name)
            self._paused_projects.discard(project_name)
            self._run_activity_seen.discard(project_name)
            self._run_submitted_at.pop(project_name, None)
            self._run_last_active_at.pop(project_name, None)
            self._run_last_active_status.pop(project_name, None)
        elif state.status.casefold() == "paused":
            self._paused_projects.add(project_name)
        elif (
            project_name in self._paused_projects
            and state.status.casefold() == "running"
        ):
            return RunState("paused", state.progress)
        return state

    async def project_definitions(self, project_name: str) -> list[str]:
        project = await self._project(project_name)
        method = getattr(project, "list_definitions", None)
        if method is None:
            method = project.definitions
        values = await self.executor.run_safe(method)
        return [str(value) for value in values]

    async def lcc_definition_inventory(self, catalog: Mapping[str, Any]) -> dict[str, Any]:
        """Read the requested Master definitions from the installed 4.6.2 library.

        Companion-library definitions are intentionally left to the service
        boundary, which may add only the packaged companion asset metadata.
        This backend method therefore reports live PSCAD evidence only.
        """

        if not isinstance(catalog, Mapping):
            raise BackendError(
                "INVALID_ARGUMENT",
                "The LCC catalog must be a mapping.",
                self.name,
                "lcc_definition_inventory",
            )
        values = catalog.get("definitions", ())
        if isinstance(values, Mapping):
            entries = list(values.items())
        elif isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
            entries = []
            for item in values:
                if isinstance(item, Mapping):
                    name = item.get("scoped_name", item.get("definition", item.get("name")))
                    entries.append((name, item))
        else:
            entries = []

        master_path = self.definition_paths.get("master")
        if master_path is None or not master_path.is_file():
            master_path = await self._discover_master_library()
            if master_path is not None:
                self.definition_paths["master"] = master_path
        if master_path is None or not master_path.is_file():
            raise BackendError(
                "CAPABILITY_UNAVAILABLE",
                "The installed PSCAD Master Library could not be located for LCC inventory.",
                self.name,
                "lcc_definition_inventory",
            )

        definitions: dict[str, dict[str, Any]] = {}
        for scoped_name, _item in entries:
            if not isinstance(scoped_name, str) or ":" not in scoped_name:
                continue
            scope, definition_name = scoped_name.split(":", 1)
            if scope.casefold() != "master":
                continue
            try:
                metadata = await asyncio.to_thread(
                    read_definition_metadata, master_path, definition_name
                )
            except (OSError, ET.ParseError, KeyError) as error:
                raise BackendError(
                    "LCC_DEFINITION_MISSING",
                    f"Live PSCAD Master definition '{scoped_name}' could not be read.",
                    self.name,
                    "lcc_definition_inventory",
                    {"definition": scoped_name, "path": str(master_path)},
                ) from error
            definitions[scoped_name] = {
                "ports": [
                    {
                        "name": port.name,
                        "dimension": port.dim,
                        "kind": port.type,
                    }
                    for port in metadata.ports
                ],
                "source": "live_master",
            }
        return {
            "pscad_version": self.version,
            "definitions": definitions,
            "source": "pscad_live",
        }

    @staticmethod
    def _settings_values_match(expected: Any, actual: Any) -> bool:
        if isinstance(expected, bool) or isinstance(actual, bool):
            return type(expected) is type(actual) and expected == actual
        try:
            if expected == actual:
                return True
        except Exception:
            pass

        def numeric_value(value: Any) -> Decimal | None:
            if not isinstance(value, (int, float, Decimal, str)):
                return None
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and value.bit_length() > LegacyBackend.SETTING_DETAIL_MAX_INTEGER_BITS
            ):
                return None
            try:
                number = value if isinstance(value, Decimal) else Decimal(str(value))
            except (InvalidOperation, ValueError):
                return None
            return number if number.is_finite() else None

        expected_number = numeric_value(expected)
        actual_number = numeric_value(actual)
        return (
            expected_number is not None
            and actual_number is not None
            and expected_number == actual_number
        )

    @classmethod
    def _bounded_setting_text(cls, value: str) -> str:
        if len(value) <= cls.SETTING_DETAIL_TEXT_LIMIT:
            return value
        return value[: cls.SETTING_DETAIL_TEXT_LIMIT - 3] + "..."

    @classmethod
    def _setting_type_name(cls, value: Any) -> str:
        return cls._bounded_setting_text(type(value).__name__)

    @classmethod
    def _oversized_integer_metadata(cls, value: int) -> dict[str, Any]:
        return {
            "type": "int",
            "bit_length": value.bit_length(),
            "sign": "negative" if value < 0 else "positive",
        }

    @classmethod
    def _is_oversized_integer(cls, value: Any) -> bool:
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value.bit_length() > cls.SETTING_DETAIL_MAX_INTEGER_BITS
        )

    @classmethod
    def _setting_detail_key(cls, key: Any) -> str:
        if isinstance(key, str):
            return cls._bounded_setting_text(key)
        if key is None:
            return "null"
        if isinstance(key, bool):
            return "true" if key else "false"
        if isinstance(key, int):
            if cls._is_oversized_integer(key):
                metadata = cls._oversized_integer_metadata(key)
                return cls._bounded_setting_text(
                    "<int bit_length={bit_length} sign={sign}>".format(
                        **metadata
                    )
                )
            return cls._bounded_setting_text(str(key))
        if isinstance(key, float):
            return cls._bounded_setting_text(str(key))
        if isinstance(key, Decimal):
            return cls._bounded_setting_text(str(key))
        return cls._bounded_setting_text(f"<{cls._setting_type_name(key)}>")

    @classmethod
    def _unique_setting_detail_key(
        cls, details: Mapping[Any, Any], key: Any, index: int
    ) -> str:
        detail_key = cls._setting_detail_key(key)
        if detail_key not in details:
            return detail_key
        suffix_index = index
        while True:
            suffix = f"_{suffix_index}"
            candidate = (
                detail_key[: cls.SETTING_DETAIL_TEXT_LIMIT - len(suffix)]
                + suffix
            )
            if candidate not in details:
                return candidate
            suffix_index += 1

    @classmethod
    def _setting_detail_value(cls, value: Any, depth: int = 0) -> Any:
        if value is None or isinstance(value, (str, bool)):
            return (
                cls._bounded_setting_text(value)
                if isinstance(value, str)
                else value
            )
        if isinstance(value, int):
            if cls._is_oversized_integer(value):
                return cls._oversized_integer_metadata(value)
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else str(value)
        if isinstance(value, Decimal):
            return cls._bounded_setting_text(str(value))
        if depth >= cls.SETTING_DETAIL_MAX_DEPTH:
            return {"type": cls._setting_type_name(value), "truncated": "depth"}
        if isinstance(value, MappingABC):
            try:
                details = {}
                for index, (key, item) in enumerate(value.items()):
                    if index >= cls.SETTING_DETAIL_MAX_ENTRIES:
                        details["__truncated__"] = {"truncated": "entries"}
                        break
                    detail_key = cls._unique_setting_detail_key(
                        details, key, index
                    )
                    details[detail_key] = cls._setting_detail_value(
                        item, depth + 1
                    )
                return details
            except Exception:
                return {
                    "type": cls._setting_type_name(value),
                    "truncated": "unreadable_mapping",
                }
        if isinstance(value, (list, tuple)):
            details = [
                cls._setting_detail_value(item, depth + 1)
                for item in value[: cls.SETTING_DETAIL_MAX_ENTRIES]
            ]
            if len(value) > cls.SETTING_DETAIL_MAX_ENTRIES:
                details.append({"truncated": "entries"})
            return details
        return {"type": cls._setting_type_name(value)}

    @classmethod
    def _settings_mapping(
        cls, values: Any, project_name: str, operation: str
    ) -> dict[Any, Any]:
        try:
            if isinstance(values, MappingABC):
                return dict(values)
            items = getattr(values, "items", None)
            if callable(items):
                return dict(items())
        except Exception:
            pass
        raise BackendError(
            "UNEXPECTED_RESPONSE",
            "Project parameters did not return a usable mapping.",
            cls.name,
            operation,
            {
                "project": cls._setting_detail_value(project_name),
                "response_type": cls._setting_type_name(values),
            },
        )

    async def get_settings(self, project_name: str) -> dict[str, Any]:
        project = await self._project(project_name)
        values = await self.executor.run_safe(project.parameters)
        return self._settings_mapping(values, project_name, "get_project_settings")

    async def set_settings(self, project_name: str, settings: Any) -> None:
        if not isinstance(settings, MappingABC):
            raise BackendError(
                "INVALID_PARAMETER",
                "Project settings must be a mapping.",
                self.name,
                "set_project_settings",
                {
                    "project": self._setting_detail_value(project_name),
                    "reason": "settings must be a mapping",
                    "settings_type": self._setting_type_name(settings),
                },
            )
        project = await self._project(project_name)
        try:
            requested = dict(settings)
        except Exception:
            raise BackendError(
                "INVALID_PARAMETER",
                "Project settings mapping could not be copied.",
                self.name,
                "set_project_settings",
                {
                    "project": self._setting_detail_value(project_name),
                    "reason": "settings mapping could not be copied",
                    "settings_type": self._setting_type_name(settings),
                },
            ) from None
        accepted = await self.executor.run_safe(project.set_parameters, requested)
        if accepted is not True:
            key_count = len(requested)
            keys = sorted(self._setting_detail_key(key) for key in requested)
            details = {
                "project": self._setting_detail_value(project_name),
                "keys": keys[: self.SETTING_DETAIL_MAX_ENTRIES],
            }
            if key_count > self.SETTING_DETAIL_MAX_ENTRIES:
                details["total_key_count"] = key_count
                details["keys_truncated"] = True
            raise BackendError(
                "INVALID_PARAMETER",
                "PSCAD did not accept the requested project parameters.",
                self.name,
                "set_project_settings",
                details,
            )
        values = await self.executor.run_safe(project.parameters)
        actual_values = self._settings_mapping(
            values, project_name, "set_project_settings"
        )
        mismatches = {}
        mismatch_count = 0
        for key, expected in requested.items():
            if key in actual_values and self._settings_values_match(
                expected, actual_values[key]
            ):
                continue
            mismatch_count += 1
            if len(mismatches) >= self.SETTING_DETAIL_MAX_MISMATCHES:
                continue
            detail_key = self._unique_setting_detail_key(
                mismatches, key, mismatch_count
            )
            mismatches[detail_key] = {
                "expected": self._setting_detail_value(expected),
                "actual": self._setting_detail_value(actual_values.get(key)),
            }
        if mismatches:
            details = {
                "project": self._setting_detail_value(project_name),
                "mismatches": mismatches,
            }
            if mismatch_count > self.SETTING_DETAIL_MAX_MISMATCHES:
                details["mismatch_count"] = mismatch_count
            raise BackendError(
                "POSTCONDITION_FAILED",
                "Project parameters could not be verified after update.",
                self.name,
                "set_project_settings",
                details,
            )

    async def project_output(self, project_name: str) -> str:
        project = await self._project(project_name)
        output = getattr(project, "output", None)
        if output is not None:
            return str(await self.executor.run_safe(output))
        messages = await self.executor.run_safe(project.messages)
        return "\n".join(str(message[0] if isinstance(message, tuple) else message) for message in messages)

    async def get_output_channels(self, project_name: str) -> list[dict[str, Any]]:
        project = await self._project(project_name)
        provider = getattr(project, "output_channels", None)
        if not callable(provider):
            raise BackendError(
                "CAPABILITY_UNAVAILABLE",
                "Legacy PSCAD does not expose verified output-channel metadata.",
                self.name,
                "get_output_channels",
                {"project_name": project_name, "backend_version": self.version},
            )
        values = await self.executor.run_safe(provider)
        if isinstance(values, MappingABC):
            values = values.get("channels", values.get("output_channels", []))
        if not isinstance(values, (list, tuple)):
            raise BackendError(
                "CAPABILITY_UNAVAILABLE",
                "Legacy output-channel metadata has an invalid shape.",
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
            if isinstance(item, MappingABC) and item.get("path")
        ]

    @staticmethod
    def _project_message(value: Any) -> ProjectMessage:
        if isinstance(value, MappingABC):
            text = value.get("text", value.get("message", ""))
            severity = value.get("severity", value.get("level", "normal"))
            source = value.get("source")
            if source is not None and not isinstance(source, MappingABC):
                source = {"value": str(source)}
            return ProjectMessage(
                str(severity),
                str(text),
                dict(source) if source is not None else None,
            )
        if isinstance(value, (tuple, list)):
            source: dict[str, Any] = {}
            if len(value) > 1 and value[1] not in (None, ""):
                source["kind"] = str(value[1])
            if len(value) > 3 and value[3] not in (None, ""):
                source["project"] = str(value[3])
            if len(value) > 4 and value[4] not in (None, ""):
                source["detail"] = str(value[4])
            return ProjectMessage(
                str(value[2]) if len(value) > 2 else "normal",
                str(value[0]) if value else "",
                source or None,
            )
        return ProjectMessage("normal", str(value), None)

    async def project_messages(self, project_name: str) -> list[ProjectMessage]:
        project = await self._project(project_name)
        messages_method = getattr(project, "messages", None)
        if messages_method is not None:
            values = await self.executor.run_safe(messages_method)
            return [self._project_message(value) for value in values]
        output = getattr(project, "output", None)
        if output is not None:
            return [
                ProjectMessage(
                    "normal",
                    str(await self.executor.run_safe(output)),
                    None,
                )
            ]
        return []

    async def parameter_grid(self, request: ParameterGridRequest) -> dict[str, Any]:
        raise BackendError(
            "CAPABILITY_UNAVAILABLE",
            "Parameter-grid operations are not exposed by the PSCAD 4.6.2 legacy Automation Library.",
            self.name,
            "parameter_grid",
            {"action": request.action},
        )

    async def list_simulation_sets(self, project_name: str) -> list[str]:
        workspace = await self.executor.run_safe(self._require_app().workspace)
        names = await self.executor.run_safe(workspace.list_simulation_sets)
        return [str(name) for name in names]

    async def _workspace(self) -> Any:
        return await self.executor.run_safe(self._require_app().workspace)

    async def _legacy_simulation_set(self, set_name: str) -> Any:
        if set_name not in await self.list_simulation_sets(""):
            raise BackendError(
                "NOT_FOUND",
                f"Simulation set '{set_name}' was not found.",
                self.name,
                "simulation_set",
                {"sim_set_name": set_name},
            )
        workspace = await self._workspace()
        method = getattr(workspace, "simulation_set", None)
        if method is None:
            method = self._require_app().simulation_set
        return await self.executor.run_safe(method, set_name)

    async def create_simulation_set(self, set_name: str) -> SimulationSetInfo:
        if set_name in await self.list_simulation_sets(""):
            raise BackendError(
                "ALREADY_EXISTS",
                f"Simulation set '{set_name}' already exists.",
                self.name,
                "create_simulation_set",
                {"sim_set_name": set_name},
            )
        workspace = await self._workspace()
        response = await self.executor.run_safe(
            workspace.create_simulation_set, set_name
        )
        legacy_support.require_success(
            response, "create_simulation_set", {"sim_set_name": set_name}
        )
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
        if set_name not in await self.list_simulation_sets(""):
            raise BackendError(
                "NOT_FOUND",
                f"Simulation set '{set_name}' was not found.",
                self.name,
                "remove_simulation_set",
                {"sim_set_name": set_name},
            )
        workspace = await self._workspace()
        response = await self.executor.run_safe(
            workspace.remove_simulation_set, set_name
        )
        legacy_support.require_success(
            response, "remove_simulation_set", {"sim_set_name": set_name}
        )
        if set_name in await self.list_simulation_sets(""):
            raise BackendError(
                "POSTCONDITION_FAILED",
                "Removed simulation set is still present.",
                self.name,
                "remove_simulation_set",
                {"sim_set_name": set_name},
            )

    async def list_simulation_set_tasks(self, set_name: str) -> list[str]:
        simset = await self._legacy_simulation_set(set_name)
        values = await self.executor.run_safe(simset.list_tasks)
        result = []
        for value in values:
            name = getattr(value, "name", value)
            if callable(name):
                name = await self.executor.run_safe(name)
            result.append(str(name))
        return result

    async def get_simulation_set_details(self, set_name: str) -> SimulationSetInfo:
        simset = await self._legacy_simulation_set(set_name)
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
        simset = await self._legacy_simulation_set(set_name)
        if task_name not in await self.list_simulation_set_tasks(set_name):
            raise BackendError(
                "NOT_FOUND",
                f"Simulation task '{task_name}' was not found.",
                self.name,
                "get_simulation_task_parameters",
                {"sim_set_name": set_name, "task_name": task_name},
            )
        task = await self.executor.run_safe(simset.task, task_name)
        values: dict[str, Any] = {}
        for key in ("namespace", "controlgroup", "volley", "affinity"):
            method = getattr(task, key, None)
            values[key] = (
                await self.executor.run_safe(method) if method is not None else None
            )
        return SimulationTaskInfo(
            task_name,
            None if values["namespace"] is None else str(values["namespace"]),
            None if values["controlgroup"] is None else str(values["controlgroup"]),
            None if values["volley"] is None else int(values["volley"]),
            None if values["affinity"] is None else int(values["affinity"]),
        )

    async def run_simulation_set(self, project_name: str, set_name: str) -> None:
        simset = await self._legacy_simulation_set(set_name)
        await self.executor.run_safe(simset.run, timeout=300.0)

    async def add_task_to_set(
        self, project_name: str, set_name: str, task_project_name: str
    ) -> None:
        simset = await self._legacy_simulation_set(set_name)
        response = await self.executor.run_safe(simset.add_tasks, task_project_name)
        legacy_support.require_success(
            response,
            "add_task_to_set",
            {"sim_set_name": set_name, "task_project_name": task_project_name},
        )
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
        simset = await self._legacy_simulation_set(set_name)
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
        response = await self.executor.run_safe(simset.remove_tasks, *task_names)
        legacy_support.require_success(
            response,
            "remove_tasks_from_set",
            {"sim_set_name": set_name, "task_names": list(task_names)},
        )
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
        unsupported = [key for key in parameters if key not in self._TASK_PARAMETER_ORDER]
        if unsupported:
            raise BackendError(
                "INVALID_ARGUMENT",
                "Unsupported simulation task parameters.",
                self.name,
                "set_simulation_task_parameters",
                {"unsupported": unsupported},
            )
        original = {key: getattr(original_record, key) for key in parameters}
        simset = await self._legacy_simulation_set(set_name)
        task = await self.executor.run_safe(simset.task, task_name)
        applied: list[str] = []
        try:
            for key in self._TASK_PARAMETER_ORDER:
                if key not in parameters:
                    continue
                method = getattr(task, key, None)
                if method is None:
                    raise BackendError(
                        "CAPABILITY_UNAVAILABLE",
                        f"Simulation task parameter '{key}' is unavailable.",
                        self.name,
                        "set_simulation_task_parameters",
                        {"unsupported": [key]},
                    )
                await self.executor.run_safe(method, parameters[key])
                applied.append(key)
            observed = await self.get_simulation_task_parameters(set_name, task_name)
            mismatches = {
                key: getattr(observed, key)
                for key, expected in parameters.items()
                if getattr(observed, key) != expected
            }
            if mismatches:
                raise BackendError(
                    "POSTCONDITION_FAILED",
                    "Simulation task parameter read-back differed.",
                    self.name,
                    "set_simulation_task_parameters",
                    {"expected": dict(parameters), "observed": mismatches},
                )
            return observed
        except Exception as operation_error:
            restore_errors: dict[str, str] = {}
            for key in reversed(applied):
                try:
                    await self.executor.run_safe(getattr(task, key), original[key])
                except Exception as restore_error:
                    restore_errors[key] = type(restore_error).__name__
            final = await self.get_simulation_task_parameters(set_name, task_name)
            unrestored = {
                key: getattr(final, key)
                for key, value in original.items()
                if getattr(final, key) != value
            }
            if restore_errors or unrestored:
                raise BackendError(
                    "PARTIAL_COMPLETION",
                    "Simulation task parameters could not be restored.",
                    self.name,
                    "set_simulation_task_parameters",
                    {
                        "requested": dict(parameters),
                        "original": original,
                        "observed": {key: getattr(final, key) for key in original},
                        "restore_errors": restore_errors,
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
        return await self.result_adapter.read_psout(
            file_path,
            max_samples=max_samples,
            channel=channel,
            summary_only=summary_only,
        )

    async def _canvas(self, project_name: str, canvas_name: str = "Main") -> Any:
        project = await self._project(project_name)
        method = getattr(project, "user_canvas", None)
        if method is None:
            method = project.canvas
        return await self.executor.run_safe(method, canvas_name)

    @staticmethod
    def _component_id(component: Any) -> int:
        value = getattr(component, "id", None)
        if value is None:
            value = getattr(component, "_id", (None,))[-1]
        return int(value)

    @staticmethod
    def _is_user_component(canvas_object: Any) -> bool:
        return all(
            callable(getattr(canvas_object, method_name, None))
            for method_name in (
                "get_definition",
                "get_parameters",
                "get_location",
            )
        )

    async def _component_info(self, component: Any) -> ComponentInfo:
        component_id = self._component_id(component)
        get_parameters = getattr(component, "get_parameters", None)
        parameters = (
            await self.executor.run_safe(get_parameters)
            if get_parameters is not None
            else {}
        )
        name = getattr(component, "name", None)
        if not name or name == getattr(component, "name", None) == "case":
            name = next(
                (
                    value
                    for key, value in parameters.items()
                    if str(key).casefold() == "name"
                ),
                "",
            )
        definition = getattr(component, "defn_name", None)
        if not definition:
            definition_proxy = await self.executor.run_safe(
                component.get_definition
            )
            definition = getattr(definition_proxy, "scoped_name", definition_proxy)
        location = await self.executor.run_safe(component.get_location)
        return ComponentInfo(
            component_id,
            str(name or ""),
            str(definition or ""),
            {"x": int(location[0]), "y": int(location[1])},
        )

    async def _legacy_components(
        self, project_name: str, canvas_name: str = "Main"
    ) -> tuple[Any, list[Any]]:
        canvas = await self._canvas(project_name, canvas_name)

        # The PSCAD 4.6.2 Automation Library models UserCanvas as a
        # ComponentCommand.  Its ``find_all()``/``list_components()`` path
        # consequently appends the canvas definition name as a component id;
        # on some 4.6.2 builds that malformed command reaches XML
        # serialization with a ``None`` attribute and fails before PSCAD can
        # answer.  Build the list-components command from the canvas scope so
        # that only project/definition are sent.  Keep the old path for test
        # doubles and older library variants which do not expose that scope.
        response = await self._legacy_scoped_list_components(canvas)
        user_cmp = getattr(canvas, "user_cmp", None)
        if isinstance(response, ET.Element) and callable(user_cmp):
            components = []
            for node in response.iter():
                if str(node.tag).split("}")[-1].casefold() != "user":
                    continue
                raw_id = node.get("id")
                if raw_id is None:
                    continue
                try:
                    component = await self.executor.run_safe(
                        user_cmp, raw_id
                    )
                except (TypeError, ValueError):
                    continue
                if self._is_user_component(component):
                    components.append(component)
            return canvas, components

        canvas_objects = await self.executor.run_safe(canvas.find_all)
        components = [
            item for item in canvas_objects if self._is_user_component(item)
        ]
        return canvas, components

    async def _legacy_scoped_list_components(self, canvas: Any) -> ET.Element | None:
        """List a legacy canvas without the Automation Library's bad id scope."""
        pscad = getattr(canvas, "_pscad", None)
        command_factory = getattr(pscad, "command", None)
        scope_values = getattr(canvas, "_scope", None)
        if not callable(command_factory) or not isinstance(scope_values, MappingABC):
            return None
        if any(value is None for value in scope_values.values()):
            return None

        command = command_factory("list-components")
        scope_name = getattr(canvas, "_scope_name", "UserCanvas")
        scope = command.scope(scope_name)
        for key, value in scope_values.items():
            ET.SubElement(scope, str(key)).set("name", str(value))
        response = await self.executor.run_safe(command.execute)
        return response if isinstance(response, ET.Element) else None

    async def _component_proxy(
        self, project_name: str, component_id: int
    ) -> tuple[Any, Any]:
        canvas, components = await self._legacy_components(project_name)
        for component in components:
            if self._component_id(component) == component_id:
                return canvas, component
        raise BackendError(
            "NOT_FOUND",
            f"Component {component_id} was not found.",
            self.name,
            "component",
            {"project": project_name, "component_id": component_id},
        )

    async def find_components(
        self,
        project_name: str,
        canvas_name: str,
        definition: str | None,
        name: str | None,
    ) -> list[ComponentInfo]:
        _canvas, components = await self._legacy_components(
            project_name, canvas_name
        )
        result = []
        for component in components:
            info = await self._component_info(component)
            definition_matches = (
                definition is None
                or info.definition == definition
                or info.definition.rsplit(":", 1)[-1] == definition
            )
            if definition_matches and (name is None or info.name == name):
                result.append(info)
        return result

    async def get_component_parameters(
        self, project_name: str, component_id: int
    ) -> dict[str, Any]:
        _canvas, component = await self._component_proxy(project_name, component_id)
        return dict(await self.executor.run_safe(component.get_parameters))

    async def set_component_parameters(
        self, project_name: str, component_id: int, parameters: Any
    ) -> None:
        _canvas, component = await self._component_proxy(project_name, component_id)
        await self.executor.run_safe(component.set_parameters, **dict(parameters))

    async def component_parameter_range(
        self, project_name: str, component_id: int, parameter_name: str
    ) -> Any:
        _canvas, component = await self._component_proxy(project_name, component_id)
        method = getattr(component, "range", None)
        if method is not None:
            return await self.executor.run_safe(method, parameter_name)
        metadata = await self._definition_metadata(component)
        try:
            return metadata.parameter_ranges[parameter_name]
        except KeyError as error:
            raise BackendError(
                "RANGE_UNAVAILABLE",
                f"No legal range is declared for '{parameter_name}'.",
                self.name,
                "component_parameter_range",
                {"component_id": component_id, "parameter": parameter_name},
            ) from error

    async def get_component_location(
        self, project_name: str, component_id: int
    ) -> tuple[int, int]:
        _canvas, component = await self._component_proxy(project_name, component_id)
        value = await self.executor.run_safe(component.get_location)
        return int(value[0]), int(value[1])

    async def set_component_location(
        self, project_name: str, component_id: int, location: tuple[int, int]
    ) -> None:
        _canvas, component = await self._component_proxy(project_name, component_id)
        await self.executor.run_safe(component.set_location, *location)
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
        commands = {
            "right": "IDM_ROTATERIGHT",
            "left": "IDM_ROTATELEFT",
            "180": "IDM_ROTATE180",
        }
        if direction not in commands:
            raise ValueError("direction must be right, left, or 180.")
        _canvas, component = await self._component_proxy(project_name, component_id)
        await self.executor.run_safe(component._generic, commands[direction])
        await self._record_orientation_transform(
            project_name,
            component_id,
            {"right": 1, "left": 3, "180": 2}[direction],
        )

    async def mirror_component(
        self, project_name: str, component_id: int, axis: str
    ) -> None:
        commands = {"horizontal": "IDM_MIRROR", "vertical": "IDM_FLIP"}
        if axis not in commands:
            raise ValueError("axis must be horizontal or vertical.")
        _canvas, component = await self._component_proxy(project_name, component_id)
        await self.executor.run_safe(component._generic, commands[axis])
        await self._record_orientation_transform(
            project_name,
            component_id,
            {"horizontal": 6, "vertical": 4}[axis],
        )

    async def _record_orientation_transform(
        self, project_name: str, component_id: int, operation: int
    ) -> None:
        raw_current = await self._legacy_component_orientation(
            project_name, str(component_id)
        )
        if raw_current is None:
            return
        matrices = {
            0: (1, 0, 0, 1),
            1: (0, -1, 1, 0),
            2: (-1, 0, 0, -1),
            3: (0, 1, -1, 0),
            4: (-1, 0, 0, 1),
            5: (0, -1, -1, 0),
            6: (1, 0, 0, -1),
            7: (0, 1, 1, 0),
        }
        left = matrices[operation]
        right = matrices[int(raw_current)]
        composed = (
            left[0] * right[0] + left[1] * right[2],
            left[0] * right[1] + left[1] * right[3],
            left[2] * right[0] + left[3] * right[2],
            left[2] * right[1] + left[3] * right[3],
        )
        resulting = next(
            code for code, matrix in matrices.items() if matrix == composed
        )
        self._component_orientations[(project_name, component_id)] = resulting

    async def clone_component(
        self, project_name: str, component_id: int, location: tuple[int, int]
    ) -> ComponentInfo:
        canvas, component = await self._component_proxy(project_name, component_id)
        definition_proxy = await self.executor.run_safe(
            component.get_definition
        )
        scoped_name = str(
            getattr(definition_proxy, "scoped_name", definition_proxy)
        )
        if ":" not in scoped_name:
            raise BackendError(
                "DEFINITION_METADATA_UNAVAILABLE",
                f"Component definition '{scoped_name}' is not scoped.",
                self.name,
                "clone_component",
            )
        library, definition_name = scoped_name.split(":", 1)
        parameters = dict(
            await self.executor.run_safe(component.get_parameters)
        )
        clone = await self.executor.run_safe(
            canvas.add_component,
            library,
            definition_name,
            *location,
        )
        if clone is None or not self._is_user_component(clone):
            raise BackendError(
                "POSTCONDITION_FAILED",
                "Clone did not create a user component.",
                self.name,
                "clone_component",
            )
        if parameters:
            await self.executor.run_safe(clone.set_parameters, **parameters)
        info = await self._component_info(clone)
        if (
            info.id == component_id
            or info.definition != scoped_name
            or info.location != {"x": location[0], "y": location[1]}
        ):
            raise BackendError(
                "POSTCONDITION_FAILED",
                "Cloned component identity, definition, or location could not be verified.",
                self.name,
                "clone_component",
            )
        source_orientation = await self._legacy_component_orientation(
            project_name, str(component_id)
        )
        if source_orientation is not None:
            self._component_orientations[(project_name, info.id)] = int(
                source_orientation
            )
        return info

    async def get_component_ports(
        self, project_name: str, component_id: int
    ) -> list[PortInfo]:
        canvas, component = await self._component_proxy(project_name, component_id)
        port_names = list(getattr(component, "port_names", []))
        ports_method = getattr(component, "ports", None)
        metadata = (
            await self.executor.run_safe(ports_method)
            if ports_method is not None
            else {}
        )
        if not port_names and hasattr(metadata, "keys"):
            port_names = list(metadata.keys())
        static_ports = {}
        if not port_names:
            definition_metadata = await self._definition_metadata(component)
            static_ports = {
                item.name: item for item in definition_metadata.ports
            }
            port_names = list(static_ports)
        else:
            try:
                definition_metadata = await self._definition_metadata(component)
            except BackendError:
                definition_metadata = DefinitionMetadata((), {})
            static_ports = {
                item.name: item for item in definition_metadata.ports
            }
        result = []
        for port_name in port_names:
            static_port = static_ports.get(port_name)
            location = None
            if static_port is not None:
                location = await self._legacy_static_port_location(
                    project_name,
                    canvas,
                    component,
                    static_port.x,
                    static_port.y,
                )
            if location is None:
                location_method = getattr(component, "get_port_location", None)
                if location_method is not None:
                    location = await self.executor.run_safe(
                        location_method, port_name
                    )
            if location is None:
                continue
            item = metadata.get(port_name) if hasattr(metadata, "get") else None
            if item is None:
                item = static_ports.get(port_name)
            result.append(
                PortInfo(
                    str(port_name),
                    int(location[0]),
                    int(location[1]),
                    getattr(item, "dim", None),
                    str(getattr(item, "type", "")) or None,
                )
            )
        return result

    async def _legacy_static_port_location(
        self,
        project_name: str,
        canvas: Any,
        component: Any,
        port_x: int,
        port_y: int,
    ) -> tuple[int, int] | None:
        list_components = getattr(canvas, "list_components", None)
        if list_components is None:
            return None
        response = await self.executor.run_safe(list_components)
        component_id = str(self._component_id(component))
        instance = next(
            (
                node
                for node in response.findall("components/User")
                if node.get("id") == component_id
            ),
            None,
        )
        if instance is None:
            return None
        raw_orientation = instance.get("orient")
        if raw_orientation is None:
            raw_orientation = await self._legacy_component_orientation(
                project_name, component_id
            )
        if raw_orientation is None:
            return None
        orientation = int(raw_orientation)
        transforms = {
            0: (port_x, port_y),
            1: (-port_y, port_x),
            2: (-port_x, -port_y),
            3: (port_y, -port_x),
            4: (-port_x, port_y),
            5: (-port_y, -port_x),
            6: (port_x, -port_y),
            7: (port_y, port_x),
        }
        try:
            offset_x, offset_y = transforms[orientation]
        except KeyError:
            return None
        origin = await self.executor.run_safe(component.get_location)
        return (
            int(origin[0]) + offset_x,
            int(origin[1]) + offset_y,
        )

    async def _legacy_component_orientation(
        self, project_name: str, component_id: str
    ) -> str | None:
        cached = self._component_orientations.get(
            (project_name, int(component_id))
        )
        if cached is not None:
            return str(cached)
        path = self.definition_paths.get(project_name)
        if path is None or not path.exists():
            return None

        def read_orientation() -> str | None:
            root = ET.parse(path).getroot()
            instance = next(
                (
                    node
                    for node in root.findall(".//User")
                    if node.get("id") == component_id
                ),
                None,
            )
            return instance.get("orient") if instance is not None else None

        try:
            return await asyncio.to_thread(read_orientation)
        except (OSError, ET.ParseError):
            return None

    async def _definition_metadata(self, component: Any) -> DefinitionMetadata:
        definition_proxy = await self.executor.run_safe(component.get_definition)
        scoped_name = str(
            getattr(definition_proxy, "scoped_name", definition_proxy)
        )
        if ":" not in scoped_name:
            raise BackendError(
                "DEFINITION_METADATA_UNAVAILABLE",
                f"Component definition '{scoped_name}' is not scoped.",
                self.name,
                "definition_metadata",
            )
        scope, definition_name = scoped_name.split(":", 1)
        path = self.definition_paths.get(scope)
        if path is None and scope.casefold() == "master":
            path = await self._discover_master_library()
            if path is not None:
                self.definition_paths[scope] = path
        if path is None or not path.exists():
            raise BackendError(
                "DEFINITION_METADATA_UNAVAILABLE",
                f"The source file for definition '{scoped_name}' was not found.",
                self.name,
                "definition_metadata",
                {"scope": scope},
            )
        try:
            return await asyncio.to_thread(
                read_definition_metadata, path, definition_name
            )
        except (OSError, ET.ParseError, KeyError) as error:
            raise BackendError(
                "DEFINITION_METADATA_UNAVAILABLE",
                f"Could not read definition '{scoped_name}': {error}",
                self.name,
                "definition_metadata",
                {"path": str(path)},
            ) from error

    async def _discover_master_library(self) -> Path | None:
        if self.automation is None:
            return None
        display_name = (
            f"PSCAD {self.version} ({'x64' if self.x64 else 'x86'})"
        )
        try:
            controller_source = self.automation.controller
            controller_factory = (
                controller_source
                if callable(controller_source)
                else controller_source.Controller
            )
            executable = await self.executor.run_safe(
                lambda: controller_factory().get_param(
                    "pscad", display_name
                )
            )
        except Exception:
            return None
        executable_path = Path(executable).resolve()
        for parent in (executable_path.parent, *executable_path.parents):
            candidate = parent / "master.pslx"
            if candidate.exists():
                return candidate
        return None

    async def set_component_enabled(
        self, project_name: str, component_id: int, enabled: bool
    ) -> None:
        canvas, component = await self._component_proxy(
            project_name, component_id
        )
        project = await self._project(project_name)
        before = await self._component_layers(canvas, component_id)
        details = {"project": project_name, "component_id": component_id}

        if enabled:
            if self._disabled_layer in before:
                response = await self.executor.run_safe(
                    component.remove_from_layer, self._disabled_layer
                )
                legacy_support.require_success(
                    response, "enable_component", details
                )
        else:
            layer_is_known = (
                self._disabled_layer in before
                or await self._layer_is_known(
                    project_name, self._disabled_layer
                )
            )
            if not layer_is_known:
                response = await self.executor.run_safe(
                    project.create_layer, self._disabled_layer
                )
                legacy_support.require_success(
                    response, "disable_component", details
                )
                self._known_managed_layers.add(
                    (project_name, self._disabled_layer)
                )
            response = await self.executor.run_safe(
                project.set_layer, self._disabled_layer, "disabled"
            )
            legacy_support.require_success(
                response, "disable_component", details
            )
            if self._disabled_layer not in before:
                response = await self.executor.run_safe(
                    component.add_to_layer, self._disabled_layer
                )
                legacy_support.require_success(
                    response, "disable_component", details
                )

        after = await self._component_layers(canvas, component_id)
        has_disabled_layer = self._disabled_layer in after
        if has_disabled_layer is enabled:
            raise BackendError(
                "POSTCONDITION_FAILED",
                "Component layer state did not change as requested.",
                self.name,
                "set_component_enabled",
                {
                    "project": project_name,
                    "component_id": component_id,
                    "layers": sorted(after),
                },
            )

    @staticmethod
    def _layer_names(value: str | None) -> set[str]:
        if not isinstance(value, str):
            return set()
        return {
            name
            for name in re.split(r"[;,\s]+", value)
            if name
        }

    async def _component_layers(
        self, canvas: Any, component_id: int
    ) -> set[str]:
        response = await self.executor.run_safe(canvas.list_components)
        if not isinstance(response, ET.Element):
            raise BackendError(
                "UNEXPECTED_RESPONSE",
                "PSCAD did not return component XML for layer verification.",
                self.name,
                "set_component_enabled",
                {"component_id": component_id},
            )
        if response.get("success") is not None:
            legacy_support.require_success(
                response,
                "set_component_enabled",
                {"component_id": component_id},
            )
        expected_id = str(component_id)
        for node in response.iter():
            if node.get("id") != expected_id:
                continue
            return self._layer_names(
                node.get("layer") or node.get("layers")
            )
        raise BackendError(
            "POSTCONDITION_FAILED",
            "PSCAD did not list the component for layer verification.",
            self.name,
            "set_component_enabled",
            {"component_id": component_id},
        )

    async def _layer_is_known(
        self, project_name: str, layer_name: str
    ) -> bool:
        if (project_name, layer_name) in self._known_managed_layers:
            return True
        path = self.definition_paths.get(project_name)
        if path is None or not path.is_file():
            return False
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            return False
        for node in root.iter():
            tag = str(node.tag).split("}")[-1].casefold()
            if tag == "layer" and node.get("name") == layer_name:
                return True
            layers = self._layer_names(
                node.get("layer") or node.get("layers")
            )
            if layer_name in layers:
                return True
        return False

    async def delete_component(self, project_name: str, component_id: int) -> None:
        await self.delete_components(project_name, [component_id])

    async def delete_components(
        self, project_name: str, component_ids: Sequence[int]
    ) -> None:
        unique_ids = list(dict.fromkeys(int(value) for value in component_ids))
        if not unique_ids:
            raise ValueError("component_ids must not be empty.")
        canvas = await self._canvas(project_name, "Main")

        targets = []
        for component_id in unique_ids:
            _target_canvas, component = await self._component_proxy(
                project_name, component_id
            )
            targets.append(component)

        ports_by_component = {
            component_id: await self.get_component_ports(
                project_name, component_id
            )
            for component_id in unique_ids
        }
        target_ports = {
            (port.x, port.y)
            for ports in ports_by_component.values()
            for port in ports
        }
        selection_bounds = {}
        for component_id, component in zip(unique_ids, targets):
            points = [
                (port.x, port.y)
                for port in ports_by_component[component_id]
            ]
            location_method = getattr(component, "get_location", None)
            try:
                if location_method is not None:
                    location = await self.executor.run_safe(location_method)
                else:
                    location = await self.executor.run_safe(
                        lambda item=component: item.location
                    )
            except Exception:
                location = None
            if location is not None:
                points.append((int(location[0]), int(location[1])))
            if points:
                selection_bounds[component_id] = self._selection_bounds(
                    points, padding=self._canvas_grid * 2
                )
        objects = list(await self.executor.run_safe(canvas.find_all))
        wires = []
        seen_wire_ids = set()
        for value in objects:
            if type(value).__name__ != "WireOrthogonal":
                continue
            vertices = await self._absolute_wire_vertices(value)
            endpoints = (
                {tuple(vertices[0]), tuple(vertices[-1])}
                if vertices
                else set()
            )
            if not endpoints.intersection(target_ports):
                continue
            wire_id = self._component_id(value)
            if wire_id in seen_wire_ids:
                continue
            seen_wire_ids.add(wire_id)
            wires.append(value)
            selection_bounds[wire_id] = self._selection_bounds(
                vertices, padding=self._canvas_grid
            )

        await self._execute_deletion_plan(
            project_name,
            canvas,
            targets,
            wires,
            selection_bounds,
        )

    async def _absolute_wire_vertices(
        self, wire: Any
    ) -> list[tuple[int, int]]:
        vertices = [
            (int(point[0]), int(point[1]))
            for point in await self.executor.run_safe(
                lambda item=wire: item.vertices
            )
        ]
        try:
            location = await self.executor.run_safe(
                lambda item=wire: item.location
            )
        except (AttributeError, BackendError):
            location = None
        if location is None:
            return vertices
        origin_x, origin_y = int(location[0]), int(location[1])
        return [
            (origin_x + x, origin_y + y)
            for x, y in vertices
        ]

    @staticmethod
    def _selection_bounds(
        points: Sequence[tuple[int, int]], *, padding: int
    ) -> tuple[int, int, int, int]:
        if not points:
            raise ValueError("selection points must not be empty.")
        x_values = [int(point[0]) for point in points]
        y_values = [int(point[1]) for point in points]
        return (
            min(x_values) - padding,
            max(y_values) + padding,
            max(x_values) + padding,
            min(y_values) - padding,
        )

    @staticmethod
    def _merged_selection_bounds(
        bounds: Sequence[tuple[int, int, int, int]],
    ) -> tuple[int, int, int, int]:
        if not bounds:
            raise ValueError("selection bounds must not be empty.")
        return (
            min(value[0] for value in bounds),
            max(value[1] for value in bounds),
            max(value[2] for value in bounds),
            min(value[3] for value in bounds),
        )

    async def _selection_conflicts(
        self,
        project_name: str,
        canvas: Any,
        bounds: tuple[int, int, int, int],
        target_ids: Sequence[int],
    ) -> list[int]:
        left, top, right, bottom = bounds
        target_id_set = set(target_ids)
        conflicts = []
        for value in list(await self.executor.run_safe(canvas.find_all)):
            if type(value).__name__ == "WireOrthogonal":
                continue
            try:
                object_id = self._component_id(value)
            except (TypeError, ValueError) as error:
                raise BackendError(
                    "CAPABILITY_UNAVAILABLE",
                    "PSCAD 4.6.2 returned an unidentified object inside "
                    "the candidate deletion selection.",
                    self.name,
                    "delete_components",
                    {
                        "project": project_name,
                        "target_component_ids": sorted(target_id_set),
                    },
                ) from error
            if object_id in target_id_set:
                continue
            location_method = getattr(value, "get_location", None)
            try:
                if location_method is not None:
                    location = await self.executor.run_safe(
                        location_method
                    )
                else:
                    location = await self.executor.run_safe(
                        lambda item=value: item.location
                    )
            except Exception:
                conflicts.append(object_id)
                continue
            if location is None:
                conflicts.append(object_id)
                continue
            x, y = int(location[0]), int(location[1])
            if left <= x <= right and bottom <= y <= top:
                conflicts.append(object_id)
        return sorted(set(conflicts))

    async def _canvas_object_ids(self, canvas: Any) -> set[int]:
        response = await self.executor.run_safe(canvas.list_components)
        if not isinstance(response, ET.Element):
            raise BackendError(
                "UNEXPECTED_RESPONSE",
                "PSCAD did not return component XML after deletion.",
                self.name,
                "delete_components",
            )
        if response.get("success") is not None:
            legacy_support.require_success(
                response, "delete_components", {}
            )
        identifiers = set()
        for node in response.iter():
            raw_id = node.get("id")
            if raw_id is None:
                continue
            try:
                identifiers.add(int(raw_id))
            except ValueError:
                continue
        return identifiers

    async def _execute_deletion_plan(
        self,
        project_name: str,
        canvas: Any,
        targets: Sequence[Any],
        wires: Sequence[Any],
        selection_bounds: Mapping[int, tuple[int, int, int, int]],
    ) -> None:
        target_ids = [self._component_id(value) for value in targets]
        wire_ids = [self._component_id(value) for value in wires]
        completed_target_ids = []
        completed_wire_ids = []

        select_components = getattr(canvas, "select_components", None)
        generic = getattr(canvas, "_generic", None)
        use_canvas_selection = (
            select_components is not None
            and generic is not None
            and all(value in selection_bounds for value in target_ids)
        )
        combined_bounds = None
        if use_canvas_selection:
            combined_bounds = self._merged_selection_bounds(
                [selection_bounds[value] for value in target_ids]
            )
            conflicts = await self._selection_conflicts(
                project_name, canvas, combined_bounds, target_ids
            )
            if conflicts:
                raise BackendError(
                    "CAPABILITY_UNAVAILABLE",
                    "PSCAD 4.6.2 cannot safely select the requested batch "
                    "without including other canvas objects.",
                    self.name,
                    "delete_components",
                    {
                        "project": project_name,
                        "conflicting_object_ids": conflicts,
                    },
                )

        async def delete(value: Any, object_id: int, operation: str) -> None:
            response = await self.executor.run_safe(value.delete)
            if response is not None:
                legacy_support.require_success(
                    response,
                    operation,
                    {"project": project_name, "object_id": object_id},
                )

        mutation_error: Exception | None = None
        try:
            if use_canvas_selection and combined_bounds is not None:
                response = await self.executor.run_safe(
                    select_components, *combined_bounds
                )
                legacy_support.require_success(
                    response,
                    "select_delete_batch",
                    {"project": project_name, "component_ids": target_ids},
                )
                response = await self.executor.run_safe(
                    generic, "IDM_DELETE"
                )
                legacy_support.require_success(
                    response,
                    "delete_batch",
                    {"project": project_name, "component_ids": target_ids},
                )
                completed_wire_ids.extend(wire_ids)
                completed_target_ids.extend(target_ids)
            else:
                for wire, wire_id in zip(wires, wire_ids):
                    await delete(wire, wire_id, "delete_wire")
                    completed_wire_ids.append(wire_id)
                for component, component_id in zip(targets, target_ids):
                    await delete(
                        component, component_id, "delete_component"
                    )
                    completed_target_ids.append(component_id)
        except Exception as error:
            mutation_error = error

        try:
            remaining_ids = await self._canvas_object_ids(canvas)
        except Exception as verification_error:
            remaining_ids = None
            if mutation_error is None:
                mutation_error = verification_error

        if remaining_ids is None:
            deleted_component_ids = completed_target_ids
            deleted_wire_ids = completed_wire_ids
            remaining_component_ids = [
                value for value in target_ids if value not in completed_target_ids
            ]
            remaining_wire_ids = [
                value for value in wire_ids if value not in completed_wire_ids
            ]
        else:
            deleted_component_ids = [
                value for value in target_ids if value not in remaining_ids
            ]
            deleted_wire_ids = [
                value for value in wire_ids if value not in remaining_ids
            ]
            remaining_component_ids = [
                value for value in target_ids if value in remaining_ids
            ]
            remaining_wire_ids = [
                value for value in wire_ids if value in remaining_ids
            ]

        if (
            mutation_error is not None
            or remaining_component_ids
            or remaining_wire_ids
        ):
            raise BackendError(
                "PARTIAL_COMPLETION",
                "The component deletion plan did not complete.",
                self.name,
                "delete_components",
                {
                    "deleted_component_ids": deleted_component_ids,
                    "deleted_wire_ids": deleted_wire_ids,
                    "remaining_component_ids": remaining_component_ids,
                    "remaining_wire_ids": remaining_wire_ids,
                },
            ) from mutation_error

        for component_id in target_ids:
            self._component_orientations.pop(
                (project_name, component_id), None
            )

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
        if orientation not in range(8):
            raise ValueError("orientation must be between 0 and 7.")
        canvas = await self._canvas(project_name, canvas_name)
        component = await self.executor.run_safe(
            canvas.add_component, library, definition, *location
        )
        if component is None or not self._is_user_component(component):
            raise BackendError(
                "POSTCONDITION_FAILED",
                "Component creation did not return a user component.",
                self.name,
                "add_component",
            )
        if parameters:
            await self.executor.run_safe(
                component.set_parameters, **dict(parameters)
            )
        command = getattr(component, "_generic", None)
        if command is not None:
            if orientation >= 4:
                await self.executor.run_safe(command, "IDM_FLIP")
            rotations = orientation - 4 if orientation >= 4 else orientation
            for _ in range(rotations):
                await self.executor.run_safe(command, "IDM_ROTATERIGHT")
        info = await self._component_info(component)
        requested_location = {"x": location[0], "y": location[1]}
        snapped_location = {
            "x": round(location[0] / self._canvas_grid) * self._canvas_grid,
            "y": round(location[1] / self._canvas_grid) * self._canvas_grid,
        }
        if (
            info.definition != f"{library}:{definition}"
            or info.location not in (requested_location, snapped_location)
        ):
            raise BackendError(
                "POSTCONDITION_FAILED",
                "Created component definition or location could not be verified.",
                self.name,
                "add_component",
                {
                    "expected_definition": f"{library}:{definition}",
                    "actual_definition": info.definition,
                    "requested_location": requested_location,
                    "expected_snapped_location": snapped_location,
                    "actual_location": info.location,
                },
            )
        self._component_orientations[(project_name, info.id)] = orientation
        return info

    @staticmethod
    def _canvas_endpoints_payload(
        object_id: int, points: Any
    ) -> dict[str, Any]:
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
        canvas = await self._canvas(project_name, canvas_name)
        wire = await self.executor.run_safe(canvas.add_wire, *vertices)
        if wire is None:
            raise BackendError(
                "POSTCONDITION_FAILED",
                "Wire creation returned no wire.",
                self.name,
                "create_wire",
            )
        return self._canvas_endpoints_payload(
            self._component_id(wire), vertices
        )

    async def _add_legacy_canvas_object(
        self, canvas: Any, class_id: str
    ) -> tuple[int, Any]:
        command = await self.executor.run_safe(canvas.command, "add-components")
        component = command.tag("component")
        component.set("classid", class_id)
        response = await self.executor.run_safe(command.execute)
        node = response.find("components/component")
        if node is None or node.get("id") is None:
            raise BackendError(
                "POSTCONDITION_FAILED",
                f"Creation of {class_id} returned no component ID.",
                self.name,
                "create_canvas_object",
                {"class_id": class_id},
            )
        return int(node.get("id")), response

    async def _legacy_canvas_proxy(
        self, canvas: Any, class_id: str, object_id: int
    ) -> Any:
        if class_id == "Bus":
            return await self.executor.run_safe(canvas.bus, object_id)
        if class_id == "GraphFrame":
            return await self.executor.run_safe(canvas.graph_frame, object_id)
        factory = getattr(self.automation, "component_command_factory", None)
        if factory is not None:
            return factory(class_id, object_id)
        module = importlib.import_module("mhrc.automation.component")
        return module.ComponentCommand(canvas, class_id, object_id)

    async def _set_legacy_proxy_location(
        self, proxy: Any, location: tuple[int, int]
    ) -> None:
        method = getattr(proxy, "set_location", None)
        if method is not None:
            await self.executor.run_safe(method, *location)
        else:
            await self.executor.run_safe(
                setattr, proxy, "location", tuple(location)
            )

    async def _legacy_canvas_object_exists(
        self, canvas: Any, object_id: int, class_id: str
    ) -> bool:
        response = await self.executor.run_safe(canvas.list_components)
        return any(
            node.get("id") == str(object_id)
            and node.get("classid") == class_id
            for node in response.findall("components/*")
        )

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
        canvas = await self._canvas(project_name, canvas_name)
        object_id, _response = await self._add_legacy_canvas_object(
            canvas, "Bus"
        )
        bus = await self._legacy_canvas_proxy(canvas, "Bus", object_id)
        await self._set_legacy_proxy_location(bus, vertices[0])
        x0, y0 = vertices[0]
        relative = [(x - x0, y - y0) for x, y in vertices]
        await self.executor.run_safe(setattr, bus, "vertices", relative)
        if parameters:
            await self.executor.run_safe(
                bus.set_parameters, **dict(parameters)
            )
        return self._canvas_endpoints_payload(object_id, vertices)

    async def create_connection(
        self,
        project_name: str,
        canvas_name: str,
        p1: tuple[int, int],
        p2: tuple[int, int],
        label: str | None,
        electrical: bool | None,
    ) -> dict[str, Any]:
        if label is None and electrical is None:
            await self.create_wire(project_name, canvas_name, [p1, p2])
            return {"connected": True}
        if label is None or electrical is None:
            raise ValueError(
                "label and electrical must either both be provided or both omitted."
            )
        used_names = {
            item.name
            for item in await self.find_components(
                project_name, canvas_name, None, None
            )
        }
        unique_label = label
        suffix = 2
        while unique_label in used_names:
            unique_label = f"{label}_{suffix}"
            suffix += 1
        definition = "nodelabel" if electrical else "datalabel"
        for point in (p1, p2):
            await self.add_component(
                project_name,
                canvas_name,
                "master",
                definition,
                point,
                0,
                {"Name": unique_label},
            )
        return {"label": unique_label}

    async def create_annotation(
        self,
        project_name: str,
        canvas_name: str,
        location: tuple[int, int],
        line1: str,
        line2: str,
    ) -> ComponentInfo:
        return await self.add_component(
            project_name,
            canvas_name,
            "master",
            "annotation",
            location,
            0,
            {"AL1": line1, "AL2": line2},
        )

    async def create_graph_frame(
        self, project_name: str, canvas_name: str, location: tuple[int, int]
    ) -> dict[str, Any]:
        canvas = await self._canvas(project_name, canvas_name)
        object_id, _response = await self._add_legacy_canvas_object(
            canvas, "GraphFrame"
        )
        proxy = await self._legacy_canvas_proxy(
            canvas, "GraphFrame", object_id
        )
        await self._set_legacy_proxy_location(proxy, location)
        if not await self._legacy_canvas_object_exists(
            canvas, object_id, "GraphFrame"
        ):
            raise BackendError(
                "POSTCONDITION_FAILED",
                "Graph frame could not be found after creation.",
                self.name,
                "create_graph_frame",
            )
        return {"id": object_id}

    async def create_control_frame(
        self, project_name: str, canvas_name: str, location: tuple[int, int]
    ) -> dict[str, Any]:
        canvas = await self._canvas(project_name, canvas_name)
        object_id, _response = await self._add_legacy_canvas_object(
            canvas, "ControlFrame"
        )
        proxy = await self._legacy_canvas_proxy(
            canvas, "ControlFrame", object_id
        )
        await self._set_legacy_proxy_location(proxy, location)
        if not await self._legacy_canvas_object_exists(
            canvas, object_id, "ControlFrame"
        ):
            raise BackendError(
                "POSTCONDITION_FAILED",
                "Control frame could not be found after creation.",
                self.name,
                "create_control_frame",
            )
        return {"frame_id": object_id, "control_ids": []}

    async def list_canvas_components(
        self, project_name: str, canvas_name: str
    ) -> list[dict[str, Any]]:
        canvas = await self._canvas(project_name, canvas_name)
        values = list(await self.executor.run_safe(canvas.find_all))
        result = []
        for value in values:
            parameters_method = getattr(value, "get_parameters", None)
            parameters = (
                await self.executor.run_safe(parameters_method)
                if parameters_method is not None
                else {}
            )
            name = next(
                (
                    item
                    for key, item in parameters.items()
                    if str(key).casefold() == "name"
                ),
                getattr(value, "name", None),
            )
            definition = getattr(value, "defn_name", None)
            definition_method = getattr(value, "get_definition", None)
            if not definition and definition_method is not None:
                definition_proxy = await self.executor.run_safe(
                    definition_method
                )
                definition = getattr(
                    definition_proxy, "scoped_name", definition_proxy
                )
            if not definition:
                definition = type(value).__name__
            location_method = getattr(value, "get_location", None)
            location = (
                await self.executor.run_safe(location_method)
                if location_method is not None
                else getattr(value, "location", None)
            )
            result.append(
                {
                    "id": self._component_id(value),
                    "name": str(name) if name else None,
                    "definition": str(definition),
                    "location": list(location) if location is not None else None,
                }
            )
        known_ids = {item["id"] for item in result}
        response = await self.executor.run_safe(canvas.list_components)
        for node in response.findall("components/*"):
            raw_id = node.get("id")
            if raw_id is None or int(raw_id) in known_ids:
                continue
            class_id = str(node.get("classid") or node.tag)
            location = None
            if class_id == "ControlFrame":
                proxy = await self._legacy_canvas_proxy(
                    canvas, class_id, int(raw_id)
                )
                location_method = getattr(proxy, "get_location", None)
                location = (
                    await self.executor.run_safe(location_method)
                    if location_method is not None
                    else getattr(proxy, "location", None)
                )
            result.append(
                {
                    "id": int(raw_id),
                    "name": node.get("name") or None,
                    "definition": class_id,
                    "location": list(location) if location is not None else None,
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
        canvas = await self._canvas(project_name, canvas_name)
        candidates = []
        seen = set()

        def add_candidate(rectangle: legacy_support.Rect) -> None:
            if rectangle not in seen:
                seen.add(rectangle)
                candidates.append(rectangle)

        method = getattr(canvas, "closest_empty_rect", None)
        if method is not None:
            rectangle = await self.executor.run_safe(
                method, width, height, near
            )
            add_candidate(
                legacy_support.Rect(
                    legacy_support.snap_to_grid(
                        int(rectangle.x), self._canvas_grid
                    ),
                    legacy_support.snap_to_grid(
                        int(rectangle.y), self._canvas_grid
                    ),
                    width,
                    height,
                )
            )
        for candidate in legacy_support.candidate_rectangles(
            near,
            width,
            height,
            grid=self._canvas_grid,
            rings=100,
        ):
            add_candidate(candidate)

        occupied = await self._occupied_rectangles(
            project_name, canvas_name, canvas
        )
        if not any(
            all(
                not rectangle.intersects(candidate, margin=self._canvas_grid)
                for rectangle in occupied
            )
            for candidate in candidates
        ):
            raise BackendError(
                "NO_EMPTY_SPACE",
                "No empty canvas location was found within the search bound.",
                self.name,
                "find_empty_space",
            )

        refreshed = await self._occupied_rectangles(
            project_name, canvas_name, canvas
        )
        for candidate in candidates:
            if all(
                not rectangle.intersects(candidate, margin=self._canvas_grid)
                for rectangle in refreshed
            ):
                return {
                    "x": candidate.x,
                    "y": candidate.y,
                    "width": candidate.width,
                    "height": candidate.height,
                }
        raise BackendError(
            "NO_EMPTY_SPACE",
            "No empty canvas location was found within the search bound.",
            self.name,
            "find_empty_space",
        )

    async def _occupied_rectangles(
        self, project_name: str, canvas_name: str, canvas: Any
    ) -> list[legacy_support.Rect]:
        response = await self.executor.run_safe(canvas.list_components)
        if not isinstance(response, ET.Element):
            raise BackendError(
                "UNEXPECTED_RESPONSE",
                "PSCAD did not return canvas XML for empty-space search.",
                self.name,
                "find_empty_space",
            )
        if response.get("success") is not None:
            legacy_support.require_success(
                response, "find_empty_space", {}
            )
        nodes = list(response.findall("components/*"))
        saved_rectangles = await asyncio.to_thread(
            self._saved_canvas_rectangles, project_name, canvas_name
        )
        sparse_ids = {
            int(node.get("id"))
            for node in nodes
            if node.get("id", "").isdigit()
            and any(node.get(key) is None for key in ("x", "y", "w", "h"))
        }
        live_locations: dict[int, tuple[int, int]] = {}
        if sparse_ids:
            objects = list(await self.executor.run_safe(canvas.find_all))
            for proxy in objects:
                object_id = self._component_id(proxy)
                if object_id not in sparse_ids:
                    continue
                location_method = getattr(proxy, "get_location", None)
                try:
                    if location_method is not None:
                        location = await self.executor.run_safe(
                            location_method
                        )
                    else:
                        location = await self.executor.run_safe(
                            lambda item=proxy: item.location
                        )
                except Exception:
                    continue
                if location is not None and len(location) >= 2:
                    live_locations[object_id] = (
                        int(location[0]),
                        int(location[1]),
                    )

        rectangles = []
        try:
            for node in nodes:
                raw_id = node.get("id")
                object_id = int(raw_id) if raw_id is not None else None
                saved = saved_rectangles.get(object_id)
                live = live_locations.get(object_id)
                raw_x = node.get("x")
                raw_y = node.get("y")
                raw_width = node.get("w")
                raw_height = node.get("h")
                x = (
                    int(raw_x)
                    if raw_x is not None
                    else saved.get("x")
                    if saved is not None and saved.get("x") is not None
                    else live[0]
                    if live is not None
                    else 0
                )
                y = (
                    int(raw_y)
                    if raw_y is not None
                    else saved.get("y")
                    if saved is not None and saved.get("y") is not None
                    else live[1]
                    if live is not None
                    else 0
                )
                rectangle_width = (
                    int(raw_width)
                    if raw_width is not None
                    else saved.get("w")
                    if saved is not None and saved.get("w") is not None
                    else 36
                )
                rectangle_height = (
                    int(raw_height)
                    if raw_height is not None
                    else saved.get("h")
                    if saved is not None and saved.get("h") is not None
                    else 36
                )
                rectangles.append(
                    legacy_support.Rect(
                        x,
                        y,
                        max(rectangle_width, 1),
                        max(rectangle_height, 1),
                    )
                )
        except (TypeError, ValueError) as error:
            raise BackendError(
                "UNEXPECTED_RESPONSE",
                "PSCAD returned invalid canvas rectangle metadata.",
                self.name,
                "find_empty_space",
            ) from error
        return rectangles

    def _saved_canvas_rectangles(
        self, project_name: str, canvas_name: str
    ) -> dict[int, dict[str, int]]:
        path = self.definition_paths.get(project_name)
        if path is None or not path.is_file():
            return {}
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            return {}

        definition = next(
            (
                node
                for node in root.iter()
                if str(node.tag).split("}")[-1] == "Definition"
                and node.get("name") == canvas_name
            ),
            None,
        )
        if definition is None:
            return {}
        schematic = next(
            (
                child
                for child in definition
                if str(child.tag).split("}")[-1] == "schematic"
            ),
            None,
        )
        if schematic is None:
            return {}

        rectangles: dict[int, dict[str, int]] = {}
        for node in schematic:
            raw_id = node.get("id")
            if raw_id is None:
                continue
            try:
                object_id = int(raw_id)
            except ValueError:
                continue
            geometry = {}
            for attribute in ("x", "y", "w", "h"):
                raw_value = node.get(attribute)
                if raw_value is None:
                    continue
                try:
                    geometry[attribute] = int(raw_value)
                except ValueError:
                    continue
            if geometry:
                rectangles[object_id] = geometry
        return rectangles
    async def inspect_canvas_topology(
        self, project_name: str, canvas_name: str
    ) -> TopologySnapshot:
        project = await self._project(project_name)
        source_hashes: dict[Path, str] = {}
        saved_topology = await asyncio.to_thread(
            self._saved_topology_components,
            project_name,
        )
        if saved_topology is None:
            saved_components = None
            saved_modules = None
        else:
            saved_components, saved_modules = saved_topology
        captures, unresolved = await self._legacy_topology_captures(
            project,
            project_name,
            canvas_name,
            source_hashes,
            saved_components,
            saved_modules,
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
        components_supported = True
        conductors_supported = True
        labels_supported = True
        captured_keys = {capture["key"] for capture in captures}
        for capture in captures:
            canvas_key = capture["key"]
            inventory_by_id = {
                item[0]: item for item in capture["inventory"]
            }
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
            for node in self._legacy_topology_nodes(capture["response"]):
                object_id = str(node.get("id"))
                key = f"{canvas_key}:{object_id}"
                proxy = capture["proxies"].get(object_id)
                inventory_item = inventory_by_id[object_id]
                class_id = str(inventory_item[1]).casefold()
                if self._legacy_topology_is_conductor(class_id, proxy):
                    vertices = inventory_item[6]
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
                                if "bus" in class_id
                                or type(proxy).__name__.casefold() == "bus"
                                else "wire"
                            ),
                            namespace=self._legacy_topology_namespace(
                                node, proxy
                            ),
                            vertices=vertices,
                            evidence=evidence(key),
                        )
                    )
                    continue
                definition = inventory_item[2]
                location = inventory_item[3]
                parameters = await self._legacy_topology_parameters(
                    proxy, node
                )
                if self._legacy_topology_is_label(definition):
                    label_name = inventory_item[5]
                    if not label_name:
                        labels_supported = False
                        unresolved.add(f"label_name_unreadable:{key}")
                        continue
                    labels.append(
                        TopologyLabel(
                            key=key,
                            canvas_key=canvas_key,
                            object_id=object_id,
                            name=label_name,
                            namespace=(
                                "data"
                                if "datalabel" in definition.casefold()
                                else "electrical"
                            ),
                            scope=canvas_key,
                            location=location,
                            evidence=evidence(key),
                        ),
                    )
                    continue
                if definition.casefold() in {"user", "usercmp"}:
                    components_supported = False
                    unresolved.add(f"component_definition_unavailable:{key}")
                orientation = inventory_item[4]
                ports = await self._legacy_topology_ports(
                    project_name,
                    canvas_key,
                    key,
                    definition,
                    location,
                    orientation,
                    proxy,
                    node,
                    evidence,
                    unresolved,
                    source_hashes,
                )
                component = TopologyComponent(
                    key=key,
                    canvas_key=canvas_key,
                    object_id=object_id,
                    definition=definition,
                    name=(
                        self._legacy_topology_name(
                            proxy, parameters, node
                        )
                        or None
                    ),
                    location=location,
                    orientation=orientation,
                    active=self._legacy_topology_active(parameters),
                    parameters=tuple(
                        sorted(
                            (str(name), value)
                            for name, value in parameters.items()
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
                links, missing = self._legacy_topology_boundary_links(
                    component,
                    child["key"],
                    child["page_ports"],
                    evidence,
                )
                boundary_links.extend(links)
                unresolved.update(missing)

        project_path = self.definition_paths.get(project_name)
        if project_path is None:
            unresolved.add("project_path_unavailable")
        for capture in captures:
            after_response = await self._legacy_topology_bulk(
                capture["canvas"]
            )
            after_proxies = await self._legacy_topology_proxies(
                capture["canvas"]
            )
            after_inventory = await self._legacy_topology_inventory(
                project_name,
                after_response,
                after_proxies,
                saved_components,
            )
            if capture["inventory"] != after_inventory:
                raise BackendError(
                    "TOPOLOGY_SNAPSHOT_UNSTABLE",
                    "Canvas changed during topology capture.",
                    self.name,
                    "inspect_canvas_topology",
                )
        hierarchy_supported = project_path is not None and not any(
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
        ports_supported = not any(
            item.startswith(
                (
                    "definition_metadata_unavailable:",
                    "port_geometry_unresolved:",
                )
            )
            for item in unresolved
        )
        return TopologySnapshot(
            source="live",
            project_name=project_name,
            project_path=str(project_path) if project_path is not None else None,
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
                ("components", components_supported),
                ("conductors", conductors_supported),
                ("dirty_state", False),
                ("hierarchy", hierarchy_supported),
                ("labels", labels_supported),
                ("ports", ports_supported),
                ("project_path", project_path is not None),
            ),
            source_fingerprint=source_fingerprint,
            grid_step=self._canvas_grid,
        )

    async def _legacy_topology_captures(
        self,
        project: Any,
        project_name: str,
        canvas_name: str,
        source_hashes: dict[Path, str],
        saved_components: Mapping[
            tuple[str, str], _SavedTopologyRecord
        ] | None,
        saved_modules: frozenset[str] | None,
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
            method = getattr(project, "user_canvas", None)
            if method is None:
                method = getattr(project, "canvas", None)
            try:
                if method is None:
                    raise AttributeError("canvas accessor unavailable")
                canvas = await self.executor.run_safe(method, request["name"])
                response = await self._legacy_topology_bulk(canvas)
            except (AttributeError, BackendError, KeyError, TypeError):
                if request["parent_key"] is None:
                    raise BackendError(
                        "TOPOLOGY_SOURCE_INVALID",
                        "Legacy canvas inventory is unavailable.",
                        self.name,
                        "inspect_canvas_topology",
                    )
                unresolved.add(
                    f"live_hierarchy_unavailable:{request['key']}"
                )
                continue
            try:
                proxies = await self._legacy_topology_proxies(canvas)
            except (AttributeError, BackendError, KeyError, TypeError):
                proxies = {}
                unresolved.add(
                    f"proxy_enrichment_unavailable:{request['key']}"
                )
            inventory = await self._legacy_topology_inventory(
                project_name,
                response,
                proxies,
                saved_components,
            )
            capture = {
                **request,
                "canvas": canvas,
                "response": response,
                "proxies": proxies,
                "inventory": inventory,
                "children": [],
            }
            inventory_by_id = {item[0]: item for item in inventory}
            captures.append(capture)
            for node in self._legacy_topology_nodes(response):
                object_id = str(node.get("id"))
                proxy = proxies.get(object_id)
                inventory_item = inventory_by_id.get(object_id)
                definition = (
                    inventory_item[2]
                    if inventory_item is not None
                    else await self._legacy_topology_definition(proxy, node)
                )
                local_name = self._legacy_topology_local_definition_name(
                    project_name, definition
                )
                if local_name is None:
                    continue
                if (
                    saved_modules is not None
                    and local_name.casefold() not in saved_modules
                ):
                    continue
                child_key = f"{request['key']}/{object_id}:{local_name}"
                if local_name.casefold() in request["ancestry"]:
                    unresolved.add(f"hierarchy_cycle:{child_key}")
                    continue
                metadata = await self._legacy_topology_definition_metadata(
                    definition, source_hashes
                )
                page_ports = (
                    tuple(
                        DefinitionPortContract(
                            name=port.name,
                            kind=self._legacy_topology_port_namespace(
                                port.kind or port.model or port.type
                            ),
                            dimension=port.dim,
                            offset=(port.x, port.y),
                        )
                        for port in metadata.ports
                        if port.page
                    )
                    if metadata is not None
                    else ()
                )
                if metadata is None:
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

    @staticmethod
    def _legacy_topology_local_definition_name(
        project_name: str, definition: str
    ) -> str | None:
        if ":" not in definition:
            return None
        scope, name = definition.split(":", 1)
        return name if scope.casefold() == project_name.casefold() else None

    @staticmethod
    def _legacy_topology_boundary_links(
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

    async def _legacy_topology_bulk(self, canvas: Any) -> ET.Element:
        method = getattr(canvas, "list_components", None)
        if method is None:
            raise BackendError(
                "TOPOLOGY_SOURCE_INVALID",
                "Legacy canvas inventory is unavailable.",
                self.name,
                "inspect_canvas_topology",
            )
        response = await self.executor.run_safe(method)
        if not isinstance(response, ET.Element):
            raise BackendError(
                "TOPOLOGY_SOURCE_INVALID",
                "Legacy canvas inventory is invalid.",
                self.name,
                "inspect_canvas_topology",
            )
        return response

    @staticmethod
    def _legacy_topology_nodes(response: ET.Element) -> list[ET.Element]:
        return sorted(
            (
                node
                for node in response.iter()
                if node.get("id") is not None
            ),
            key=lambda node: str(node.get("id")),
        )

    async def _legacy_topology_proxies(self, canvas: Any) -> dict[str, Any]:
        method = getattr(canvas, "find_all", None)
        if method is None:
            return {}
        values = list(await self.executor.run_safe(method))
        result = {}
        for value in values:
            try:
                result[str(self._component_id(value))] = value
            except (TypeError, ValueError):
                continue
        return result

    async def _legacy_topology_inventory(
        self,
        project_name: str,
        response: ET.Element,
        proxies: Mapping[str, Any],
        saved_components: Mapping[
            tuple[str, str], _SavedTopologyRecord
        ] | None = None,
    ) -> tuple[tuple, ...]:
        result = []
        for node in self._legacy_topology_nodes(response):
            object_id = str(node.get("id"))
            proxy = proxies.get(object_id)
            class_id = str(node.get("classid") or node.tag)
            saved_component = (
                saved_components.get(
                    (
                        object_id,
                        self._legacy_topology_class_family(class_id),
                    )
                )
                if saved_components is not None
                else None
            )
            saved_definition, saved_location, saved_orientation = (
                saved_component or (None, None, None)
            )
            location = await self._legacy_topology_location(
                proxy,
                node,
                saved_location,
            )
            orientation = await self._legacy_topology_orientation(
                project_name,
                object_id,
                node,
                proxy,
                saved_orientation,
            )
            definition = await self._legacy_topology_definition(
                proxy,
                node,
                saved_definition,
            )
            vertices = (
                await self._legacy_topology_vertices(node, proxy, location)
                if self._legacy_topology_is_conductor(class_id.casefold(), proxy)
                else None
            )
            label_name = None
            if self._legacy_topology_is_label(definition):
                label_name = self._legacy_topology_name(
                    proxy,
                    await self._legacy_topology_parameters(proxy, node),
                    node,
                )
            result.append(
                (
                    object_id,
                    class_id,
                    definition,
                    location,
                    orientation,
                    label_name,
                    vertices,
                )
            )
        return tuple(result)

    @staticmethod
    def _legacy_topology_is_conductor(class_id: str, proxy: Any) -> bool:
        proxy_name = type(proxy).__name__.casefold() if proxy is not None else ""
        return any(
            marker in class_id or marker in proxy_name
            for marker in ("wire", "bus")
        )

    @staticmethod
    def _legacy_topology_class_family(class_id: str) -> str:
        lowered = str(class_id).split("}")[-1].casefold()
        if lowered in {"user", "usercmp"}:
            return "user"
        if "wire" in lowered:
            return "wire"
        if "bus" in lowered:
            return "bus"
        return lowered

    @staticmethod
    def _legacy_topology_is_label(definition: str) -> bool:
        lowered = definition.casefold()
        return "nodelabel" in lowered or "datalabel" in lowered

    async def _legacy_topology_definition(
        self,
        proxy: Any,
        node: ET.Element,
        saved_definition: str | None = None,
    ) -> str:
        definition = str(
            getattr(proxy, "defn_name", None)
            or node.get("defn")
            or node.get("definition")
            or saved_definition
            or ""
        )
        method = getattr(proxy, "get_definition", None)
        if not definition and method is not None:
            value = await self.executor.run_safe(method)
            definition = str(getattr(value, "scoped_name", value) or "")
        return definition or str(node.get("classid") or node.tag)

    async def _legacy_topology_location(
        self,
        proxy: Any,
        node: ET.Element,
        saved_location: tuple[int, int] | None = None,
    ) -> tuple[int, int] | None:
        try:
            return int(node.get("x")), int(node.get("y"))
        except (TypeError, ValueError):
            pass
        if proxy is not None:
            value = getattr(proxy, "location", None)
            if value is not None:
                return int(value[0]), int(value[1])
            method = getattr(proxy, "get_location", None)
            if method is not None:
                value = await self.executor.run_safe(method)
                if value is not None:
                    return int(value[0]), int(value[1])
        return saved_location

    async def _legacy_topology_parameters(
        self, proxy: Any, node: ET.Element | None = None
    ) -> dict[str, Any]:
        result = self._legacy_topology_xml_parameters(node)
        if proxy is None:
            return result
        for name in ("get_parameters", "parameters"):
            method = getattr(proxy, name, None)
            if method is not None:
                result.update(dict(await self.executor.run_safe(method) or {}))
                break
        return result

    @staticmethod
    def _legacy_topology_xml_parameters(
        node: ET.Element | None,
    ) -> dict[str, Any]:
        result = {}
        if node is None:
            return result
        for child in node.iter():
            tag = str(child.tag).split("}")[-1].casefold()
            if tag not in {"param", "parameter"}:
                continue
            name = child.get("name") or child.get("key")
            if name:
                result[str(name)] = (
                    child.get("value")
                    if child.get("value") is not None
                    else (child.text or "").strip()
                )
        return result

    async def _legacy_topology_orientation(
        self,
        project_name: str,
        object_id: str,
        node: ET.Element,
        proxy: Any,
        saved_orientation: str | None = None,
    ) -> int | None:
        raw = node.get("orient") or node.get("orientation")
        if raw is None:
            cached = self._component_orientations.get(
                (project_name, int(object_id))
            )
            raw = cached if cached is not None else getattr(proxy, "orientation", None)
        if raw is None:
            raw = saved_orientation
        if raw is None:
            raw = await self._legacy_component_orientation(project_name, object_id)
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    def _saved_topology_components(
        self, project_name: str
    ) -> tuple[
        dict[tuple[str, str], _SavedTopologyRecord],
        frozenset[str],
    ] | None:
        path = self.definition_paths.get(project_name)
        if path is None or not path.is_file():
            return None
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            return None
        result: dict[tuple[str, str], _SavedTopologyRecord] = {}
        modules = set()
        for definition in root.iter():
            if str(definition.tag).split("}")[-1].casefold() != "definition":
                continue
            name = definition.get("name")
            if not name:
                continue
            has_page_port = any(
                str(port.tag).split("}")[-1].casefold() == "port"
                and (port.get("page") or "").strip().casefold()
                in {"1", "true", "yes", "on"}
                for port in definition.iter()
            )
            has_internal_objects = any(
                child.get("id") is not None
                for schematic in definition
                if str(schematic.tag).split("}")[-1].casefold()
                == "schematic"
                for child in schematic.iter()
                if child is not schematic
            )
            if has_page_port or has_internal_objects:
                modules.add(str(name).casefold())
        for node in root.iter():
            object_id = node.get("id")
            if object_id is None:
                continue
            class_id = node.get("classid") or str(node.tag).split("}")[-1]
            definition = node.get("defn") or node.get("definition")
            try:
                location = (int(node.get("x")), int(node.get("y")))
            except (TypeError, ValueError):
                location = None
            orientation = node.get("orient") or node.get("orientation")
            record = (
                str(definition) if definition is not None else None,
                location,
                str(orientation) if orientation is not None else None,
            )
            key = (
                str(object_id),
                self._legacy_topology_class_family(str(class_id)),
            )
            previous = result.get(key)
            if previous is None or sum(item is not None for item in record) > sum(
                item is not None for item in previous
            ):
                result[key] = record
        return result, frozenset(modules)

    async def _legacy_topology_vertices(
        self,
        node: ET.Element,
        proxy: Any,
        location: tuple[int, int] | None = None,
    ) -> tuple[tuple[int, int], ...] | None:
        raw_vertices = []
        for vertex in node.iter():
            if vertex is node or str(vertex.tag).split("}")[-1].casefold() not in {
                "vertex",
                "point",
                "node",
            }:
                continue
            try:
                raw_vertices.append((int(vertex.get("x")), int(vertex.get("y"))))
            except (TypeError, ValueError):
                return None
        if not raw_vertices and proxy is not None:
            values = getattr(proxy, "vertices", None)
            if callable(values):
                values = await self.executor.run_safe(values)
            if values is not None:
                try:
                    raw_vertices = [
                        (int(point[0]), int(point[1])) for point in values
                    ]
                except (TypeError, ValueError, IndexError):
                    return None
        if len(raw_vertices) < 2:
            return None
        origin = location
        has_xml_origin = node.get("x") is not None and node.get("y") is not None
        proxy_has_origin = proxy is not None and hasattr(proxy, "location")
        if origin is not None and (has_xml_origin or proxy_has_origin):
            if raw_vertices[0] == (0, 0):
                raw_vertices = [
                    (origin[0] + x, origin[1] + y) for x, y in raw_vertices
                ]
        return tuple(raw_vertices)

    async def _legacy_topology_ports(
        self,
        project_name: str,
        canvas_name: str,
        component_key: str,
        definition: str,
        location: tuple[int, int] | None,
        orientation: int | None,
        proxy: Any,
        node: ET.Element,
        evidence,
        unresolved: set[str],
        source_hashes: dict[Path, str],
    ) -> tuple[TopologyPort, ...]:
        xml_ports = []
        for port in node.iter():
            if (
                port is node
                or str(port.tag).split("}")[-1].casefold() != "port"
            ):
                continue
            name = port.get("name") or port.get("id")
            if not name:
                continue
            try:
                relative = (int(port.get("x")), int(port.get("y")))
            except (TypeError, ValueError):
                relative = None
            absolute = None
            if (
                relative is not None
                and location is not None
                and orientation is not None
            ):
                try:
                    absolute = absolute_port(location, relative, orientation)
                except GeometryError:
                    absolute = None
            key = f"{component_key}:{name}"
            if absolute is None:
                unresolved.add(f"port_geometry_unresolved:{key}")
            xml_ports.append(
                TopologyPort(
                    key=key,
                    component_key=component_key,
                    name=str(name),
                    absolute=absolute,
                    relative=relative,
                    kind=self._legacy_topology_port_namespace(
                        port.get("kind")
                        or port.get("model")
                        or port.get("type")
                    ),
                    dimension=self._legacy_topology_optional_int(
                        port.get("dim") or port.get("dimension")
                    ),
                    evidence=evidence(key),
                )
            )
        if xml_ports:
            return tuple(sorted(xml_ports, key=lambda item: item.key))
        method = getattr(proxy, "ports", None)
        if callable(method):
            raw_ports = await self.executor.run_safe(method)
            if raw_ports:
                return tuple(
                    sorted(
                        (
                            TopologyPort(
                                key=f"{component_key}:{name}",
                                component_key=component_key,
                                name=str(getattr(port, "name", name)),
                                absolute=(int(port.x), int(port.y)),
                                kind=self._legacy_topology_port_namespace(
                                    getattr(port, "type", None)
                                ),
                                dimension=self._legacy_topology_optional_int(
                                    getattr(port, "dim", None)
                                ),
                                evidence=evidence(f"{component_key}:{name}"),
                            )
                            for name, port in dict(raw_ports).items()
                        ),
                        key=lambda item: item.key,
                    )
                )
        metadata = await self._legacy_topology_definition_metadata(
            definition,
            source_hashes,
        )
        if metadata is None:
            unresolved.add(
                f"definition_metadata_unavailable:{component_key}"
            )
            return ()
        result = []
        for port in metadata.ports:
            key = f"{component_key}:{port.name}"
            absolute = None
            if location is not None and orientation is not None:
                try:
                    absolute = absolute_port(
                        location,
                        (port.x, port.y),
                        orientation,
                    )
                except GeometryError:
                    absolute = None
            if absolute is None:
                unresolved.add(f"port_geometry_unresolved:{key}")
            result.append(
                TopologyPort(
                    key=key,
                    component_key=component_key,
                    name=port.name,
                    absolute=absolute,
                    relative=(port.x, port.y),
                    kind=self._legacy_topology_port_namespace(
                        port.kind or port.model or port.type
                    ),
                    dimension=port.dim,
                    evidence=evidence(key),
                )
            )
        return tuple(sorted(result, key=lambda item: item.key))

    async def _legacy_topology_definition_metadata(
        self,
        definition: str,
        source_hashes: dict[Path, str],
    ) -> DefinitionMetadata | None:
        if ":" not in definition:
            return None
        scope, definition_name = definition.split(":", 1)
        path = self.definition_paths.get(scope)
        if path is None and scope.casefold() == "master":
            path = await self._discover_master_library()
            if path is not None:
                self.definition_paths[scope] = path
        if path is None or not path.is_file():
            return None
        path = path.resolve()
        source_hash = source_hashes.get(path)
        if source_hash is None:
            try:
                source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                return None
            source_hashes[path] = source_hash
        cache_key = (str(path), source_hash, definition_name.casefold())
        metadata = self._topology_definition_cache.get(cache_key)
        if metadata is None:
            try:
                metadata = await asyncio.to_thread(
                    read_definition_metadata,
                    path,
                    definition_name,
                )
            except (OSError, ET.ParseError, KeyError, TypeError, ValueError):
                return None
            self._topology_definition_cache[cache_key] = metadata
        stale = [
            key
            for key in self._topology_definition_cache
            if key[0] == str(path) and key[1] != source_hash
        ]
        for key in stale:
            self._topology_definition_cache.pop(key, None)
        return metadata

    @staticmethod
    def _legacy_topology_namespace(node: ET.Element, proxy: Any) -> str:
        raw = str(
            node.get("namespace")
            or node.get("kind")
            or getattr(proxy, "namespace", None)
            or ""
        ).casefold()
        return "data" if raw in {"data", "signal", "digital"} else "electrical"

    @staticmethod
    def _legacy_topology_port_namespace(value: Any) -> str:
        raw = str(value or "").casefold()
        return (
            "data"
            if raw in {"data", "signal", "digital", "transfer"}
            else "electrical"
        )

    @staticmethod
    def _legacy_topology_optional_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _legacy_topology_name(
        proxy: Any,
        parameters: Mapping[str, Any],
        node: ET.Element | None = None,
    ) -> str:
        for name, value in parameters.items():
            if str(name).casefold() == "name":
                return str(value)
        proxy_name = str(getattr(proxy, "name", "") or "")
        if node is not None:
            node_name = str(
                node.get("name")
                or node.get("text")
                or node.get("value")
                or ""
            )
            if node_name:
                return node_name
        return proxy_name

    @staticmethod
    def _legacy_topology_active(parameters: Mapping[str, Any]) -> bool:
        for name, value in parameters.items():
            if str(name).casefold() == "enabled":
                return bool(value)
        return True
