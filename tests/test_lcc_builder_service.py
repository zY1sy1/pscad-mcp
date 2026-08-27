from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import ConfirmationRequired
from pscad_mcp.hvdc.builders.lcc.models import LccBuildRecord, LccBuildState
from pscad_mcp.hvdc.builders.lcc.planner import LccPlanRequest
from pscad_mcp.hvdc.builders.lcc.service import LccBuilderService
from pscad_mcp.runtime import PendingCleanupError

from lcc_builder_fakes import RecordingPscadService
from test_lcc_planner import BLUEPRINT, INVENTORY, _asset_set


class OutputReadingService(RecordingPscadService):
    async def read_output_file(
        self,
        file_path: str,
        max_samples: int = 10_000,
        channel: str | None = None,
        summary_only: bool = False,
    ) -> dict[str, object]:
        self._call("read_output_file", file_path, max_samples, channel, summary_only)
        return {"time": [0.0, 1.0], "channels": {}}


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


def test_plan_model_fails_closed_without_live_inventory(tmp_path):
    pscad = SimpleNamespace(path_policy=PathPolicy(str(tmp_path)))
    service = LccBuilderService(
        pscad,
        asset_loader=lambda name: _asset_set(),
    )

    with pytest.raises(BackendError) as raised:
        service.plan_model("CIGRE_LCC")

    assert raised.value.code == "LCC_DEFINITION_MISSING"
    assert raised.value.details["reason"] == "live_inventory_unavailable"
    assert list(tmp_path.iterdir()) == []


def test_plan_model_uses_async_live_inventory_bridge(tmp_path):
    class LiveInventoryService:
        path_policy = PathPolicy(str(tmp_path))

        async def get_lcc_inventory(self, catalog):
            assert catalog["pscad_version"] == "4.6.2"
            return INVENTORY

    service = LccBuilderService(
        LiveInventoryService(),
        asset_loader=lambda name: _asset_set(),
    )

    plan = service.plan_model("CIGRE_LCC")

    assert plan["pscad_version"] == "4.6.2"


def test_explicit_workspace_root_controls_the_builder_path_policy(tmp_path):
    service_workspace = tmp_path / "service-workspace"
    explicit_workspace = tmp_path / "explicit-workspace"
    pscad = SimpleNamespace(path_policy=PathPolicy(str(service_workspace)))
    service = LccBuilderService(
        pscad,
        workspace_root=explicit_workspace,
        inventory=INVENTORY,
        asset_loader=lambda name: _asset_set(),
    )

    plan = service.plan_model("CIGRE_LCC")

    assert Path(plan["target_path"]).parent == explicit_workspace.resolve()
    assert str(service.path_policy.workspace_root) == str(explicit_workspace.resolve())


def test_planner_rejects_component_parameters_outside_catalog_contract(tmp_path):
    candidate = dict(BLUEPRINT)
    candidate["components"] = [dict(component) for component in BLUEPRINT["components"]]
    candidate["components"][0]["parameters"] = {"Amplitude": 1001.0}

    with pytest.raises(BackendError) as raised:
        from pscad_mcp.hvdc.builders.lcc.planner import LccPlanRequest, create_plan

        create_plan(LccPlanRequest("CIGRE_LCC"), _asset_set(candidate), INVENTORY, tmp_path)

    assert raised.value.code == "LCC_PARAMETER_MISMATCH"


def test_build_requires_confirmation_and_rejects_stale_hash_before_lease(tmp_path):
    service = _service(tmp_path)
    plan = service.plan_model("CIGRE_LCC")

    with pytest.raises(ConfirmationRequired):
        asyncio.run(service.build_model("CIGRE_LCC", plan["plan_hash"], confirm=False))
    with pytest.raises(BackendError) as raised:
        asyncio.run(service.build_model("CIGRE_LCC", "stale", confirm=True))
    assert raised.value.code == "LCC_PLAN_STALE"
    assert not (tmp_path / ".pscad-mcp" / "lcc-build.lock").exists()


