"""Stable, JSON-safe contracts shared by PSCAD automation backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


JsonDict = dict[str, Any]
Point = tuple[int, int]


@dataclass(frozen=True)
class BackendInfo:
    backend: str
    version: str | None
    x64: bool | None
    alive: bool
    busy: bool
    licensed: bool | None
    owns_process: bool


@dataclass(frozen=True)
class ProjectInfo:
    name: str
    type: str
    description: str


@dataclass(frozen=True)
class ComponentInfo:
    id: int
    name: str
    definition: str
    location: dict[str, int]


@dataclass(frozen=True)
class PortInfo:
    name: str
    x: int
    y: int
    dim: int | None
    type: str | None


@dataclass(frozen=True)
class RunState:
    status: str
    progress: float | None


class BackendError(RuntimeError):
    """A vendor-neutral backend failure suitable for MCP serialization."""

    def __init__(
        self,
        code: str,
        message: str,
        backend: str,
        operation: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.backend = backend
        self.operation = operation
        self.details = dict(details or {})

    def to_dict(self) -> JsonDict:
        return {
            "code": self.code,
            "message": str(self),
            "backend": self.backend,
            "operation": self.operation,
            "details": self.details,
        }


class ApplicationBackend(Protocol):
    async def attach(self) -> BackendInfo: ...
    async def heartbeat(self) -> BackendInfo: ...
    async def disconnect(self) -> None: ...
    async def quit(self) -> None: ...


class ProjectBackend(Protocol):
    async def load_projects(self, filenames: Sequence[str]) -> None: ...
    async def list_projects(self) -> list[ProjectInfo]: ...
    async def create_project(self, kind: str, filename: str, folder: str | None) -> ProjectInfo: ...
    async def save_project(self, project_name: str) -> None: ...
    async def save_project_as(self, project_name: str, filename: str, folder: str | None) -> None: ...
    async def build_project(self, project_name: str) -> None: ...
    async def build_all_projects(self) -> None: ...
    async def run_project(self, project_name: str) -> None: ...
    async def pause_project(self, project_name: str) -> None: ...
    async def stop_project(self, project_name: str) -> None: ...
    async def project_run_state(self, project_name: str) -> RunState: ...
    async def project_definitions(self, project_name: str) -> list[str]: ...
    async def get_settings(self, project_name: str) -> JsonDict: ...
    async def set_settings(self, project_name: str, settings: Mapping[str, Any]) -> None: ...
    async def project_output(self, project_name: str) -> str: ...


class SimulationSetBackend(Protocol):
    async def list_simulation_sets(self, project_name: str) -> list[str]: ...
    async def run_simulation_set(self, project_name: str, set_name: str) -> None: ...
    async def add_task_to_set(self, project_name: str, set_name: str, task_project_name: str) -> None: ...


class ComponentBackend(Protocol):
    async def find_components(
        self,
        project_name: str,
        canvas_name: str,
        definition: str | None,
        name: str | None,
    ) -> list[ComponentInfo]: ...
    async def get_component_parameters(self, project_name: str, component_id: int) -> JsonDict: ...
    async def set_component_parameters(self, project_name: str, component_id: int, parameters: Mapping[str, Any]) -> None: ...
    async def component_parameter_range(self, project_name: str, component_id: int, parameter_name: str) -> Any: ...
    async def get_component_location(self, project_name: str, component_id: int) -> Point: ...
    async def set_component_location(self, project_name: str, component_id: int, location: Point) -> None: ...
    async def rotate_component(self, project_name: str, component_id: int, direction: str) -> None: ...
    async def mirror_component(self, project_name: str, component_id: int, axis: str) -> None: ...
    async def clone_component(self, project_name: str, component_id: int, location: Point) -> ComponentInfo: ...
    async def get_component_ports(self, project_name: str, component_id: int) -> list[PortInfo]: ...
    async def set_component_enabled(self, project_name: str, component_id: int, enabled: bool) -> None: ...
    async def delete_component(self, project_name: str, component_id: int) -> None: ...
    async def delete_components(
        self, project_name: str, component_ids: Sequence[int]
    ) -> None: ...


class CanvasBackend(Protocol):
    async def add_component(
        self,
        project_name: str,
        canvas_name: str,
        library: str,
        definition: str,
        location: Point,
        orientation: int,
        parameters: Mapping[str, Any],
    ) -> ComponentInfo: ...
    async def create_wire(self, project_name: str, canvas_name: str, points: Sequence[Point]) -> JsonDict: ...
    async def create_bus(self, project_name: str, canvas_name: str, points: Sequence[Point], parameters: Mapping[str, Any]) -> JsonDict: ...
    async def create_connection(self, project_name: str, canvas_name: str, p1: Point, p2: Point, label: str | None, electrical: bool | None) -> JsonDict: ...
    async def create_annotation(self, project_name: str, canvas_name: str, location: Point, line1: str, line2: str) -> ComponentInfo: ...
    async def create_graph_frame(self, project_name: str, canvas_name: str, location: Point) -> JsonDict: ...
    async def create_control_frame(self, project_name: str, canvas_name: str, location: Point) -> JsonDict: ...
    async def list_canvas_components(self, project_name: str, canvas_name: str) -> list[JsonDict]: ...
    async def find_empty_space(self, project_name: str, canvas_name: str, width: int, height: int, near: Point) -> JsonDict: ...


class ResultBackend(Protocol):
    async def read_output_file(self, file_path: str, max_samples: int) -> JsonDict: ...


@runtime_checkable
class PscadBackend(
    ApplicationBackend,
    ProjectBackend,
    SimulationSetBackend,
    ComponentBackend,
    CanvasBackend,
    ResultBackend,
    Protocol,
):
    """Complete structural contract implemented by both vendor backends."""
