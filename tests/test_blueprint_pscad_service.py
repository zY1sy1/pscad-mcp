from __future__ import annotations

from pathlib import Path

import pytest

from pscad_mcp.builders.blueprint.inventory import read_live_inventory
from pscad_mcp.core.backend.base import BackendError, BackendInfo, PortInfo
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import PscadService
from tests.backend_fakes import ImmediateExecutor


class BlueprintBackend:
    name = "modern"
    version = "4.6.2"

    def __init__(self) -> None:
        self.loaded: list[list[str]] = []
        self.unloaded: list[str] = []

    async def heartbeat(self) -> BackendInfo:
        return BackendInfo("modern", "4.6.2", True, True, False, True, False)

    async def project_definitions(self, project_name: str) -> list[str]:
        return ["master:breaker"]

    async def list_canvas_components(self, project_name: str, canvas_name: str):
        return [
            {
                "id": 7,
                "name": "BRK",
                "definition": "master:breaker",
                "location": [10, 20],
                "orientation": 90,
            }
        ]

    async def get_component_parameters(self, project_name: str, component_id: int):
        return {"Name": "BRK"}

    async def get_component_ports(self, project_name: str, component_id: int):
        return [PortInfo("A", 9, 20, 1, "electrical")]

    async def get_component_location(self, project_name: str, component_id: int):
        return (10, 20)

    async def load_projects(self, filenames):
        self.loaded.append(list(filenames))

    async def unload_project(self, project_name):
        self.unloaded.append(project_name)

    async def list_projects(self):
        return [{"name": "BuiltCase"}]

    async def get_output_channels(self, project_name: str):
        return [{"path": "Main/BRK_STATE", "units": "state", "call_id": 1}]


def _service(tmp_path: Path, backend: BlueprintBackend) -> PscadService:
    service = PscadService(
        lambda: backend,
        executor=ImmediateExecutor(),
        path_policy=PathPolicy(str(tmp_path)),
    )
    service._backend = backend
    return service


@pytest.mark.asyncio
async def test_real_pscad_service_exposes_complete_blueprint_readback_contract(tmp_path):
    backend = BlueprintBackend()
    service = _service(tmp_path, backend)

    inventory = await read_live_inventory(service, "Source", "breaker")
    snapshot = await service.get_component_snapshot("Source", 7)

    assert inventory.pscad_version == "4.6.2"
    assert inventory.definitions["master:breaker"]["parameters"]["Name"]["resolved"] is True
    assert inventory.definitions["master:breaker"]["ports"]["A"]["dimension"] == 1
    assert snapshot["orientation"] == 90
    assert snapshot["parameters"] == {"Name": "BRK"}
    assert snapshot["ports"]["A"]["type"] == "electrical"


@pytest.mark.asyncio
async def test_real_pscad_service_reloads_and_verifies_declared_output_channels(tmp_path):
    backend = BlueprintBackend()
    service = _service(tmp_path, backend)
    project = tmp_path / "BuiltCase.pscx"
    project.write_text("<project/>", encoding="utf-8")

    await service.reload_project("BuiltCase", str(project))
    channel = await service.create_output_channel(
        "BuiltCase", "Main/BRK_STATE", "state", call_id=1
    )

    assert backend.unloaded == ["BuiltCase"]
    assert backend.loaded == [[str(project.resolve())]]
    assert channel == {"path": "Main/BRK_STATE", "units": "state", "call_id": 1}

    with pytest.raises(BackendError) as raised:
        await service.create_output_channel("BuiltCase", "Main/MISSING", "kV")
    assert raised.value.code == "BLUEPRINT_OUTPUT_DECLARATION_UNAVAILABLE"
