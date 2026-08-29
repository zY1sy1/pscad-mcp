from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.blank import BlankMmcRequest
from pscad_mcp.hvdc.builders.mmc.blank_service import BlankMmcBuilderService
from tests.test_mmc_template_native import _template as _native_template


def _audit(topology: str) -> dict[str, object]:
    return {
        "compatible": True,
        "pscad_version": "4.6.2",
        "source_hashes": {"project": "a" * 64, "library": "b" * 64},
        "definitions": ["project:Main", "intermediate:FullCellR_n"],
        "absolute_paths": [],
        "compiler_support": {"required": False, "present": True, "hashes": {}},
        "template_native_controls": {"available": True, "time_basis": "EMTDC"},
        "submodule_topology": {"declared": topology, "full_cell_instances": 4, "firing_hbridge_instances": 3},
    }


def test_blank_mmc_plan_records_audited_topology_and_source_hashes(tmp_path: Path) -> None:
    template = tmp_path / "template.pscx"
    library = tmp_path / "library.pslx"
    template.write_text("template", encoding="ascii")
    library.write_text("library", encoding="ascii")
    service = BlankMmcBuilderService(
        None,
        workspace_root=tmp_path / "workspace",
        audit_loader=lambda *_args: _audit("full_bridge"),
    )
    request = BlankMmcRequest.from_dict(
        {
            "project_name": "MMC_CASE",
            "template_path": str(template),
            "library_path": str(library),
            "submodule_topology": "full_bridge",
        }
    )

    plan = service.plan_model(request, folder=str(tmp_path / "workspace"))

    assert plan["status"] == "planned"
    assert plan["capabilities"]["intrinsic_dc_fault_blocking"] is True
    assert plan["template_native"]["source_hashes"]["project"] == "a" * 64
    assert plan["template_native"]["source_hashes"]["library"] == "b" * 64


def test_blank_mmc_plan_rejects_topology_mismatch(tmp_path: Path) -> None:
    template = tmp_path / "template.pscx"
    library = tmp_path / "library.pslx"
    template.write_text("template", encoding="ascii")
    library.write_text("library", encoding="ascii")
    service = BlankMmcBuilderService(
        None,
        workspace_root=tmp_path / "workspace",
        audit_loader=lambda *_args: _audit("half_bridge"),
    )
    request = BlankMmcRequest.from_dict(
        {
            "project_name": "MMC_CASE",
            "template_path": str(template),
            "library_path": str(library),
            "submodule_topology": "full_bridge",
        }
    )

    with pytest.raises(BackendError) as raised:
        service.plan_model(request, folder=str(tmp_path / "workspace"))

    assert raised.value.code == "MMC_TEMPLATE_TOPOLOGY_MISMATCH"


class _MmcNativeFake:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.project: Path | None = None
        self.settings: dict[str, object] = {}

    async def load_projects(self, paths: list[str]) -> None:
        self.calls.append("load_projects")
        self.project = Path(paths[-1])

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
        output = self.project.parent / "native_01.out"
        output.write_text("waveform", encoding="ascii")
        return [str(output)]

    async def read_output_file(self, file_path: str, *, max_samples: int = 1_000_000, summary_only: bool = False) -> dict[str, object]:
        self.calls.append("read_output_file")
        return {
            "channels": [
                {"description": "Fault mode", "domain": [0.0, 0.3, 0.5], "values": [0.0, 1.0, 0.0]},
                {"description": "DC fault current", "domain": [0.0, 0.3, 0.5], "values": [0.0, 1.0, 0.0]},
                {"description": "De-blocking T1", "domain": [0.0, 0.3, 0.5], "values": [1.0, 0.0, 1.0]},
            ]
        }


