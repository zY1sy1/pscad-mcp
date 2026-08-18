"""Recording public-boundary fake used by the LCC executor tests."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


class RecordingPscadService:
    def __init__(self, *, fail_on: str | None = None, output: Any = None, run_statuses: list[str] | None = None) -> None:
        self.fail_on = fail_on
        self.output = {"verdict": "PASS"} if output is None else output
        self.run_statuses = list(run_statuses or ["running", "completed"])
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.settings: dict[str, dict[str, Any]] = {}
        self.components: dict[int, dict[str, Any]] = {}
        self.next_component_id = 1
        self.project_file: Path | None = None

    def _call(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))
        if self.fail_on == name:
            raise RuntimeError(f"injected failure at {name}")

    def _write_project(self, path: Path) -> None:
        root = ET.Element("project", {"name": path.stem, "version": "4.6.2"})
        definition = ET.SubElement(root, "definition", {"name": "Main"})
        for component in sorted(self.components.values(), key=lambda value: value["id"]):
            element = ET.SubElement(
                definition,
                "component",
                {
                    "id": str(component["id"]),
                    "logical_id": component["logical_id"],
                    "definition": component["definition"],
                    "x": str(component["x"]),
                    "y": str(component["y"]),
                    "orientation": str(component["orientation"]),
                },
            )
            parameters = ET.SubElement(element, "parameters")
            for name, value in sorted(component["parameters"].items()):
                ET.SubElement(parameters, "param", {"name": str(name), "value": str(value)})
        path.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)

    async def create_project(self, kind: str, filename: str, folder: str, *, confirm: bool = False) -> dict[str, str]:
        self._call("create_project", kind, filename, folder, confirm=confirm)
        path = Path(folder) / filename
        self.project_file = path
        self._write_project(path)
        return {"name": path.stem, "filename": str(path)}

    async def load_projects(self, filenames: list[str]) -> str:
        self._call("load_projects", filenames)
        return "loaded"

    async def set_project_settings(self, project_name: str, settings: dict[str, Any], *args: Any, **kwargs: Any) -> str:
        self._call("set_project_settings", project_name, settings, *args, **kwargs)
        self.settings[project_name] = dict(settings)
        return "set"

    async def get_project_settings(self, project_name: str) -> dict[str, Any]:
        self._call("get_project_settings", project_name)
        return dict(self.settings.get(project_name, {}))

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
        self._call("add_canvas_component", project_name, library, name, x, y, orientation, parameters, canvas_name=canvas_name)
        component_id = self.next_component_id
        self.next_component_id += 1
        logical_id = str((parameters or {}).get("LogicalId", name))
        self.components[component_id] = {
            "id": component_id,
            "logical_id": logical_id,
            "definition": f"{library}:{name}",
            "x": x,
            "y": y,
            "orientation": orientation,
            "parameters": dict(parameters or {}),
        }
        return {"id": component_id, "name": logical_id, "definition": f"{library}:{name}", "location": {"x": x, "y": y}}

    async def get_component_location(self, project_name: str, component_id: int) -> dict[str, int]:
        self._call("get_component_location", project_name, component_id)
        component = self.components[component_id]
        return {"id": component_id, "x": component["x"], "y": component["y"]}

    async def get_component_parameters(self, project_name: str, component_id: int) -> dict[str, Any]:
        self._call("get_component_parameters", project_name, component_id)
        return dict(self.components[component_id]["parameters"])

    async def get_component_ports(self, project_name: str, component_id: int) -> list[dict[str, Any]]:
        self._call("get_component_ports", project_name, component_id)
        return []

    async def create_wire(self, project_name: str, vertices: list[list[int]], *, canvas_name: str = "Main") -> dict[str, Any]:
        self._call("create_wire", project_name, vertices, canvas_name=canvas_name)
        return {"vertices": vertices}

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
        self._call("create_connection", project_name, p1, p2, label, electrical, canvas_name=canvas_name)
        return {"p1": p1, "p2": p2, "label": label}

    async def save_project(self, project_name: str, *, confirm: bool = False) -> str:
        self._call("save_project", project_name, confirm=confirm)
        if self.project_file is not None:
            self._write_project(self.project_file)
        return "saved"

    async def build_project(self, project_name: str) -> str:
        self._call("build_project", project_name)
        return "built"

    async def run_project(self, project_name: str) -> str:
        self._call("run_project", project_name)
        return "started"

    async def get_run_status(self, project_name: str) -> dict[str, str]:
        self._call("get_run_status", project_name)
        value = self.run_statuses.pop(0) if self.run_statuses else "completed"
        return {"status": value}

    async def get_project_output(self, project_name: str, structured: bool = False) -> Any:
        self._call("get_project_output", project_name, structured=structured)
        return self.output

    async def save_project_as(self, project_name: str, filename: str, folder: str, *, confirm: bool = False) -> str:
        self._call("save_project_as", project_name, filename, folder, confirm=confirm)
        destination = Path(folder) / filename
        if self.project_file is not None:
            self._write_project(self.project_file)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(self.project_file.read_bytes())
        return "saved as"
