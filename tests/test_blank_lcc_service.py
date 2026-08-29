from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.master_bindings import audit_master_bindings
from pscad_mcp.hvdc.builders.lcc.assets import load_packaged_asset_set
from pscad_mcp.hvdc.builders.lcc.blank import BlankLccRequest
from pscad_mcp.hvdc.builders.lcc.blank_service import BlankLccBuilderService
from tests.test_lcc_native_template import _template
from tests.test_master_binding_registry import _master_fixture_xml


def _master_registry(tmp_path: Path, *, include_pgb: bool = True):
    definitions = "<Definition name='tfault'><svg /></Definition>"
    if include_pgb:
        definitions += "<Definition name='pgb'><svg /></Definition>"
    master = tmp_path / "master.pslx"
    master.write_text(
        _master_fixture_xml().replace(
            "</pslx>",
            definitions + "</pslx>",
        ),
        encoding="utf-8",
    )
    assets = load_packaged_asset_set()
    assert assets.master_bindings is not None
    return audit_master_bindings(master, assets.master_bindings)


class _NativeLccServiceFake:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.project: Path | None = None
        self.settings: dict[str, object] = {}
        self.source_to_mutate: Path | None = None

    async def load_projects(self, paths: list[str]) -> None:
        self.calls.append("load_projects")
        self.project = Path(paths[-1])
        if self.source_to_mutate is not None:
            self.source_to_mutate.write_text("changed", encoding="ascii")
            self.source_to_mutate = None

    async def set_project_settings(self, project_name: str, settings: dict[str, object]) -> None:
        self.calls.append("set_project_settings")
        self.settings = dict(settings)

    async def get_project_settings(self, project_name: str) -> dict[str, object]:
        self.calls.append("get_project_settings")
        return dict(self.settings)

    async def save_project(self, project_name: str, *, confirm: bool = False) -> None:
        self.calls.append("save_project")

    async def build_project(self, project_name: str) -> None:
        self.calls.append("build_project")

    async def run_project(self, project_name: str) -> None:
        self.calls.append("run_project")

    async def get_run_status(self, project_name: str) -> dict[str, str]:
        self.calls.append("get_run_status")
        return {"status": "idle"}

    async def discover_output_files(self, project_name: str, *, started_after: float, max_files: int = 32) -> list[str]:
        self.calls.append("discover_output_files")
        assert self.project is not None
        outputs = []
        for index in range(1, 3):
            output = self.project.parent / f"LCC_CASE_{index:02d}.out"
            output.write_text("waveform", encoding="ascii")
            outputs.append(str(output))
        return outputs

    async def read_output_file(self, file_path: str, *, max_samples: int = 1_000_000, summary_only: bool = False) -> dict[str, object]:
        self.calls.append("read_output_file")
        domain = [0.0, 0.8, 0.9, 1.0, 2.0]
        return {
            "channels": [
                {"path": "Fault/LCC Fault Active", "domain": domain, "values": [0, 1, 0, 0, 0]},
                {"path": "Inverter/DC Current", "domain": domain, "values": [1, 1.2, 1.1, 1, 1]},
                {"path": "Inverter/Gamma", "domain": domain, "values": [18, 5, 6, 18, 18]},
            ]
        }

    async def save_project_as(self, project_name: str, filename: str, folder: str, *, confirm: bool = False) -> None:
        self.calls.append("save_project_as")
        assert self.project is not None
        destination = Path(folder) / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.project, destination)


def test_blank_lcc_native_plan_records_source_and_fault_contract(tmp_path: Path) -> None:
    source = _template(tmp_path / "official.pscx")
    workspace = tmp_path / "workspace"
    service = BlankLccBuilderService(None, workspace_root=workspace)

    plan = service.plan_model(
        "LCC_CASE",
        folder=str(workspace),
        template_path=str(source),
    )

    assert plan["status"] == "planned"
    assert plan["native_template"]["source"] == str(source.resolve())
    assert plan["fault"]["time_s"] == 0.8
    assert plan["fault"]["duration_s"] == 0.1
    assert plan["companion"]["namespace"] == "cigre_lcc_v1"
    assert len(plan["plan_hash"]) == 64
    assert not workspace.exists()