def test_blank_mmc_native_build_keeps_staging_when_fault_evidence_is_incomplete(tmp_path: Path) -> None:
    template = _native_template(tmp_path / "template.pscx")
    library = tmp_path / "library.pslx"
    library.write_text("<project name='library' Target='Library'><definitions /></project>", encoding="ascii")
    workspace = tmp_path / "workspace"
    fake = _MmcNativeFake()
    def audit_for_build(template_path: str, library_path: str) -> dict[str, object]:
        report = _audit("full_bridge")
        report["source_hashes"] = {
            "project": hashlib.sha256(Path(template_path).read_bytes()).hexdigest(),
            "library": hashlib.sha256(Path(library_path).read_bytes()).hexdigest(),
        }
        return report

    service = BlankMmcBuilderService(
        fake,
        workspace_root=workspace,
        audit_loader=audit_for_build,
    )
    request = BlankMmcRequest.from_dict(
        {
            "project_name": "MMC_CASE",
            "template_path": str(template),
            "library_path": str(library),
            "submodule_topology": "full_bridge",
        }
    )
    plan = service.plan_model(request, folder=str(workspace))

    async def run() -> dict[str, object]:
        started = await service.build_model(request, plan["plan_hash"], confirm=True)
        await asyncio.sleep(0)
        return service.get_build_status(str(started["build_id"]))

    status = asyncio.run(run())

    assert status["state"] == "failed"
    assert status["error"]["code"] == "MMC_ACCEPTANCE_INCOMPLETE"
    assert not Path(plan["target_path"]).exists()
    assert Path(plan["staging_path"]).is_dir()


def test_blank_mmc_validation_uses_audited_half_bridge_capability(tmp_path: Path) -> None:
    project = tmp_path / "MMC_CASE.pscx"
    library = tmp_path / "intermediate.pslx"
    output = tmp_path / "MMC_CASE.out"
    project.write_text("<project />", encoding="ascii")
    library.write_text("<project name='library' Target='Library' />", encoding="ascii")
    output.write_text("waveform", encoding="ascii")
    fake = _MmcNativeFake()
    service = BlankMmcBuilderService(
        fake,
        workspace_root=tmp_path,
        audit_loader=lambda *_args: _audit("half_bridge"),
    )

    async def call() -> dict[str, object]:
        return service.validate_model(
            str(project),
            output_file=str(output),
            template_path=str(project),
            library_path=str(library),
        )

    result = asyncio.run(call())

    assert result["acceptance"]["verdict"] == "NOT_APPLICABLE"


def test_blank_mmc_plan_rejects_non_finite_duration(tmp_path: Path) -> None:
    template = tmp_path / "template.pscx"
    library = tmp_path / "library.pslx"
    template.write_text("template", encoding="ascii")
    library.write_text("library", encoding="ascii")
    service = BlankMmcBuilderService(
        None,
        workspace_root=tmp_path / "workspace",
        audit_loader=lambda *_args: _audit("full_bridge"),
    )
    request = BlankMmcRequest.from_dict(
        {
            "project_name": "MMC_CASE",
            "template_path": str(template),
            "library_path": str(library),
        }
    )

    with pytest.raises(BackendError) as raised:
        service.plan_model(
            request,
            folder=str(tmp_path / "workspace"),
            simulation_duration_s=float("inf"),
        )

    assert raised.value.code == "MMC_BLUEPRINT_INVALID"


def test_blank_mmc_plan_rejects_a_dangling_destination_link(tmp_path: Path) -> None:
    template = tmp_path / "template.pscx"
    library = tmp_path / "library.pslx"
    template.write_text("template", encoding="ascii")
    library.write_text("library", encoding="ascii")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "MMC_CASE.pscx"
    try:
        target.symlink_to(workspace / "missing.pscx")
    except OSError as error:
        pytest.skip(f"file symlinks unavailable: {error}")
    service = BlankMmcBuilderService(
        None,
        workspace_root=workspace,
        audit_loader=lambda *_args: _audit("full_bridge"),
    )
    request = BlankMmcRequest.from_dict(
        {
            "project_name": "MMC_CASE",
            "template_path": str(template),
            "library_path": str(library),
        }
    )

    with pytest.raises(BackendError) as raised:
        service.plan_model(request, folder=str(workspace))

    assert raised.value.code == "MMC_BUILD_CONFLICT"


