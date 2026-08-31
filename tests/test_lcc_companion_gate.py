from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.assets import load_packaged_asset_set

FIXTURE_PORTS = {
    "cigre_lcc_v1:LCC12PulseBridge": {
        "ACY_A",
        "ACY_B",
        "ACY_C",
        "ACD_A",
        "ACD_B",
        "ACD_C",
        "DC_POS",
        "DC_NEG",
        "AO_Y",
        "AO_D",
        "ENABLE",
        "AM_Y",
        "AM_D",
        "GM_Y",
        "GM_D",
    },
    "cigre_lcc_v1:RectifierControl": {
        "VDC",
        "IDC",
        "IORDER",
        "ENABLE",
        "AO_Y",
        "AO_D",
        "ALPHA",
    },
    "cigre_lcc_v1:InverterControl": {
        "VDC",
        "IDC",
        "GM_Y",
        "GM_D",
        "GAMMA_ORDER",
        "ENABLE",
        "AO_Y",
        "AO_D",
        "GAMMA",
    },
    "cigre_lcc_v1:Initialization": {
        "IORDER",
        "GAMMA_ORDER",
        "ENABLE_RECT",
        "ENABLE_INV",
    },
    "cigre_lcc_v1:SignalInterface": {"VDC_RECT", "VDC_INV", "IDC"},
}


def _subject():
    return importlib.import_module(
        "pscad_mcp.hvdc.builders.lcc.companion_gate"
    ).run_companion_component_gate


class CompanionGateFakeService:
    def __init__(
        self,
        *,
        fail_on: str | None = None,
        port_drift: bool = False,
        mutate_master_on_build: Path | None = None,
        reload_unavailable: bool = False,
    ) -> None:
        self.fail_on = fail_on
        self.port_drift = port_drift
        self.mutate_master_on_build = mutate_master_on_build
        self.reload_unavailable = reload_unavailable
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.failure_index = -1
        self.projects: dict[str, dict[str, Any]] = {}
        self.next_id = 1

    def _call(self, name: str, *arguments: Any) -> None:
        self.calls.append((name, arguments))
        if self.fail_on == name:
            self.failure_index = len(self.calls) - 1
            raise RuntimeError(f"injected failure at {name}")

    async def load_projects(self, filenames: list[str]) -> str:
        self._call("load_projects", filenames)
        return "loaded"

    async def create_project(
        self,
        kind: str,
        filename: str,
        folder: str,
        *,
        confirm: bool = False,
    ) -> dict[str, str]:
        self._call("create_project", kind, filename, folder, confirm)
        path = Path(folder) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<project />", encoding="utf-8")
        name = path.stem
        self.projects[name] = {"path": path, "components": {}}
        return {"name": name, "filename": str(path)}

    async def add_canvas_component(
        self,
        project_name: str,
        library: str,
        name: str,
        x: int,
        y: int,
        orientation: int,
        parameters: dict[str, Any],
        *,
        canvas_name: str = "Main",
    ) -> dict[str, Any]:
        self._call(
            "add_canvas_component",
            project_name,
            library,
            name,
            x,
            y,
            orientation,
            parameters,
            canvas_name,
        )
        component_id = self.next_id
        self.next_id += 1
        definition = f"{library}:{name}"
        electrical = {
            "ACY_A",
            "ACY_B",
            "ACY_C",
            "ACD_A",
            "ACD_B",
            "ACD_C",
            "DC_POS",
            "DC_NEG",
        }
        ports = {
            port: {
                "name": port,
                "kind": "electrical" if port in electrical else "data",
                "dimension": 1,
            }
            for port in FIXTURE_PORTS[definition]
        }
        self.projects[project_name]["components"][component_id] = {
            "definition": definition,
            "parameters": dict(parameters),
            "ports": ports,
        }
        return {
            "id": component_id,
            "definition": definition,
            "orientation": orientation,
        }

    async def get_component_snapshot(
        self,
        project_name: str,
        component_id: int,
    ) -> dict[str, Any]:
        self._call("get_component_snapshot", project_name, component_id)
        component = self.projects[project_name]["components"][component_id]
        return {
            "id": component_id,
            "definition": component["definition"],
        }

    async def get_component_parameters(
        self,
        project_name: str,
        component_id: int,
    ) -> dict[str, Any]:
        self._call("get_component_parameters", project_name, component_id)
        return dict(
            self.projects[project_name]["components"][component_id][
                "parameters"
            ]
        )

    async def get_component_ports(
        self,
        project_name: str,
        component_id: int,
    ) -> dict[str, Any]:
        self._call("get_component_ports", project_name, component_id)
        ports = dict(
            self.projects[project_name]["components"][component_id]["ports"]
        )
        if self.port_drift:
            ports.pop(next(iter(ports)))
        return ports

    async def save_project(
        self,
        project_name: str,
        *,
        confirm: bool = False,
    ) -> str:
        self._call("save_project", project_name, confirm)
        project = self.projects[project_name]
        project["path"].write_text(
            json.dumps(project["components"], sort_keys=True),
            encoding="utf-8",
        )
        return "saved"

    async def reload_project(self, project_name: str, filename: str) -> str:
        self._call("reload_project", project_name, filename)
        if self.reload_unavailable:
            raise BackendError(
                "BLUEPRINT_RELOAD_UNAVAILABLE",
                "The legacy backend cannot unload this project.",
                "legacy",
                "unload_project",
            )
        return "reloaded"

    async def save_project_as(
        self,
        project_name: str,
        filename: str,
        folder: str,
        *,
        confirm: bool = False,
    ) -> str:
        self._call("save_project_as", project_name, filename, folder, confirm)
        source = self.projects[project_name]
        path = Path(folder) / filename
        path.write_text(
            json.dumps(source["components"], sort_keys=True),
            encoding="utf-8",
        )
        reloaded_name = path.stem
        reloaded_components = {}
        for component in source["components"].values():
            component_id = self.next_id
            self.next_id += 1
            reloaded_components[component_id] = copy.deepcopy(component)
        self.projects[reloaded_name] = {
            "path": path,
            "components": reloaded_components,
        }
        return "saved as"

    async def find_components(
        self,
        project_name: str,
        definition: str | None = None,
        name: str | None = None,
        canvas_name: str = "Main",
    ) -> list[dict[str, Any]]:
        self._call(
            "find_components",
            project_name,
            definition,
            name,
            canvas_name,
        )
        return [
            {"id": component_id, "definition": component["definition"]}
            for component_id, component in self.projects[project_name][
                "components"
            ].items()
            if definition is None or component["definition"] == definition
        ]

    async def build_project(self, project_name: str) -> str:
        self._call("build_project", project_name)
        if self.mutate_master_on_build is not None:
            self.mutate_master_on_build.write_bytes(b"changed-master")
        return "built"