def test_blank_lcc_service_records_live_master_audit(tmp_path: Path) -> None:
    source = _template(tmp_path / "official.pscx")
    workspace = tmp_path / "workspace"
    audited = _master_registry(tmp_path)
    service = BlankLccBuilderService(
        None,
        workspace_root=workspace,
        master_registry=audited,
    )

    plan = service.plan_model(
        "LCC_CASE",
        folder=str(workspace),
        template_path=str(source),
    )

    assert plan["native_template"]["master_sha256"] == audited.master_sha256
    assert (
        plan["native_template"]["master_binding_registry_sha256"]
        == audited.registry.sha256
    )


def test_blank_lcc_service_reads_live_master_inventory_bridge(tmp_path: Path) -> None:
    source = _template(tmp_path / "official.pscx")
    audited = _master_registry(tmp_path)

    class LiveInventoryBridge:
        def __init__(self):
            self.calls = 0

        async def get_lcc_inventory(self, catalog, registry):
            self.calls += 1
            return {
                "master_path": audited.master_path,
                "master_sha256": audited.master_sha256,
                "master_binding_registry_sha256": audited.registry.sha256,
                "definitions": {},
            }

    bridge = LiveInventoryBridge()
    service = BlankLccBuilderService(
        bridge,
        workspace_root=tmp_path / "workspace",
    )

    plan = service.plan_model(
        "LCC_CASE",
        folder=str(tmp_path / "workspace"),
        template_path=str(source),
    )

    assert bridge.calls == 1
    assert plan["native_template"]["master_sha256"] == audited.master_sha256


def test_blank_lcc_service_rejects_missing_master_reference(tmp_path: Path) -> None:
    source = _template(tmp_path / "official.pscx")
    service = BlankLccBuilderService(
        None,
        workspace_root=tmp_path / "workspace",
        master_registry=_master_registry(tmp_path, include_pgb=False),
    )

    with pytest.raises(BackendError) as failure:
        service.plan_model(
            "LCC_CASE",
            folder=str(tmp_path / "workspace"),
            template_path=str(source),
        )

    assert failure.value.code == "LCC_TEMPLATE_INCOMPATIBLE"
    assert "master_reference_missing:pgb" in failure.value.details["errors"]


def test_blank_lcc_service_honors_template_and_folder_from_request(tmp_path: Path) -> None:
    source = _template(tmp_path / "official.pscx")
    workspace = tmp_path / "workspace"
    destination = workspace / "nested"
    request = BlankLccRequest.from_dict(
        {
            "project_name": "LCC_CASE",
            "folder": str(destination),
            "template_path": str(source),
        }
    )
    service = BlankLccBuilderService(None, workspace_root=workspace)

    plan = service.plan_model(
        request.project_name,
        request=request,
    )

    assert plan["target_path"] == str((destination / "LCC_CASE.pscx").resolve())
    assert plan["native_template"]["source"] == str(source.resolve())


def test_blank_lcc_native_plan_requires_an_explicit_template(tmp_path: Path) -> None:
    service = BlankLccBuilderService(None, workspace_root=tmp_path)

    with pytest.raises(BackendError) as raised:
        service.plan_model("LCC_CASE", folder=str(tmp_path))

    assert raised.value.code == "LCC_TEMPLATE_REQUIRED"