def test_blank_mmc_validation_accepts_a_minimal_output_reader(tmp_path: Path) -> None:
    project = tmp_path / "MMC_CASE.pscx"
    library = tmp_path / "intermediate.pslx"
    output = tmp_path / "MMC_CASE.out"
    project.write_text("<project />", encoding="ascii")
    library.write_text("<project name='library' Target='Library' />", encoding="ascii")
    output.write_text("waveform", encoding="ascii")

    class MinimalReader:
        async def read_output_file(self, file_path: str) -> dict[str, object]:
            return {"channels": []}

    service = BlankMmcBuilderService(
        MinimalReader(),
        workspace_root=tmp_path,
        audit_loader=lambda *_args: _audit("half_bridge"),
    )

    result = service.validate_model(
        str(project),
        output_file=str(output),
        template_path=str(project),
        library_path=str(library),
    )

    assert result["acceptance"]["verdict"] == "NOT_APPLICABLE"


def test_blank_mmc_validation_rejects_partial_template_pair(tmp_path: Path) -> None:
    project = tmp_path / "MMC_CASE.pscx"
    project.write_text("<project />", encoding="ascii")
    service = BlankMmcBuilderService(
        None,
        workspace_root=tmp_path,
        audit_loader=lambda *_args: _audit("full_bridge"),
    )

    with pytest.raises(BackendError) as raised:
        service.validate_model(
            str(project),
            template_path=str(project),
        )

    assert raised.value.code == "MMC_TEMPLATE_PAIR_INVALID"


def test_blank_mmc_validation_marks_an_incompatible_audit_invalid(tmp_path: Path) -> None:
    project = tmp_path / "MMC_CASE.pscx"
    library = tmp_path / "intermediate.pslx"
    project.write_text("<project />", encoding="ascii")
    library.write_text("<project />", encoding="ascii")
    service = BlankMmcBuilderService(
        None,
        workspace_root=tmp_path,
        audit_loader=lambda *_args: {"compatible": False, "submodule_topology": {}},
    )

    result = service.validate_model(
        str(project),
        template_path=str(project),
        library_path=str(library),
    )

    assert result["valid"] is False


def test_blank_mmc_validation_never_accepts_incompatible_audit(
    tmp_path: Path,
) -> None:
    project = tmp_path / "MMC_CASE.pscx"
    library = tmp_path / "intermediate.pslx"
    output = tmp_path / "MMC_CASE.out"
    project.write_text("<project />", encoding="ascii")
    library.write_text("<project />", encoding="ascii")
    output.write_text("waveform", encoding="ascii")

    class PassingReader:
        async def read_output_file(self, file_path: str) -> dict[str, object]:
            domain = [0.0, 0.2, 0.4]
            return {
                "channels": [
                    {"description": "Fault mode", "domain": domain, "values": [0.0, 1.0, 0.0]},
                    {"description": "DC fault current", "domain": domain, "values": [0.0, 1.0, 0.0]},
                    {"description": "De-blocking", "domain": domain, "values": [1.0, 0.0, 1.0]},
                    {"description": "V_inserted", "domain": domain, "values": [0.0, -1.0, 0.0]},
                ]
            }

    service = BlankMmcBuilderService(
        PassingReader(),
        workspace_root=tmp_path,
        audit_loader=lambda *_args: {"compatible": False, "submodule_topology": {"declared": "full_bridge"}},
    )

    result = service.validate_model(
        str(project),
        output_file=str(output),
        template_path=str(project),
        library_path=str(library),
    )

    assert result["valid"] is False
    assert result["accepted"] is False
