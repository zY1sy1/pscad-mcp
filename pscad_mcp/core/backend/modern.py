"""PSCAD 5.x backend implemented with the current MHI API."""

from __future__ import annotations

from typing import Any, Sequence

from ..pscad_adapter import PscadAdapter
from ..pscad_config import _version_key
from .base import (
    BackendError,
    BackendInfo,
    ComponentInfo,
    PortInfo,
    ProjectInfo,
    RunState,
)


class ModernBackend:
    name = "modern"

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

    async def run_project(self, project_name: str) -> None:
        await self.adapter.call(
            await self._project(project_name), "run", timeout=300.0
        )

    async def pause_project(self, project_name: str) -> None:
        await self.adapter.call(await self._project(project_name), "pause")

    async def stop_project(self, project_name: str) -> None:
        await self.adapter.call(await self._project(project_name), "stop")

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

    async def get_settings(self, project_name: str) -> dict[str, Any]:
        values = await self.adapter.call(self._app, "settings")
        return dict(values) if hasattr(values, "items") else {"value": str(values)}

    async def set_settings(self, project_name: str, settings: Any) -> None:
        await self.adapter.call(self._app, "settings", **dict(settings))

    async def project_output(self, project_name: str) -> str:
        return str(
            await self.adapter.call(await self._project(project_name), "output")
        )

    async def list_simulation_sets(self, project_name: str) -> list[str]:
        values = await self.adapter.call(self._app, "simulation_sets")
        return [str(value) for value in values]

    async def run_simulation_set(self, project_name: str, set_name: str) -> None:
        simset = await self.adapter.call(self._app, "simulation_set", set_name)
        await self.adapter.call(simset, "run", timeout=300.0)

    async def add_task_to_set(
        self, project_name: str, set_name: str, task_project_name: str
    ) -> None:
        simset = await self.adapter.call(self._app, "simulation_set", set_name)
        await self.adapter.call(simset, "add_tasks", task_project_name)

    async def read_output_file(
        self, file_path: str, max_samples: int
    ) -> dict[str, Any]:
        return await self.adapter.read_psout(
            file_path,
            max_samples=max_samples,
        )

    async def _component(self, project_name: str, component_id: int) -> Any:
        return await self.adapter.call(
            await self._project(project_name), "component", component_id
        )

    async def _canvas(self, project_name: str, canvas_name: str) -> Any:
        return await self.adapter.call(
            await self._project(project_name), "canvas", canvas_name
        )

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
