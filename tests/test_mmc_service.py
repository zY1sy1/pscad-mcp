from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import ConfirmationRequired
from pscad_mcp.hvdc.builders.mmc.models import MmcBuildRecord, MmcBuildState
from pscad_mcp.hvdc.builders.mmc.planner import MmcPlanRequest
from pscad_mcp.hvdc.builders.mmc.service import MmcBuilderService

from tests.mmc_builder_fakes import RecordingMmcService
from tests.test_mmc_planner import ASSET, INVENTORY


class OutputReadingService(RecordingMmcService):
    async def read_output_file(self, file_path: str, max_samples: int = 10_000, channel: str | None = None, summary_only: bool = False) -> dict[str, object]:
        self._call("read_output_file", file_path, max_samples, channel, summary_only)
        return {"vdc": {"units": "kV", "time": [0.0, 1.0], "values": [640.0, 640.0]}}


def _successful_executor(plan, service, workspace_root, *, asset_set, build_id, journal):
    async def run():
        record = MmcBuildRecord(build_id=build_id, state=MmcBuildState.PUBLISHED, plan=plan, history=( {"state": "validated"}, {"state": "published"}), result={"verdict": "PASS"}, workspace=str(workspace_root))
        journal.write(record.to_dict())
        return record

    return run()


def _service(tmp_path, *, executor_factory=None, asset_loader=lambda name: ASSET, pscad=None):
    pscad = pscad or SimpleNamespace(path_policy=PathPolicy(str(tmp_path)))
    return MmcBuilderService(pscad, workspace_root=tmp_path, inventory=INVENTORY, asset_loader=asset_loader, executor_factory=executor_factory or _successful_executor)


def test_plan_model_is_side_effect_free_and_json_safe(tmp_path):
    service = _service(tmp_path)

    plan = service.plan_model("MMC_STAGE_A")

    assert plan["plan_hash"]
    assert plan["blueprint"]["profile"] == "cigre_b4_p2p_avm_v1"
    assert list(tmp_path.iterdir()) == []


def test_build_requires_confirmation_and_rejects_stale_hash_before_lease(tmp_path):
    service = _service(tmp_path)
    plan = service.plan_model("MMC_STAGE_A")

    with pytest.raises(ConfirmationRequired):
        asyncio.run(service.build_model("MMC_STAGE_A", plan["plan_hash"], confirm=False))
    with pytest.raises(BackendError) as raised:
        asyncio.run(service.build_model("MMC_STAGE_A", "stale", confirm=True))
    assert raised.value.code == "MMC_PLAN_STALE"
    assert not (tmp_path / ".pscad-mcp" / "mmc-build.lock").exists()


def test_valid_build_returns_status_and_releases_mmc_lease(tmp_path):
    service = _service(tmp_path)
    plan = service.plan_model("MMC_STAGE_A")

    started = asyncio.run(service.build_model("MMC_STAGE_A", plan["plan_hash"], confirm=True))

    assert started["state"] == "validated"
    assert service.get_build_status(started["build_id"])["state"] in {"validated", "published"}
    asyncio.run(asyncio.sleep(0))
    assert service.get_build_status(started["build_id"])["state"] == "published"
    assert not (tmp_path / ".pscad-mcp" / "mmc-build.lock").exists()


def test_validation_is_read_only_and_marks_missing_waveform_as_not_evaluated(tmp_path, monkeypatch):
    service = _service(tmp_path, pscad=RecordingMmcService())
    project_path = tmp_path / "MMC_STAGE_A.pscx"
    project_path.write_text("<project />", encoding="utf-8")
    monkeypatch.setattr("pscad_mcp.hvdc.builders.mmc.service.read_project_graph", lambda *args, **kwargs: object())
    monkeypatch.setattr("pscad_mcp.hvdc.builders.mmc.service.validate_project_graph", lambda *args, **kwargs: {"valid": True, "findings": []})

    result = service.validate_model("MMC_STAGE_A")

    assert result["valid"] is True
    assert result["accepted"] is False
    assert result["acceptance"]["verdict"] == "not_evaluated"
    assert service.pscad_service.calls == []


def test_validation_reads_waveform_without_mutating_pscad(tmp_path, monkeypatch):
    pscad = OutputReadingService()
    service = _service(tmp_path, pscad=pscad)
    project_path = tmp_path / "MMC_STAGE_A.pscx"
    output_path = tmp_path / "MMC_STAGE_A.out"
    project_path.write_text("<project />", encoding="utf-8")
    output_path.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr("pscad_mcp.hvdc.builders.mmc.service.read_project_graph", lambda *args, **kwargs: object())
    monkeypatch.setattr("pscad_mcp.hvdc.builders.mmc.service.validate_project_graph", lambda *args, **kwargs: {"valid": True, "findings": []})

    result = service.validate_model("MMC_STAGE_A", output_file=str(output_path))

    assert result["valid"] is True
    assert result["accepted"] is False
    assert result["acceptance"]["verdict"] == "INCOMPLETE_ANALYSIS"
    assert [call[0] for call in pscad.calls] == ["read_output_file"]
