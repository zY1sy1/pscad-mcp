from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from blueprint_builder_fakes import RecordingBlueprintPscadService
from pscad_mcp.builders.blueprint.journal import WorkspaceBuildLease
from pscad_mcp.builders.blueprint.models import BlueprintBuildState
from pscad_mcp.builders.blueprint.service import BlueprintBuilderService
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import ConfirmationRequired
from test_blueprint_assets import write_source_package
from test_blueprint_planner import live_inventory
from test_blueprint_schema import valid_blueprint


class ServicePscadFake(RecordingBlueprintPscadService):
    def __init__(self, workspace: Path, **kwargs):
        super().__init__(**kwargs)
        self.path_policy = PathPolicy(str(workspace))

    async def get_blueprint_inventory(self, project_name: str, inspection_profile: str | None):
        self._call("get_blueprint_inventory", project_name, inspection_profile)
        return live_inventory()


@pytest.mark.asyncio
async def test_build_requires_confirmation_and_exact_current_plan(tmp_path):
    source = write_source_package(tmp_path)
    service = BlueprintBuilderService(ServicePscadFake(tmp_path), workspace_root=tmp_path)
    blueprint = valid_blueprint()
    planned = await service.plan_project(blueprint, str(source), "BuiltCase")

    with pytest.raises(ConfirmationRequired):
        await service.build_project(planned["plan_hash"], blueprint, str(source), "BuiltCase", confirm=False)
    with pytest.raises(BackendError) as stale:
        await service.build_project("0" * 64, blueprint, str(source), "BuiltCase", confirm=True)
    assert stale.value.code == "BLUEPRINT_PLAN_STALE"

    (source / "support" / "notes.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(BackendError) as source_stale:
        await service.build_project(planned["plan_hash"], blueprint, str(source), "BuiltCase", confirm=True)
    assert source_stale.value.code == "BLUEPRINT_PLAN_STALE"


@pytest.mark.asyncio
async def test_async_build_publishes_only_declared_evidence_and_reports_status(tmp_path):
    source = write_source_package(tmp_path)
    backend = ServicePscadFake(tmp_path)
    service = BlueprintBuilderService(backend, workspace_root=tmp_path)
    blueprint = valid_blueprint()
    planned = await service.plan_project(blueprint, str(source), "BuiltCase")

    started = await service.build_project(planned["plan_hash"], blueprint, str(source), "BuiltCase", confirm=True)
    pending = service.get_build_status(started["build_id"])
    assert pending["state"] in {"planned", "staging_created", "mutations_applied", "structure_verified", "saved", "reloaded", "parameters_verified", "compiled", "simulated", "acceptance_passed", "published"}
    final = await service.wait_for_build(started["build_id"])

    assert final["state"] == "published"
    assert final["published"] is True
    assert final["publication_scope"] == "model_run_through_only"
    publication = Path(final["publication_path"])
    assert publication.is_dir()
    assert sorted(path.name for path in (publication / "evidence").iterdir()) == ["manifest.json", "plan.json", "validation-report.json"]
    publication_manifest = json.loads((publication / "publication-manifest.json").read_text(encoding="utf-8"))
    assert publication_manifest["included"] == ["manifest.json", "plan.json", "validation-report.json"]
    assert publication_manifest["source_package_included"] is False
    assert not (publication / "source.pscx").exists()
    assert not (tmp_path / ".pscad-mcp" / "blueprint-build.lock").exists()


@pytest.mark.asyncio
async def test_failed_build_is_quarantined_and_never_published(tmp_path):
    source = write_source_package(tmp_path)
    service = BlueprintBuilderService(ServicePscadFake(tmp_path, location_drift=True), workspace_root=tmp_path)
    blueprint = valid_blueprint()
    planned = await service.plan_project(blueprint, str(source), "BuiltCase")

    started = await service.build_project(planned["plan_hash"], blueprint, str(source), "BuiltCase", confirm=True)
    final = await service.wait_for_build(started["build_id"])

    assert final["state"] == "quarantined"
    assert final["published"] is False
    assert final["publication_path"] is None
    assert not (tmp_path / ".pscad-mcp" / "blueprint-publications").exists()


def test_workspace_lease_rejects_concurrent_owner_and_token_mismatch(tmp_path):
    first = WorkspaceBuildLease.acquire(tmp_path, "build-first")
    try:
        with pytest.raises(BackendError) as raised:
            WorkspaceBuildLease.acquire(tmp_path, "build-second")
        assert raised.value.code == "BLUEPRINT_BUILD_CONFLICT"
        assert first.release("wrong-token") is False
        assert first.lock_path.exists()
        assert first.release(first.token) is True
        assert not first.lock_path.exists()
    finally:
        first.release(first.token)


@pytest.mark.asyncio
async def test_validation_accepts_build_id_or_workspace_contained_staging_path(tmp_path):
    source = write_source_package(tmp_path)
    service = BlueprintBuilderService(ServicePscadFake(tmp_path), workspace_root=tmp_path)
    blueprint = valid_blueprint()
    planned = await service.plan_project(blueprint, str(source), "BuiltCase")
    started = await service.build_project(planned["plan_hash"], blueprint, str(source), "BuiltCase", confirm=True)
    final = await service.wait_for_build(started["build_id"])

    by_id = await service.validate_project_build(build_id=started["build_id"])
    by_path = await service.validate_project_build(staging_path=final["staging_path"])

    assert by_id["valid"] is True
    assert by_path["valid"] is True
    assert by_path["plan_hash"] == planned["plan_hash"]


@pytest.mark.asyncio
async def test_validation_rejects_ambiguous_target_and_workspace_escape(tmp_path):
    service = BlueprintBuilderService(ServicePscadFake(tmp_path), workspace_root=tmp_path)
    with pytest.raises(BackendError) as ambiguous:
        await service.validate_project_build()
    assert ambiguous.value.code == "BLUEPRINT_VALIDATION_TARGET_INVALID"

    outside = tmp_path.parent / "outside-blueprint-staging"
    outside.mkdir(exist_ok=True)
    with pytest.raises(BackendError) as escape:
        await service.validate_project_build(staging_path=str(outside))
    assert escape.value.code == "BLUEPRINT_VALIDATION_TARGET_INVALID"
