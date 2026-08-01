"""PSCAD 4.x backend implemented with the legacy Automation Library."""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from typing import Any, Mapping
import xml.etree.ElementTree as ET

from ..definition_metadata import DefinitionMetadata, read_definition_metadata
from ..pscad_adapter import PscadAdapter
from .base import (
    BackendError,
    BackendInfo,
    ComponentInfo,
    PortInfo,
    ProjectInfo,
    RunState,
)


class LegacyBackend:
    name = "legacy"
    _canvas_grid = 18

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
    ) -> None:
        self.executor = executor
        self.version = version
        self.x64 = x64
        self.legacy_wheel = legacy_wheel
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
        self.definition_paths = {
            str(name): Path(path).resolve()
            for name, path in (definition_paths or {}).items()
        }
        self._component_orientations: dict[tuple[str, int], int] = {}
        self.result_adapter = PscadAdapter(
            executor,
            pscad_module=False,
            psout_module=psout_module,
            environ={},
        )

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

        display_name = (
            f"PSCAD {self.version} ({'x64' if self.x64 else 'x86'})"
        )

        def launch() -> Any:
            return self.automation.launch_pscad(
                pscad_version=display_name,
                silence=True,
                minimize=True,
                certificate=False,
            )

        self._app = await self.executor.run_safe(launch)
        self.owns_process = True
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
        self._component_orientations.clear()

    async def quit(self) -> None:
        app = self._app
        if app is not None:
            await self.executor.run_safe(app.quit)
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

    async def list_projects(self) -> list[ProjectInfo]:
        values = await self.executor.run_safe(self._require_app().list_projects)
        return [self._project_info(value) for value in values]

    async def create_project(
        self, kind: str, filename: str, folder: str | None
    ) -> ProjectInfo:
        if kind not in {"case", "library"}:
            raise ValueError("kind must be case or library.")
        workspace = await self.executor.run_safe(self._require_app().workspace)
        name = Path(filename).stem
        path = folder or str(Path(filename).parent)
        if path in {"", "."}:
            raise ValueError("A destination folder is required for PSCAD 4.6.")
        project = await self.executor.run_safe(
            workspace.create_project,
            1 if kind == "case" else 2,
            name,
            path,
        )
        self.definition_paths[name] = Path(path).resolve() / filename
        return self._project_info(project, "Case" if kind == "case" else "Library")

    async def save_project(self, project_name: str) -> None:
        project = await self._project(project_name)
        await self.executor.run_safe(project.save)

    async def save_project_as(
        self, project_name: str, filename: str, folder: str | None
    ) -> None:
        project = await self._project(project_name)
        destination = str(Path(folder) / filename) if folder else filename
        await self.executor.run_safe(project.save_as, destination)
        self.definition_paths[Path(filename).stem] = Path(destination).resolve()

    async def build_project(self, project_name: str) -> None:
        project = await self._project(project_name)
        await self.executor.run_safe(project.build, timeout=300.0)

    async def build_all_projects(self) -> None:
        await self.executor.run_safe(
            self._require_app().build_all,
            timeout=300.0,
        )

    async def run_project(self, project_name: str) -> None:
        project = await self._project(project_name)
        await self.executor.run_safe(project.run, timeout=300.0)

    async def pause_project(self, project_name: str) -> None:
        project = await self._project(project_name)
        await self.executor.run_safe(project.pause)

    async def stop_project(self, project_name: str) -> None:
        project = await self._project(project_name)
        await self.executor.run_safe(project.stop)

    async def project_run_state(self, project_name: str) -> RunState:
        project = await self._project(project_name)
        run_status = getattr(project, "run_status", None)
        if run_status is None:
            return RunState("unknown", None)
        status, progress = await self.executor.run_safe(run_status)
        return RunState(str(status), float(progress) if progress is not None else None)

    async def project_definitions(self, project_name: str) -> list[str]:
        project = await self._project(project_name)
        method = getattr(project, "list_definitions", None)
        if method is None:
            method = project.definitions
        values = await self.executor.run_safe(method)
        return [str(value) for value in values]

    async def get_settings(self, project_name: str) -> dict[str, Any]:
        values = await self.executor.run_safe(self._require_app().settings)
        return dict(values) if hasattr(values, "items") else {"value": str(values)}

    async def set_settings(self, project_name: str, settings: Any) -> None:
        await self.executor.run_safe(self._require_app().settings, dict(settings))

    async def project_output(self, project_name: str) -> str:
        project = await self._project(project_name)
        output = getattr(project, "output", None)
        if output is not None:
            return str(await self.executor.run_safe(output))
        messages = await self.executor.run_safe(project.messages)
        return "\n".join(str(message[0] if isinstance(message, tuple) else message) for message in messages)

    async def list_simulation_sets(self, project_name: str) -> list[str]:
        workspace = await self.executor.run_safe(self._require_app().workspace)
        names = await self.executor.run_safe(workspace.list_simulation_sets)
        return [str(name) for name in names]

    async def run_simulation_set(self, project_name: str, set_name: str) -> None:
        simset = await self.executor.run_safe(
            self._require_app().simulation_set, set_name
        )
        await self.executor.run_safe(simset.run, timeout=300.0)

    async def add_task_to_set(
        self, project_name: str, set_name: str, task_project_name: str
    ) -> None:
        simset = await self.executor.run_safe(
            self._require_app().simulation_set, set_name
        )
        await self.executor.run_safe(simset.add_tasks, task_project_name)

    async def read_output_file(
        self, file_path: str, max_samples: int
    ) -> dict[str, Any]:
        return await self.result_adapter.read_psout(
            file_path,
            max_samples=max_samples,
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
        canvas_objects = await self.executor.run_safe(canvas.find_all)
        components = [
            item for item in canvas_objects if self._is_user_component(item)
        ]
        return canvas, components

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
        result = []
        for port_name in port_names:
            location_method = getattr(component, "get_port_location", None)
            location = (
                await self.executor.run_safe(location_method, port_name)
                if location_method is not None
                else None
            )
            if location is None:
                if not static_ports:
                    try:
                        definition_metadata = await self._definition_metadata(
                            component
                        )
                    except BackendError:
                        definition_metadata = DefinitionMetadata((), {})
                    static_ports = {
                        item.name: item for item in definition_metadata.ports
                    }
                static_port = static_ports.get(port_name)
                if static_port is not None:
                    location = await self._legacy_static_port_location(
                        project_name,
                        canvas,
                        component,
                        static_port.x,
                        static_port.y,
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
        _canvas, component = await self._component_proxy(project_name, component_id)
        method = getattr(component, "enable" if enabled else "disable", None)
        if method is not None:
            await self.executor.run_safe(method)
        else:
            await self.executor.run_safe(component.set_parameters, enabled=enabled)
        parameters = await self.get_component_parameters(project_name, component_id)
        if "enabled" in parameters and bool(parameters["enabled"]) is not enabled:
            raise BackendError(
                "POSTCONDITION_FAILED",
                "Component enabled state could not be verified.",
                self.name,
                "set_component_enabled",
            )

    async def delete_component(self, project_name: str, component_id: int) -> None:
        _canvas, component = await self._component_proxy(project_name, component_id)
        await self.executor.run_safe(component.delete)
        remaining = await self.find_components(project_name, "Main", None, None)
        if component_id in {item.id for item in remaining}:
            raise BackendError(
                "POSTCONDITION_FAILED",
                f"Component {component_id} still exists after deletion.",
                self.name,
                "delete_component",
            )
        self._component_orientations.pop((project_name, component_id), None)

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
        method = getattr(canvas, "closest_empty_rect", None)
        if method is not None:
            rectangle = await self.executor.run_safe(
                method, width, height, near
            )
            return {
                "x": int(rectangle.x),
                "y": int(rectangle.y),
                "width": int(rectangle.width),
                "height": int(rectangle.height),
            }
        occupied = {
            tuple(item["location"])
            for item in await self.list_canvas_components(
                project_name, canvas_name
            )
            if item["location"] is not None
        }
        for offset in range(0, 1001, 6):
            candidate = near[0] + offset, near[1] + offset
            if candidate not in occupied:
                return {
                    "x": candidate[0],
                    "y": candidate[1],
                    "width": width,
                    "height": height,
                }
        raise BackendError(
            "NO_EMPTY_SPACE",
            "No empty canvas location was found within the search bound.",
            self.name,
            "find_empty_space",
        )
