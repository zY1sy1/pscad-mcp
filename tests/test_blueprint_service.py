from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from blueprint_builder_fakes import RecordingBlueprintPscadService
from pscad_mcp.builders.blueprint import journal as journal_module
from pscad_mcp.builders.blueprint.executor import execute_build
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
async def test_planning_loads_declared_companion_libraries_with_source_entry_point(tmp_path):
    source = write_source_package(tmp_path)
    (source / "BreakerArc.pslx").write_text("<library/>", encoding="utf-8")
    blueprint = valid_blueprint()
    blueprint["source_package"]["required"].append({"path": "BreakerArc.pslx", "kind": "file"})
    backend = ServicePscadFake(tmp_path)
    service = BlueprintBuilderService(backend, workspace_root=tmp_path)

    await service.plan_project(blueprint, str(source), "BuiltCase")

    load = next(call for call in backend.calls if call[0] == "load_projects")
    assert [Path(path).name for path in load[1][0]] == ["source.pscx", "BreakerArc.pslx"]


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


@pytest.mark.asyncio
async def test_rejected_physical_publication_is_quarantined(tmp_path):
    source = write_source_package(tmp_path)
    service = BlueprintBuilderService(ServicePscadFake(tmp_path), workspace_root=tmp_path)
    blueprint = valid_blueprint()
    blueprint["publication"]["scope"] = "physical_and_model"
    planned = await service.plan_project(blueprint, str(source), "BuiltCase")

    started = await service.build_project(planned["plan_hash"], blueprint, str(source), "BuiltCase", confirm=True)
    final = await service.wait_for_build(started["build_id"])

    assert final["state"] == "quarantined"
    assert final["error"]["code"] == "BLUEPRINT_PUBLICATION_REJECTED"
    assert "quarantine" in final["staging_path"]
    assert final["published"] is False


@pytest.mark.asyncio
async def test_publication_copy_failure_leaves_no_visible_partial_package(tmp_path, monkeypatch):
    source = write_source_package(tmp_path)
    service = BlueprintBuilderService(ServicePscadFake(tmp_path), workspace_root=tmp_path)
    blueprint = valid_blueprint()
    planned = await service.plan_project(blueprint, str(source), "BuiltCase")

    def fail_copy(source_path, destination_path):
        raise OSError("injected publication copy failure")

    monkeypatch.setattr("pscad_mcp.builders.blueprint.service.shutil.copy2", fail_copy)
    started = await service.build_project(planned["plan_hash"], blueprint, str(source), "BuiltCase", confirm=True)
    final = await service.wait_for_build(started["build_id"])

    publication_root = tmp_path / ".pscad-mcp" / "blueprint-publications"
    assert final["state"] == "quarantined"
    assert not publication_root.exists() or list(publication_root.iterdir()) == []


@pytest.mark.asyncio
async def test_publication_journal_failure_removes_atomically_visible_package(tmp_path, monkeypatch):
    source = write_source_package(tmp_path)
    service = BlueprintBuilderService(ServicePscadFake(tmp_path), workspace_root=tmp_path)
    blueprint = valid_blueprint()
    planned = await service.plan_project(blueprint, str(source), "BuiltCase")
    original_journal = journal_module.BuildJournal

    class FailingPublicationJournal(original_journal):
        def append(self, event, payload):
            if event == "state" and payload.get("state") == "published":
                raise OSError("injected publication journal failure")
            return super().append(event, payload)

    monkeypatch.setattr("pscad_mcp.builders.blueprint.service.BuildJournal", FailingPublicationJournal)
    started = await service.build_project(planned["plan_hash"], blueprint, str(source), "BuiltCase", confirm=True)
    final = await service.wait_for_build(started["build_id"])

    publication_root = tmp_path / ".pscad-mcp" / "blueprint-publications"
    assert final["state"] == "quarantined"
    assert not publication_root.exists() or list(publication_root.iterdir()) == []


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


def test_workspace_lease_release_preserves_replacement_owner(tmp_path):
    first = WorkspaceBuildLease.acquire(tmp_path, "build-first")
    replacement = {
        "build_id": "build-replacement",
        "pid": 12345,
        "token": "replacement-token",
        "created_at_utc": "2026-08-27T00:00:00Z",
    }
    replacement_path = first.lock_path.with_name("blueprint-build.lock.replacement")
    replacement_path.write_text(json.dumps(replacement), encoding="utf-8")
    replacement_path.replace(first.lock_path)

    assert first.release() is False
    assert json.loads(first.lock_path.read_text(encoding="utf-8")) == replacement


def test_workspace_lease_release_does_not_depend_on_hard_links(tmp_path, monkeypatch):
    lease = WorkspaceBuildLease.acquire(tmp_path, "build-no-hardlinks")
    monkeypatch.setattr(journal_module.os, "link", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("unsupported")))

    assert lease.release() is True
    assert not lease.lock_path.exists()


@pytest.mark.asyncio
async def test_build_rejects_linked_workspace_control_root_before_external_write(tmp_path):
    source = write_source_package(tmp_path)
    service = BlueprintBuilderService(ServicePscadFake(tmp_path), workspace_root=tmp_path)
    blueprint = valid_blueprint()
    planned = await service.plan_project(blueprint, str(source), "BuiltCase")
    outside = tmp_path.parent / f"{tmp_path.name}-outside-control"
    outside.mkdir()
    try:
        (tmp_path / ".pscad-mcp").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(BackendError) as raised:
        await service.build_project(planned["plan_hash"], blueprint, str(source), "BuiltCase", confirm=True)

    assert raised.value.code == "BLUEPRINT_BUILD_CONFLICT"
    assert list(outside.iterdir()) == []


@pytest.mark.asyncio
async def test_publication_rejects_linked_root_without_external_write(tmp_path):
    source = write_source_package(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside-publication"
    outside.mkdir()
    probe = tmp_path / "publication-link-probe"
    try:
        probe.symlink_to(outside, target_is_directory=True)
        probe.unlink()
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    async def executor_with_link(*args, **kwargs):
        record = await execute_build(*args, **kwargs)
        publication_root = tmp_path / ".pscad-mcp" / "blueprint-publications"
        publication_root.symlink_to(outside, target_is_directory=True)
        return record

    service = BlueprintBuilderService(
        ServicePscadFake(tmp_path),
        workspace_root=tmp_path,
        executor_factory=executor_with_link,
    )
    blueprint = valid_blueprint()
    planned = await service.plan_project(blueprint, str(source), "BuiltCase")
    started = await service.build_project(planned["plan_hash"], blueprint, str(source), "BuiltCase", confirm=True)
    final = await service.wait_for_build(started["build_id"])

    assert final["state"] == "quarantined"
    assert final["error"]["code"] == "BLUEPRINT_PUBLICATION_REJECTED"
    assert list(outside.iterdir()) == []


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


@pytest.mark.asyncio
async def test_standalone_validation_fails_closed_without_message_evidence(tmp_path):
    source = write_source_package(tmp_path)
    backend = ServicePscadFake(tmp_path)
    service = BlueprintBuilderService(backend, workspace_root=tmp_path)
    blueprint = valid_blueprint()
    planned = await service.plan_project(blueprint, str(source), "BuiltCase")
    started = await service.build_project(planned["plan_hash"], blueprint, str(source), "BuiltCase", confirm=True)
    await service.wait_for_build(started["build_id"])
    backend.fail_on = "get_project_output"

    report = await service.validate_project_build(build_id=started["build_id"])

    assert report["message_evidence_available"] is False
    assert report["messages_acceptance"] is False
    assert report["valid"] is False