def _inputs(tmp_path: Path):
    assets = load_packaged_asset_set()
    master_path = tmp_path / "master.pslx"
    master_path.write_bytes(b"master")
    registry_path = (
        Path(__file__).parents[1]
        / "pscad_mcp"
        / "assets"
        / "lcc"
        / "cigre_lcc_monopole_v1"
        / "master-bindings-pscad-4.6.2.json"
    )
    return (
        assets,
        master_path,
        registry_path,
        hashlib.sha256(master_path.read_bytes()).hexdigest(),
        assets.master_bindings.sha256,
    )


def test_component_gate_loads_reads_reloads_and_compiles_every_fixture(tmp_path):
    assets, master, registry, master_hash, registry_hash = _inputs(tmp_path)
    service = CompanionGateFakeService()

    result = asyncio.run(
        _subject()(
            service,
            assets,
            tmp_path / "fixtures",
            master_path=master,
            registry_path=registry,
            expected_master_sha256=master_hash,
            expected_registry_sha256=registry_hash,
        )
    )

    assert result["status"] == "PASS"
    assert [item["fixture"] for item in result["fixtures"]] == [
        "bridge_rectifier",
        "bridge_inverter",
        "rectifier_control",
        "inverter_control",
        "initialization",
        "signal_interface",
    ]
    assert all(item["compile"]["success"] for item in result["fixtures"])
    assert all(
        item["before_reload"] == item["after_reload"]
        for item in result["fixtures"]
    )


@pytest.mark.parametrize(
    "failure",
    [
        "load_projects",
        "create_project",
        "add_canvas_component",
        "get_component_ports",
        "reload_project",
        "build_project",
    ],
)
def test_component_gate_preserves_fail_evidence_and_stops(failure, tmp_path):
    assets, master, registry, master_hash, registry_hash = _inputs(tmp_path)
    service = CompanionGateFakeService(fail_on=failure)

    result = asyncio.run(
        _subject()(
            service,
            assets,
            tmp_path / "fixtures",
            master_path=master,
            registry_path=registry,
            expected_master_sha256=master_hash,
            expected_registry_sha256=registry_hash,
        )
    )

    assert result["status"] == "FAIL"
    assert result["failure"]["operation"] == failure
    assert not any(
        call[0] == "build_project"
        for call in service.calls[service.failure_index + 1 :]
    )


def test_component_gate_rejects_port_readback_drift(tmp_path):
    assets, master, registry, master_hash, registry_hash = _inputs(tmp_path)

    result = asyncio.run(
        _subject()(
            CompanionGateFakeService(port_drift=True),
            assets,
            tmp_path / "fixtures",
            master_path=master,
            registry_path=registry,
            expected_master_sha256=master_hash,
            expected_registry_sha256=registry_hash,
        )
    )

    assert result["status"] == "FAIL"
    assert result["failure"]["operation"] == "validate_readback"
    assert result["failure"]["code"] == "LCC_COMPANION_READBACK_FAILED"


def test_component_gate_rejects_master_change_before_compile(tmp_path):
    assets, master, registry, master_hash, registry_hash = _inputs(tmp_path)

    result = asyncio.run(
        _subject()(
            CompanionGateFakeService(mutate_master_on_build=master),
            assets,
            tmp_path / "fixtures",
            master_path=master,
            registry_path=registry,
            expected_master_sha256=master_hash,
            expected_registry_sha256=registry_hash,
        )
    )

    assert result["status"] == "FAIL"
    assert result["failure"]["operation"] == "verify_sources"
    assert result["failure"]["code"] == "MASTER_SOURCE_CHANGED"


def test_component_gate_uses_save_as_when_legacy_unload_is_unavailable(tmp_path):
    assets, master, registry, master_hash, registry_hash = _inputs(tmp_path)
    service = CompanionGateFakeService(reload_unavailable=True)

    result = asyncio.run(
        _subject()(
            service,
            assets,
            tmp_path / "fixtures",
            master_path=master,
            registry_path=registry,
            expected_master_sha256=master_hash,
            expected_registry_sha256=registry_hash,
        )
    )

    assert result["status"] == "PASS"
    call_names = [call[0] for call in service.calls]
    assert call_names.count("reload_project") == 6
    assert call_names.count("save_project_as") == 6
    assert call_names.count("find_components") == 6
    assert all(
        item["project"]["name"].endswith("_reloaded")
        for item in result["fixtures"]
    )