def test_build_rejects_assets_changed_since_planning_without_leaking_lease(tmp_path):
    original = _asset_set()
    changed = replace(original, hashes={"library/cigre_lcc_v1.pslx": "b" * 64})
    calls = 0

    def load_assets(name):
        nonlocal calls
        calls += 1
        return original if calls == 1 else changed

    pscad = SimpleNamespace(path_policy=PathPolicy(str(tmp_path)))
    service = LccBuilderService(
        pscad,
        inventory=INVENTORY,
        asset_loader=load_assets,
        executor_factory=_successful_executor,
    )
    parsed_plan = service._create_plan(LccPlanRequest("CIGRE_LCC"))

    with pytest.raises(BackendError) as raised:
        asyncio.run(service._start_build(parsed_plan))

    assert raised.value.code == "LCC_ASSET_MISMATCH"
    assert raised.value.details["reason"] == "plan_assets_changed"
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


def test_shutdown_interrupts_build_releases_lease_and_rejects_new_builds(tmp_path):
    entered = asyncio.Event()

    async def blocking_executor(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    service = _service(tmp_path, executor_factory=blocking_executor)
    plan = service.plan_model("CIGRE_LCC")

    async def exercise():
        started = await service.build_model(
            "CIGRE_LCC", plan["plan_hash"], confirm=True
        )
        await entered.wait()
        await service.shutdown(timeout_s=0.2)
        with pytest.raises(BackendError) as raised:
            await service.build_model(
                "CIGRE_LCC", plan["plan_hash"], confirm=True
            )
        return started, raised.value

    started, error = asyncio.run(exercise())
    assert service.get_build_status(started["build_id"])["state"] == "interrupted"
    assert error.code == "LCC_BUILD_CONFLICT"
    assert service._tasks == {}
    assert service._leases == {}
    assert not (tmp_path / ".pscad-mcp" / "lcc-build.lock").exists()


def test_shutdown_releases_lease_when_build_task_never_started(tmp_path):
    async def blocking_executor(*args, **kwargs):
        await asyncio.Event().wait()

    service = _service(tmp_path, executor_factory=blocking_executor)
    plan = service.plan_model("CIGRE_LCC")

    async def exercise():
        started = await service.build_model(
            "CIGRE_LCC", plan["plan_hash"], confirm=True
        )
        await service.shutdown(timeout_s=0.2)
        return started

    started = asyncio.run(exercise())
    assert service.get_build_status(started["build_id"])["state"] == "interrupted"
    assert service._leases == {}
    assert not (tmp_path / ".pscad-mcp" / "lcc-build.lock").exists()


def test_shutdown_reports_live_fixed_builder_task_as_pending(tmp_path):
    service = _service(tmp_path)

    async def exercise():
        release = asyncio.Event()

        async def stubborn():
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue

        task = asyncio.create_task(stubborn())
        service._tasks["pending"] = task
        await asyncio.sleep(0)
        try:
            with pytest.raises(PendingCleanupError) as raised:
                await service.shutdown(timeout_s=0.02)
            assert task in raised.value.pending_tasks
        finally:
            release.set()
            await task

    asyncio.run(exercise())


def test_builder_service_forwards_injected_threshold_registry_to_executor(tmp_path):
    registry = {"review": {"review_id": "review"}}
    captured = {}

    async def recording_executor(
        plan,
        service,
        workspace_root,
        *,
        asset_set,
        build_id,
        journal,
        trusted_threshold_sources,
    ):
        captured["registry"] = trusted_threshold_sources
        return await _successful_executor(
            plan,
            service,
            workspace_root,
            asset_set=asset_set,
            build_id=build_id,
            journal=journal,
        )

    pscad = SimpleNamespace(path_policy=PathPolicy(str(tmp_path)))
    service = LccBuilderService(
        pscad,
        inventory=INVENTORY,
        asset_loader=lambda name: _asset_set(),
        executor_factory=recording_executor,
        trusted_threshold_sources=registry,
    )
    plan = service.plan_model("CIGRE_LCC")

    async def scenario():
        started = await service.build_model("CIGRE_LCC", plan["plan_hash"], confirm=True)
        for _ in range(10):
            await asyncio.sleep(0)
            if service.get_build_status(started["build_id"])["state"] == "published":
                break

    asyncio.run(scenario())

    assert captured["registry"] is registry


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


def test_validation_marks_waveform_acceptance_not_evaluated_without_output_samples(tmp_path, monkeypatch):
    service = _service(tmp_path)
    output_path = tmp_path / "CIGRE_LCC.pscx"
    output_path.write_text("<project />", encoding="utf-8")
    monkeypatch.setattr(
        "pscad_mcp.hvdc.builders.lcc.service.read_project_graph",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        "pscad_mcp.hvdc.builders.lcc.service.validate_project_graph",
        lambda *args, **kwargs: {"valid": True, "errors": [], "warnings": []},
    )

    result = service.validate_model("CIGRE_LCC")

    assert result["valid"] is True
    assert result["acceptance"]["status"] == "not_evaluated"


def test_validation_reads_supplied_waveform_and_preserves_incomplete_acceptance(tmp_path, monkeypatch):
    pscad = OutputReadingService()
    pscad.path_policy = PathPolicy(str(tmp_path))
    service = LccBuilderService(
        pscad,
        workspace_root=tmp_path,
        inventory=INVENTORY,
        asset_loader=lambda name: _asset_set(),
    )
    project_path = tmp_path / "CIGRE_LCC.pscx"
    output_path = tmp_path / "CIGRE_LCC.out"
    project_path.write_text("<project />", encoding="utf-8")
    output_path.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(
        "pscad_mcp.hvdc.builders.lcc.service.read_project_graph",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        "pscad_mcp.hvdc.builders.lcc.service.validate_project_graph",
        lambda *args, **kwargs: {"valid": True, "errors": [], "warnings": []},
    )

    result = service.validate_model("CIGRE_LCC", output_file=str(output_path))

    assert result["valid"] is True
    assert result["accepted"] is False
    assert result["acceptance"]["verdict"] == "INCOMPLETE_ANALYSIS"
    assert [call[0] for call in pscad.calls] == ["read_output_file"]
    assert pscad.calls[0][1][0] == str(output_path.resolve())


def test_validation_forwards_injected_threshold_registry_to_acceptance(tmp_path, monkeypatch):
    registry = {"review": {"review_id": "review"}}
    captured = {}
    pscad = OutputReadingService()
    pscad.path_policy = PathPolicy(str(tmp_path))
    service = LccBuilderService(
        pscad,
        workspace_root=tmp_path,
        inventory=INVENTORY,
        asset_loader=lambda name: _asset_set(),
        trusted_threshold_sources=registry,
    )
    project_path = tmp_path / "CIGRE_LCC.pscx"
    output_path = tmp_path / "CIGRE_LCC.out"
    project_path.write_text("<project />", encoding="utf-8")
    output_path.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(
        "pscad_mcp.hvdc.builders.lcc.service.read_project_graph",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        "pscad_mcp.hvdc.builders.lcc.service.validate_project_graph",
        lambda *args, **kwargs: {"valid": True, "errors": [], "warnings": []},
    )

    def fake_acceptance(samples, golden, contract, trusted_threshold_sources=None):
        captured["registry"] = trusted_threshold_sources
        return {"verdict": "PASS"}

    monkeypatch.setattr(
        "pscad_mcp.hvdc.builders.lcc.service.evaluate_acceptance",
        fake_acceptance,
    )

    result = service.validate_model("CIGRE_LCC", output_file=str(output_path))

    assert result["accepted"] is True
    assert captured["registry"] is registry
