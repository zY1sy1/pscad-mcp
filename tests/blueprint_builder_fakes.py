from __future__ import annotations

from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


class RecordingBlueprintPscadService:
    def __init__(self, *, location_drift: bool = False, run_statuses=None, fail_on: str | None = None):
        self.location_drift = location_drift
        self.run_statuses = list(run_statuses or ["running", "completed"])
        self.fail_on = fail_on
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.project_file: Path | None = None
        self.project_name = "BuiltCase"
        self.settings: dict[str, Any] = {}
        self.output_channels: list[dict[str, Any]] = []
        self.wires: list[dict[str, Any]] = []
        self.connections: list[dict[str, Any]] = []
        self.components = {
            17: {
                "id": 17,
                "logical_id": "source_breaker",
                "name": "BRK_SOURCE",
                "definition": "master:breaker",
                "canvas": "Main",
                "x": 10,
                "y": 10,
                "orientation": 0,
                "parameters": {"Name": "BRK_SOURCE"},
                "ports": {
                    "A": {"name": "A", "x": 9, "y": 10, "kind": "electrical", "dimension": 1},
                    "B": {"name": "B", "x": 11, "y": 10, "kind": "electrical", "dimension": 1},
                },
            }
        }
        self.next_id = 18

    def _call(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))
        if self.fail_on == name:
            raise RuntimeError(f"injected failure at {name}")

    def _write_project(self) -> None:
        assert self.project_file is not None
        root = ET.Element("project", {"name": self.project_name, "version": "4.6.2"})
        canvases: dict[str, ET.Element] = {}
        for component in sorted(self.components.values(), key=lambda value: value["id"]):
            canvas = component["canvas"]
            definition = canvases.setdefault(canvas, ET.SubElement(root, "definition", {"name": canvas}))
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
                ET.SubElement(parameters, "param", {"name": name, "value": str(value)})
            for port in component["ports"].values():
                ET.SubElement(element, "port", {key: str(value) for key, value in port.items()})
        self.project_file.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(root).write(self.project_file, encoding="utf-8", xml_declaration=True)

    async def load_projects(self, filenames: list[str]) -> str:
        self._call("load_projects", filenames)
        self.project_file = Path(filenames[0])
        self.project_name = self.project_file.stem
        return "loaded"

    async def reload_project(self, project_name: str, filename: str) -> str:
        self._call("reload_project", project_name, filename)
        self.project_file = Path(filename)
        return "reloaded"

    async def clone_component(self, project_name: str, component_id: int, x: int, y: int) -> dict[str, Any]:
        self._call("clone_component", project_name, component_id, x, y)
        source = self.components[component_id]
        component = {**source, "id": self.next_id, "logical_id": "breaker_copy", "name": "BRK_COPY", "x": x, "y": y, "parameters": dict(source["parameters"]), "ports": {name: dict(value) for name, value in source["ports"].items()}}
        self.components[self.next_id] = component
        self.next_id += 1
        return {"id": component["id"], "name": component["name"], "definition": component["definition"], "location": {"x": x, "y": y}}

    async def create_canvas_component(self, project_name: str, definition: str, x: int, y: int, orientation: int, parameters: dict[str, Any] | None, *, canvas_name="Main") -> dict[str, Any]:
        self._call("create_canvas_component", project_name, definition, x, y, orientation, parameters, canvas_name=canvas_name)
        logical_id = str((parameters or {}).get("LogicalId", "aux"))
        component = {"id": self.next_id, "logical_id": logical_id, "name": logical_id, "definition": definition, "canvas": canvas_name, "x": x, "y": y, "orientation": orientation, "parameters": dict(parameters or {}), "ports": {"A": {"name": "A", "x": x - 1, "y": y, "kind": "electrical", "dimension": 1}, "B": {"name": "B", "x": x + 1, "y": y, "kind": "electrical", "dimension": 1}}}
        self.components[self.next_id] = component
        self.next_id += 1
        return {"id": component["id"], "name": logical_id, "definition": definition, "location": {"x": x, "y": y}}

    async def get_component_location(self, project_name: str, component_id: int) -> dict[str, int]:
        self._call("get_component_location", project_name, component_id)
        component = self.components[component_id]
        return {"id": component_id, "x": component["x"] + (1 if self.location_drift else 0), "y": component["y"]}

    async def set_component_location(self, project_name: str, component_id: int, x: int, y: int) -> str:
        self._call("set_component_location", project_name, component_id, x, y)
        self.components[component_id].update(x=x, y=y)
        return "moved"

    async def rotate_component(self, project_name: str, component_id: int, direction: str) -> str:
        self._call("rotate_component", project_name, component_id, direction)
        amount = {"right": 90, "left": -90, "180": 180}[direction]
        self.components[component_id]["orientation"] = (self.components[component_id]["orientation"] + amount) % 360
        return "rotated"

    async def get_component_snapshot(self, project_name: str, component_id: int) -> dict[str, Any]:
        self._call("get_component_snapshot", project_name, component_id)
        return dict(self.components[component_id])

    async def set_component_parameters(self, project_name: str, component_id: int, parameters: dict[str, Any], *, confirm=False) -> str:
        self._call("set_component_parameters", project_name, component_id, parameters, confirm=confirm)
        self.components[component_id]["parameters"].update(parameters)
        return "set"

    async def get_component_parameters(self, project_name: str, component_id: int) -> dict[str, Any]:
        self._call("get_component_parameters", project_name, component_id)
        return dict(self.components[component_id]["parameters"])

    async def get_component_ports(self, project_name: str, component_id: int) -> dict[str, Any]:
        self._call("get_component_ports", project_name, component_id)
        return {name: dict(value) for name, value in self.components[component_id]["ports"].items()}

    async def create_wire(self, project_name: str, vertices: list[list[int]], *, canvas_name="Main") -> dict[str, Any]:
        self._call("create_wire", project_name, vertices, canvas_name=canvas_name)
        value = {"vertices": vertices, "canvas": canvas_name}
        self.wires.append(value)
        return value

    async def connect_ports(self, project_name: str, first_id: int, first_port: str, second_id: int, second_port: str, *, canvas_name="Main") -> dict[str, Any]:
        self._call("connect_ports", project_name, first_id, first_port, second_id, second_port, canvas_name=canvas_name)
        value = {"from": {"component_id": first_id, "port": first_port}, "to": {"component_id": second_id, "port": second_port}, "canvas": canvas_name}
        self.connections.append(value)
        return value

    async def set_project_settings(self, project_name: str, settings: dict[str, Any], *, confirm=False) -> str:
        self._call("set_project_settings", project_name, settings, confirm=confirm)
        self.settings.update(settings)
        return "set"

    async def get_project_settings(self, project_name: str) -> dict[str, Any]:
        self._call("get_project_settings", project_name)
        return dict(self.settings)

    async def create_output_channel(self, project_name: str, path: str, units: str, *, call_id=None) -> dict[str, Any]:
        self._call("create_output_channel", project_name, path, units, call_id=call_id)
        value = {"path": path, "units": units, "call_id": call_id}
        self.output_channels.append(value)
        return value

    async def get_output_channels(self, project_name: str) -> list[dict[str, Any]]:
        self._call("get_output_channels", project_name)
        return list(self.output_channels)

    async def save_project(self, project_name: str, *, confirm=False) -> str:
        self._call("save_project", project_name, confirm=confirm)
        self._write_project()
        return "saved"

    async def build_project(self, project_name: str) -> str:
        self._call("build_project", project_name)
        return "built"

    async def run_project(self, project_name: str) -> str:
        self._call("run_project", project_name)
        assert self.project_file is not None
        base = self.project_file.with_suffix("")
        base.with_suffix(".inf").write_text('PGB(1) Output Desc="BRK_STATE" Group="Main" Max=1 Min=0 Units="state"\n', encoding="utf-8")
        Path(f"{base}_01.out").write_text("0.0 0\n0.1 1\n", encoding="utf-8")
        return "started"

    async def get_run_status(self, project_name: str) -> dict[str, str]:
        self._call("get_run_status", project_name)
        status = self.run_statuses.pop(0) if self.run_statuses else "completed"
        return {"status": status}

    async def stop_simulation(self, project_name: str) -> str:
        self._call("stop_simulation", project_name)
        return "stopped"

    async def get_project_output(self, project_name: str, structured=False) -> list[dict[str, str]]:
        self._call("get_project_output", project_name, structured=structured)
        return []