def test_blank_lcc_native_build_publishes_only_after_waveform_acceptance(tmp_path: Path) -> None:
    source = _template(tmp_path / "official.pscx")
    workspace = tmp_path / "workspace"
    fake = _NativeLccServiceFake()
    service = BlankLccBuilderService(fake, workspace_root=workspace)
    plan = service.plan_model("LCC_CASE", folder=str(workspace), template_path=str(source))

    async def run() -> dict[str, object]:
        started = await service.build_model("LCC_CASE", plan["plan_hash"], folder=str(workspace), confirm=True, template_path=str(source))
        await asyncio.sleep(0)
        return service.get_build_status(str(started["build_id"]))

    status = asyncio.run(run())

    assert status["state"] == "published"
    assert Path(plan["target_path"]).is_file()
    assert (Path(plan["target_path"]).parent / "cigre_lcc_v1.pslx").is_file()
    assert Path(plan["target_path"]).with_name("LCC_CASE_scenario_source.pscx").is_file()
    persisted_output = Path(status["result"]["output_file"])
    assert persisted_output.is_file()
    assert persisted_output.parent.name == "LCC_CASE.outputs"
    assert fake.calls.index("read_output_file") < fake.calls.index("save_project_as")


def test_blank_lcc_validation_accepts_a_contained_absolute_project_path(tmp_path: Path) -> None:
    source = _template(tmp_path / "official.pscx")
    workspace = tmp_path / "workspace"
    project = workspace / "LCC_CASE.pscx"
    library = workspace / "cigre_lcc_v1.pslx"
    from pscad_mcp.hvdc.builders.lcc.native_template import (
        materialize_native_lcc_bundle,
    )

    materialize_native_lcc_bundle(
        source,
        project,
        library,
        project_name="LCC_CASE",
        fault_time_s=0.8,
        fault_duration_s=0.1,
    )
    output = workspace / "result.out"
    output.write_text("waveform", encoding="ascii")
    fake = _NativeLccServiceFake()

    result = BlankLccBuilderService(fake, workspace_root=workspace).validate_model(
        str(project), output_file=str(output)
    )

    assert result["project_file"] == str(project.resolve())
    assert result["acceptance"]["status"] == "evaluated"


def test_blank_lcc_build_fails_if_the_official_source_changes_during_execution(tmp_path: Path) -> None:
    source = _template(tmp_path / "official.pscx")
    workspace = tmp_path / "workspace"
    fake = _NativeLccServiceFake()
    service = BlankLccBuilderService(fake, workspace_root=workspace)
    plan = service.plan_model("LCC_CASE", folder=str(workspace), template_path=str(source))
    fake.source_to_mutate = source

    async def run() -> dict[str, object]:
        started = await service.build_model("LCC_CASE", plan["plan_hash"], folder=str(workspace), confirm=True, template_path=str(source))
        await asyncio.sleep(0)
        return service.get_build_status(str(started["build_id"]))

    status = asyncio.run(run())

    assert status["state"] == "failed"
    assert status["error"]["code"] == "LCC_PLAN_STALE"
    assert not Path(plan["target_path"]).exists()


def test_blank_lcc_plan_rejects_non_finite_duration(tmp_path: Path) -> None:
    source = _template(tmp_path / "official.pscx")
    service = BlankLccBuilderService(None, workspace_root=tmp_path / "workspace")

    with pytest.raises(BackendError) as raised:
        service.plan_model(
            "LCC_CASE",
            folder=str(tmp_path / "workspace"),
            simulation_duration_s=float("inf"),
            template_path=str(source),
        )

    assert raised.value.code == "LCC_BLUEPRINT_INVALID"


def test_blank_lcc_plan_rejects_a_dangling_destination_link(tmp_path: Path) -> None:
    source = _template(tmp_path / "official.pscx")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "LCC_CASE.pscx"
    try:
        target.symlink_to(workspace / "missing.pscx")
    except OSError as error:
        pytest.skip(f"file symlinks unavailable: {error}")
    service = BlankLccBuilderService(None, workspace_root=workspace)

    with pytest.raises(BackendError) as raised:
        service.plan_model(
            "LCC_CASE",
            folder=str(workspace),
            template_path=str(source),
        )

    assert raised.value.code == "LCC_BUILD_CONFLICT"
