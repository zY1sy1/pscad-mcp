"""Version-independent service boundary used by MCP tools."""

from __future__ import annotations

from dataclasses import asdict
import inspect
from pathlib import Path
from typing import Any, Awaitable, Callable

from .backend.base import BackendError, BackendInfo
from .executor import robust_executor
from .path_policy import PathPolicy


BackendFactory = Callable[[], Any | Awaitable[Any]]
_ERROR_TEXT_LIMIT = 512


def _bounded_error_text(error: BaseException) -> str:
    value = f"{type(error).__name__}: {error}"
    if len(value) <= _ERROR_TEXT_LIMIT:
        return value
    return value[: _ERROR_TEXT_LIMIT - 3] + "..."


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

    @property
    def backend(self) -> Any:
        if self._backend is None:
            raise RuntimeError("PSCAD is not connected. Call get_local_pscad first.")
        return self._backend

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
            return (
                "Successfully launched a new PSCAD automation instance using "
                f"legacy backend for PSCAD {info.version} ({architecture}); legacy "
                "automation does not attach to an already-open GUI."
            )
        return (
            f"Successfully attached using {info.backend} backend to "
            f"PSCAD {info.version} ({architecture})."
        )

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
            }
        info: BackendInfo = await self._backend.heartbeat()
        payload = asdict(info)
        payload["connected"] = bool(info.alive)
        payload["selected_version"] = info.version
        return payload

    async def disconnect(self) -> None:
        if self._backend is not None:
            await self._backend.disconnect()
        self._backend = None

    async def repair_connection(self) -> str:
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
                self.path_policy.resolve(
                    filename,
                    suffixes={".pscx", ".pslx", ".pswx"},
                    must_exist=True,
                )
            )
            for filename in filenames
        ]
        await self.backend.load_projects(resolved)
        return f"Loaded: {', '.join(resolved)}"

    async def list_projects(self) -> list[dict[str, Any]]:
        return [asdict(item) for item in await self.backend.list_projects()]

    async def run_project(self, project_name: str) -> str:
        info = await self.backend.heartbeat()
        if info.licensed is False:
            return "Error: PSCAD is not licensed."
        await self.backend.run_project(project_name)
        return f"Simulation started for '{project_name}'."

    async def get_run_status(self, project_name: str) -> dict[str, Any]:
        return asdict(await self.backend.project_run_state(project_name))

    async def pause_simulation(self, project_name: str) -> str:
        await self.backend.pause_project(project_name)
        return f"Simulation paused for '{project_name}'."

    async def stop_simulation(self, project_name: str) -> str:
        await self.backend.stop_project(project_name)
        return f"Simulation stopped for '{project_name}'."

    async def get_project_settings(self, project_name: str) -> dict[str, Any]:
        return await self.backend.get_settings(project_name)

    async def set_project_settings(
        self, project_name: str, settings: dict[str, Any]
    ) -> str:
        await self.backend.set_settings(project_name, settings)
        return f"Settings updated for project '{project_name}'."

    def _resolve_destination(
        self,
        filename: str,
        folder: str | None,
        suffixes: set[str],
    ) -> Path:
        candidate = str(Path(folder) / filename) if folder else filename
        return self.path_policy.resolve(candidate, suffixes=suffixes)

    async def create_project(
        self,
        kind: str,
        filename: str,
        folder: str | None,
        *,
        confirm: bool = False,
    ) -> dict[str, str]:
        suffixes = {".pscx"} if kind == "case" else {".pslx"}
        destination = self._resolve_destination(filename, folder, suffixes)
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
        destination = self._resolve_destination(filename, folder, suffixes)
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

    async def run_simulation_set(
        self, project_name: str, sim_set_name: str
    ) -> str:
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
        await self.backend.add_task_to_set(
            project_name,
            sim_set_name,
            task_project_name,
        )
        return f"Task '{task_project_name}' added to set '{sim_set_name}'."

    async def get_project_output(self, project_name: str) -> str:
        return await self.backend.project_output(project_name)

    async def read_output_file(
        self, file_path: str, max_samples: int = 10_000
    ) -> dict[str, Any]:
        if not 1 <= max_samples <= 1_000_000:
            raise ValueError("max_samples must be between 1 and 1000000.")
        resolved = self.path_policy.resolve(
            file_path,
            suffixes={".psout", ".out"},
            must_exist=True,
        )
        return await self.backend.read_output_file(str(resolved), max_samples)

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
            return {"error": error.to_dict()}
        return {
            "error": {
                "code": "INTERNAL_ERROR",
                "message": str(error),
                "backend": "service",
                "operation": operation,
                "details": {},
            }
        }
