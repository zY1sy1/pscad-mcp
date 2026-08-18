from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import ConfirmationRequired
from pscad_mcp.hvdc.builders.lcc.models import LccBuildRecord, LccBuildState
from pscad_mcp.hvdc.builders.lcc.service import LccBuilderService

from lcc_builder_fakes import RecordingPscadService
from test_lcc_planner import INVENTORY, _asset_set


def _service(tmp_path, *, executor_factory=None):
    pscad = SimpleNamespace(path_policy=PathPolicy(str(tmp_path)))
    asset = _asset_set()
    return LccBuilderService(
        pscad,
        inventory=INVENTORY,
        asset_loader=lambda name: asset,
        executor_factory=executor_factory or _successful_executor,
    )


async def _successful_executor(plan, service, workspace_root, *, asset_set, build_id, journal):
    record = LccBuildRecord(
        build_id=build_id,
        state=LccBuildState.PUBLISHED,
        plan=plan,
        history=({"state": "validated"}, {"state": "published"}),
        result={"verdict": "PASS"},
        workspace=str(workspace_root),
    )
    journal.write(record.to_dict())
    return record


def test_plan_model_is_side_effect_free_and_json_safe(tmp_path):
    service = _service(tmp_path)

    plan = service.plan_model("CIGRE_LCC")

    assert plan["plan_hash"]
    assert plan["blueprint"]["name"] == "cigre_lcc_monopole_v1"
    assert list(tmp_path.iterdir()) == []


def test_build_requires_confirmation_and_rejects_stale_hash_before_lease(tmp_path):
    service = _service(tmp_path)
    plan = service.plan_model("CIGRE_LCC")

    with pytest.raises(ConfirmationRequired):
        asyncio.run(service.build_model("CIGRE_LCC", plan["plan_hash"], confirm=False))
    with pytest.raises(BackendError) as raised:
        asyncio.run(service.build_model("CIGRE_LCC", "stale", confirm=True))
    assert raised.value.code == "LCC_PLAN_STALE"
    assert not (tmp_path / ".pscad-mcp" / "lcc-build.lock").exists()


def test_valid_build_returns_without_waiting_and_status_is_json_safe(tmp_path):
    service = _service(tmp_path)
    plan = service.plan_model("CIGRE_LCC")

    started = asyncio.run(service.build_model("CIGRE_LCC", plan["plan_hash"], confirm=True))

    assert started["build_id"]
    assert started["state"] == "validated"
    status = service.get_build_status(started["build_id"])
    assert status["state"] in {"validated", "published"}
    asyncio.run(asyncio.sleep(0))
    status = service.get_build_status(started["build_id"])
    assert status["state"] == "published"
    assert not (tmp_path / ".pscad-mcp" / "lcc-build.lock").exists()


def test_unknown_build_id_is_not_found(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(BackendError) as raised:
        service.get_build_status("missing")

    assert raised.value.code == "NOT_FOUND"


def test_validation_does_not_call_mutating_service_methods(tmp_path, monkeypatch):
    pscad = RecordingPscadService()
    service = LccBuilderService(
        pscad,
        workspace_root=tmp_path,
        inventory=INVENTORY,
        asset_loader=lambda name: _asset_set(),
    )
    monkeypatch.setattr(
        "pscad_mcp.hvdc.builders.lcc.service.read_project_graph",
        lambda *args, **kwargs: (_ for _ in ()).throw(BackendError("LCC_STRUCTURE_INVALID", "fixture", "hvdc", "read_lcc_project_graph")),
    )

    with pytest.raises(BackendError):
        service.validate_model("CIGRE_LCC", output_file=str(tmp_path / "CIGRE_LCC.pscx"))

    assert [call[0] for call in pscad.calls] == []
