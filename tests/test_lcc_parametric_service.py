import asyncio
import copy
import hashlib
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc import parametric_service
from pscad_mcp.hvdc.builders.lcc.assets import load_parametric_catalog
from pscad_mcp.hvdc.builders.lcc.parametric_models import (
    LccRatings,
    LccTemplateMapping,
    ParametricLccRequest,
)
from pscad_mcp.hvdc.builders.lcc.parametric_service import ParametricLccBuilderService


FIXTURES = Path(__file__).parent / "fixtures" / "lcc_parametric"


def request(topology="bipolar"):
    return ParametricLccRequest(
        topology=topology,
        ratings=LccRatings(1200.0, 500.0, 2.4, 500.0, 50.0, 3.0),
        engineering_overrides={
            "smoothing_reactor_mh": 120.0,
            "filter_capacitance_uf": 60.0,
            "min_firing_angle_deg": 5.0,
            "max_firing_angle_deg": 45.0,
        },
        operation_modes=("bipolar_run",) if topology == "bipolar" else (),
        return_path_assets=("neutral_bus",) if topology == "bipolar" else (),
    )


def _inputs(tmp_path, *, topology="bipolar"):
    workspace = tmp_path / "workspace-must-remain-absent"
    fixture = "bipole_template.pscx" if topology == "bipolar" else "monopole_template.pscx"
    return {
        "request": request(topology),
        "template_path": str((FIXTURES / fixture).resolve()),
        "project_name": "ParametricLcc",
        "folder": str((workspace / "models").resolve()),
        "workspace": workspace,
    }


def _plan(service, values):
    return service.plan_parametric_model(
        values["request"],
        template_path=values["template_path"],
        project_name=values["project_name"],
        folder=values["folder"],
    )


def _build(service, values, plan_hash, *, confirm=True):
    return asyncio.run(
        service.build_parametric_model(
            values["request"],
            template_path=values["template_path"],
            project_name=values["project_name"],
            folder=values["folder"],
            expected_plan_hash=plan_hash,
            confirm=confirm,
        )
    )


def test_plan_binds_template_assets_roles_and_owned_targets_without_writes(tmp_path):
    values = _inputs(tmp_path)
    source = Path(values["template_path"])
    before_bytes = source.read_bytes()
    before_mtime = source.stat().st_mtime_ns
    service = ParametricLccBuilderService(workspace_root=values["workspace"])

    first = _plan(service, values)
    second = _plan(service, values)

    assert first == second
    assert first["status"] == "planned"
    assert len(first["plan_hash"]) == 64
    assert first["template"] == {
        "path": str(source),
        "fingerprint": hashlib.sha256(before_bytes).hexdigest(),
        "roles": first["template"]["roles"],
    }
    assert set(first["template"]["roles"]) == {
        "rectifier_positive_pole", "rectifier_negative_pole",
        "inverter_positive_pole", "inverter_negative_pole", "earth_electrode",
    }
    assert set(first["assets"]) == {"catalog", "provenance", "blueprint"}
    assert all(len(item["sha256"]) == 64 for item in first["assets"].values())
    assert first["project"] == {
        "name": "ParametricLcc",
        "folder": str((values["workspace"] / "models").resolve()),
        "target_path": str((values["workspace"] / "models" / "ParametricLcc.pscx").resolve()),
        "staging_path": str((values["workspace"] / ".pscad-mcp" / "lcc-builds" / "ParametricLcc.staging.pscx").resolve()),
    }
    assert source.read_bytes() == before_bytes
    assert source.stat().st_mtime_ns == before_mtime
    assert not values["workspace"].exists()


@pytest.mark.parametrize(
    ("topology", "fixture"),
    [("bipolar", "monopole_template.pscx"), ("monopolar", "bipole_template.pscx")],
)
def test_plan_rejects_template_whose_audited_roles_do_not_match_topology(tmp_path, topology, fixture):
    values = _inputs(tmp_path, topology=topology)
    values["template_path"] = str((FIXTURES / fixture).resolve())
    service = ParametricLccBuilderService(workspace_root=values["workspace"])
    with pytest.raises(BackendError) as raised:
        _plan(service, values)
    assert raised.value.code == "LCC_TEMPLATE_TOPOLOGY_MISMATCH"
    assert raised.value.details == {"topology": topology, "reason": "required_roles_missing"}
    assert not values["workspace"].exists()


def test_plan_rejects_incompatible_template_without_writes(tmp_path):
    values = _inputs(tmp_path)
    values["template_path"] = str((FIXTURES / "incompatible_template.pscx").resolve())
    service = ParametricLccBuilderService(workspace_root=values["workspace"])
    with pytest.raises(BackendError) as raised:
        _plan(service, values)
    assert raised.value.code == "LCC_TEMPLATE_INCOMPATIBLE"
    assert raised.value.details["reason"] == "audit_not_compatible"
    assert isinstance(raised.value.details["missing_contracts"], list)
    assert not values["workspace"].exists()


@pytest.mark.parametrize("project_name", ["../escape", "bad/name", "bad\\name", ".", "9starts_wrong", "x" * 65])
def test_plan_rejects_unsafe_project_name(tmp_path, project_name):
    values = _inputs(tmp_path)
    values["project_name"] = project_name
    service = ParametricLccBuilderService(workspace_root=values["workspace"])
    with pytest.raises(BackendError) as raised:
        _plan(service, values)
    assert raised.value.code == "LCC_LAYOUT_INVALID"
    assert raised.value.details == {"field": "project_name", "reason": "unsafe_project_name"}
    assert project_name not in str(raised.value.details)


@pytest.mark.parametrize(
    "project_name",
    ["CON", "con", "PrN", "AUX", "nul", "COM1", "com9", "LPT1", "lpt9"],
)
def test_plan_rejects_windows_reserved_device_project_names(tmp_path, project_name):
    values = _inputs(tmp_path)
    values["project_name"] = project_name
    service = ParametricLccBuilderService(workspace_root=values["workspace"])
    with pytest.raises(BackendError) as raised:
        _plan(service, values)
    assert raised.value.code == "LCC_LAYOUT_INVALID"
    assert raised.value.details == {
        "field": "project_name",
        "reason": "reserved_project_name",
    }


def test_plan_requires_absolute_existing_pscx_source_and_absolute_owned_folder(tmp_path):
    values = _inputs(tmp_path)
    service = ParametricLccBuilderService(workspace_root=values["workspace"])
    for field, bad_value, reason in (
        ("template_path", "relative.pscx", "template_path_not_absolute"),
        ("template_path", str((tmp_path / "missing.pscx").resolve()), "template_not_found"),
        ("template_path", str((tmp_path / "template.txt").resolve()), "template_suffix_invalid"),
        ("folder", "relative-folder", "folder_not_absolute"),
        ("folder", str((tmp_path / "outside").resolve()), "folder_outside_workspace"),
    ):
        candidate = dict(values)
        candidate[field] = bad_value
        with pytest.raises(BackendError) as raised:
            _plan(service, candidate)
        assert raised.value.code in {"LCC_TEMPLATE_INCOMPATIBLE", "LCC_LAYOUT_INVALID"}
        assert raised.value.details["reason"] == reason
    assert not values["workspace"].exists()


def test_plan_fails_closed_without_configured_workspace(tmp_path):
    values = _inputs(tmp_path)
    service = ParametricLccBuilderService()
    with pytest.raises(BackendError) as raised:
        _plan(service, values)
    assert raised.value.code == "LCC_LAYOUT_INVALID"
    assert raised.value.details == {"reason": "workspace_not_configured"}


def test_plan_rejects_workspace_root_that_is_an_existing_file(tmp_path):
    workspace_file = tmp_path / "workspace-file"
    workspace_file.write_text("not a directory", encoding="utf-8")
    values = _inputs(tmp_path)
    service = ParametricLccBuilderService(workspace_root=workspace_file)
    with pytest.raises(BackendError) as raised:
        _plan(service, values)
    assert raised.value.code == "LCC_LAYOUT_INVALID"
    assert raised.value.details == {"reason": "workspace_not_directory"}


def test_plan_rejects_existing_final_target(tmp_path):
    values = _inputs(tmp_path)
    target = Path(values["folder"]) / "ParametricLcc.pscx"
    target.parent.mkdir(parents=True)
    target.write_text("occupied", encoding="utf-8")
    service = ParametricLccBuilderService(workspace_root=values["workspace"])
    with pytest.raises(BackendError) as raised:
        _plan(service, values)
    assert raised.value.code == "LCC_BUILD_CONFLICT"
    assert raised.value.details == {"reason": "final_target_exists"}


def test_missing_public_plan_arguments_fail_closed_instead_of_returning_shell_plan(tmp_path):
    service = ParametricLccBuilderService(workspace_root=tmp_path)
    with pytest.raises(BackendError) as raised:
        service.plan_parametric_model(request())
    assert raised.value.code == "LCC_PLAN_INPUT_REQUIRED"
    assert raised.value.details == {"missing": ["template_path", "project_name", "folder"]}


def test_build_requires_confirmation_before_plan_and_configuration_checks(tmp_path):
    values = _inputs(tmp_path)
    service = ParametricLccBuilderService()
    with pytest.raises(BackendError) as raised:
        _build(service, values, "wrong", confirm=False)
    assert raised.value.code == "CONFIRMATION_REQUIRED"
    assert service._statuses == {}
    assert not values["workspace"].exists()


@pytest.mark.parametrize(
    "expected_plan_hash",
    [None, 1, "", "a" * 63, "a" * 65, "A" * 64, "g" * 64, "é" * 64, "a" * 10000],
)
def test_build_rejects_invalid_expected_hash_before_template_or_asset_revalidation(
    tmp_path, monkeypatch, expected_plan_hash
):
    values = _inputs(tmp_path)
    service = ParametricLccBuilderService(pscad_service=object(), workspace_root=values["workspace"])

    def must_not_revalidate(*args, **kwargs):
        raise AssertionError("template/assets must not be read for an invalid expected hash")

    monkeypatch.setattr(service, "_compose_plan", must_not_revalidate)
    with pytest.raises(BackendError) as raised:
        _build(service, values, expected_plan_hash)
    assert raised.value.code == "LCC_PLAN_STALE"
    assert raised.value.details == {"reason": "invalid_expected_plan_hash"}
    assert len(str(raised.value.details)) < 128
    assert not values["workspace"].exists()


def test_build_rejects_stale_source_before_any_workspace_write(tmp_path):
    values = _inputs(tmp_path)
    source = tmp_path / "source" / "bipole.pscx"
    source.parent.mkdir()
    source.write_bytes((FIXTURES / "bipole_template.pscx").read_bytes())
    values["template_path"] = str(source.resolve())
    service = ParametricLccBuilderService(pscad_service=object(), workspace_root=values["workspace"])
    plan = _plan(service, values)
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(BackendError) as raised:
        _build(service, values, plan["plan_hash"])
    assert raised.value.code == "LCC_PLAN_STALE"
    assert raised.value.details["reason"] == "source_changed"
    assert service._statuses == {}
    assert not values["workspace"].exists()


@pytest.mark.parametrize("change", ["incompatible", "unreadable"])
def test_build_normalizes_template_reaudit_failures_to_stale_before_writes(tmp_path, change):
    values = _inputs(tmp_path)
    source = tmp_path / "source" / "bipole.pscx"
    source.parent.mkdir()
    source.write_bytes((FIXTURES / "bipole_template.pscx").read_bytes())
    values["template_path"] = str(source.resolve())
    service = ParametricLccBuilderService(pscad_service=object(), workspace_root=values["workspace"])
    plan = _plan(service, values)
    if change == "incompatible":
        payload = source.read_text(encoding="utf-8")
        source.write_text(
            payload.replace("FixtureBipole:RectPole", "foreign:RectPole"),
            encoding="utf-8",
        )
    else:
        source.unlink()

    with pytest.raises(BackendError) as raised:
        _build(service, values, plan["plan_hash"])

    assert raised.value.code == "LCC_PLAN_STALE"
    assert raised.value.details == {"reason": "source_changed"}
    assert service._statuses == {}
    assert not values["workspace"].exists()


def test_build_rejects_stale_asset_snapshot_before_any_workspace_write(tmp_path, monkeypatch):
    values = _inputs(tmp_path)
    service = ParametricLccBuilderService(pscad_service=object(), workspace_root=values["workspace"])
    plan = _plan(service, values)
    original = parametric_service._load_parametric_asset_snapshot

    def changed(topology, catalog_override=None):
        snapshot = copy.deepcopy(original(topology, catalog_override))
        snapshot["evidence"]["blueprint"]["sha256"] = "f" * 64
        return snapshot

    monkeypatch.setattr(parametric_service, "_load_parametric_asset_snapshot", changed)
    with pytest.raises(BackendError) as raised:
        _build(service, values, plan["plan_hash"])
    assert raised.value.code == "LCC_PLAN_STALE"
    assert raised.value.details == {"reason": "asset_changed"}
    assert service._statuses == {}
    assert not values["workspace"].exists()


def test_build_normalizes_damaged_packaged_asset_to_stale_before_writes(tmp_path, monkeypatch):
    values = _inputs(tmp_path)
    service = ParametricLccBuilderService(pscad_service=object(), workspace_root=values["workspace"])
    plan = _plan(service, values)
    original = parametric_service._asset_json

    def damaged(relative):
        if relative[-1] == "blueprint.json":
            raise BackendError(
                "LCC_ASSET_MISMATCH",
                "damaged",
                "hvdc",
                "plan_parametric_lcc_model",
                {"unbounded": "x" * 10000},
            )
        return original(relative)

    monkeypatch.setattr(parametric_service, "_asset_json", damaged)
    with pytest.raises(BackendError) as raised:
        _build(service, values, plan["plan_hash"])
    assert raised.value.code == "LCC_PLAN_STALE"
    assert raised.value.details == {"reason": "asset_changed"}
    assert len(str(raised.value.details)) < 128
    assert service._statuses == {}
    assert not values["workspace"].exists()


@pytest.mark.parametrize("damage", ["non_json", "oversized"])
def test_build_normalizes_injected_catalog_canonicalization_failure_to_asset_stale(
    tmp_path, damage
):
    values = _inputs(tmp_path)
    catalog = copy.deepcopy(load_parametric_catalog())
    service = ParametricLccBuilderService(
        pscad_service=object(), workspace_root=values["workspace"], catalog=catalog
    )
    plan = _plan(service, values)
    catalog["post_plan_damage"] = object() if damage == "non_json" else "x" * 300_000

    with pytest.raises(BackendError) as raised:
        _build(service, values, plan["plan_hash"])
    assert raised.value.code == "LCC_PLAN_STALE"
    assert raised.value.details == {"reason": "asset_changed"}
    assert service._statuses == {}
    assert not values["workspace"].exists()


@pytest.mark.parametrize("damage", ["non_json", "oversized"])
def test_plan_reports_injected_catalog_canonicalization_as_asset_mismatch(tmp_path, damage):
    values = _inputs(tmp_path)
    catalog = copy.deepcopy(load_parametric_catalog())
    catalog["invalid_catalog_payload"] = object() if damage == "non_json" else "x" * 300_000
    service = ParametricLccBuilderService(workspace_root=values["workspace"], catalog=catalog)

    with pytest.raises(BackendError) as raised:
        _plan(service, values)

    assert raised.value.code == "LCC_ASSET_MISMATCH"
    assert raised.value.details == {"reason": "catalog_canonicalization_invalid"}


def test_build_preserves_oversized_request_as_plan_invalid_not_asset_stale(tmp_path):
    values = _inputs(tmp_path)
    service = ParametricLccBuilderService(pscad_service=object(), workspace_root=values["workspace"])
    plan = _plan(service, values)
    values["request"] = replace(
        values["request"],
        template_mappings=(
            LccTemplateMapping(
                role="evidence",
                definition="FixtureBipole:RectPole",
                source="x" * 300_000,
            ),
        ),
    )

    with pytest.raises(BackendError) as raised:
        _build(service, values, plan["plan_hash"])

    assert raised.value.code == "LCC_PLAN_INVALID"
    assert raised.value.details["reason"] == "plan_too_large"
    assert raised.value.details["max_bytes"] == parametric_service._PLAN_MAX_BYTES
    assert "x" * 100 not in str(raised.value.details)
    assert service._statuses == {}
    assert not values["workspace"].exists()


@pytest.mark.parametrize(
    ("filename", "field", "bad_value"),
    [
        ("lcc_parametric_catalog_v1.json", "schema_version", 99),
        ("lcc_parametric_catalog_v1.json", "schema_version", True),
        ("provenance-parametric-v1.json", "schema_version", 99),
        ("provenance-parametric-v1.json", "schema_version", True),
    ],
)
def test_plan_rejects_asset_schema_drift_with_specific_error(
    tmp_path, monkeypatch, filename, field, bad_value
):
    values = _inputs(tmp_path)
    service = ParametricLccBuilderService(workspace_root=values["workspace"])
    original = parametric_service._asset_json

    def malformed(relative):
        value, digest = original(relative)
        if relative[-1] == filename:
            value = copy.deepcopy(value)
            value[field] = bad_value
        return value, digest

    monkeypatch.setattr(parametric_service, "_asset_json", malformed)
    with pytest.raises(BackendError) as raised:
        _plan(service, values)
    assert raised.value.code == "LCC_ASSET_MISMATCH"
    assert raised.value.details == {"reason": "asset_identity_mismatch"}


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("schema_version", 99),
        ("topology", "not-lcc"),
        ("poles", 99),
        ("poles", True),
        ("terminals", 99),
        ("required_assets", ["positive_pole"]),
        ("return_paths", ["earth_return"]),
    ],
)
def test_plan_rejects_named_blueprint_with_malformed_authoritative_contract(
    tmp_path, monkeypatch, field, bad_value
):
    values = _inputs(tmp_path)
    service = ParametricLccBuilderService(workspace_root=values["workspace"])
    original = parametric_service._asset_json

    def malformed(relative):
        value, digest = original(relative)
        if relative[-1] == "blueprint.json":
            value = copy.deepcopy(value)
            value[field] = bad_value
        return value, digest

    monkeypatch.setattr(parametric_service, "_asset_json", malformed)
    with pytest.raises(BackendError) as raised:
        _plan(service, values)
    assert raised.value.code == "LCC_BLUEPRINT_INVALID"
    assert raised.value.details == {
        "field": field,
        "reason": "blueprint_contract_mismatch",
    }
    assert not values["workspace"].exists()


def test_build_normalizes_malformed_blueprint_contract_to_stale(tmp_path, monkeypatch):
    values = _inputs(tmp_path)
    service = ParametricLccBuilderService(pscad_service=object(), workspace_root=values["workspace"])
    plan = _plan(service, values)
    original = parametric_service._asset_json

    def malformed(relative):
        value, digest = original(relative)
        if relative[-1] == "blueprint.json":
            value = copy.deepcopy(value)
            value["terminals"] = 99
        return value, digest

    monkeypatch.setattr(parametric_service, "_asset_json", malformed)
    with pytest.raises(BackendError) as raised:
        _build(service, values, plan["plan_hash"])
    assert raised.value.code == "LCC_PLAN_STALE"
    assert raised.value.details == {"reason": "asset_changed"}
    assert service._statuses == {}
    assert not values["workspace"].exists()


def test_monopolar_blueprint_contract_rejects_boolean_pole_count(tmp_path, monkeypatch):
    values = _inputs(tmp_path, topology="monopolar")
    service = ParametricLccBuilderService(workspace_root=values["workspace"])
    original = parametric_service._asset_json

    def malformed(relative):
        value, digest = original(relative)
        if relative[-1] == "blueprint.json":
            value = copy.deepcopy(value)
            value["poles"] = True
        return value, digest

    monkeypatch.setattr(parametric_service, "_asset_json", malformed)
    with pytest.raises(BackendError) as raised:
        _plan(service, values)
    assert raised.value.code == "LCC_BLUEPRINT_INVALID"
    assert raised.value.details["field"] == "poles"


def test_build_checks_staleness_before_final_target_conflict(tmp_path):
    values = _inputs(tmp_path)
    service = ParametricLccBuilderService(pscad_service=object(), workspace_root=values["workspace"])
    plan = _plan(service, values)
    target = Path(plan["project"]["target_path"])
    target.parent.mkdir(parents=True)
    target.write_text("occupied", encoding="utf-8")
    with pytest.raises(BackendError) as raised:
        _build(service, values, "0" * 64)
    assert raised.value.code == "LCC_PLAN_STALE"
    assert not Path(plan["project"]["staging_path"]).exists()


def test_build_rejects_target_created_after_plan_before_staging(tmp_path):
    values = _inputs(tmp_path)
    service = ParametricLccBuilderService(pscad_service=object(), workspace_root=values["workspace"])
    plan = _plan(service, values)
    target = Path(plan["project"]["target_path"])
    target.parent.mkdir(parents=True)
    target.write_text("occupied", encoding="utf-8")
    with pytest.raises(BackendError) as raised:
        _build(service, values, plan["plan_hash"])
    assert raised.value.code == "LCC_BUILD_CONFLICT"
    assert raised.value.details == {"reason": "final_target_exists"}
    assert not Path(plan["project"]["staging_path"]).exists()


@pytest.mark.parametrize("pscad_service", [None, object()])
def test_build_fails_explicitly_when_real_executor_is_not_connected(tmp_path, pscad_service):
    values = _inputs(tmp_path)
    service = ParametricLccBuilderService(pscad_service=pscad_service, workspace_root=values["workspace"])
    plan = _plan(service, values)
    with pytest.raises(BackendError) as raised:
        _build(service, values, plan["plan_hash"])
    assert raised.value.code == "LCC_BUILD_UNAVAILABLE"
    assert raised.value.details["reason"] in {"lifecycle_configuration_missing", "real_lifecycle_not_implemented"}
    assert service._statuses == {}
    assert not values["workspace"].exists()


def test_build_with_configured_executor_stages_template_and_tracks_status(tmp_path):
    values = _inputs(tmp_path)
    calls = {}

    async def fake_executor(plan, pscad_service, workspace_root, *, build_id, journal):
        calls["pscad_service"] = pscad_service
        calls["workspace_root"] = Path(workspace_root)
        staging = Path(plan["project"]["staging_path"])
        staging.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(plan["template"]["path"], staging)
        record = {
            "build_id": build_id,
            "state": "published",
            "plan_hash": plan["plan_hash"],
            "target_path": plan["project"]["target_path"],
            "staging_path": str(staging),
            "result": {"staged_sha256": hashlib.sha256(staging.read_bytes()).hexdigest()},
        }
        journal.write(record)
        return record

    pscad_service = object()
    service = ParametricLccBuilderService(
        pscad_service=pscad_service,
        workspace_root=values["workspace"],
        executor_factory=fake_executor,
    )
    plan = _plan(service, values)

    async def scenario():
        started = await service.build_parametric_model(
            values["request"],
            template_path=values["template_path"],
            project_name=values["project_name"],
            folder=values["folder"],
            expected_plan_hash=plan["plan_hash"],
            confirm=True,
        )
        assert started["state"] == "validated"
        for _ in range(20):
            status = service.get_status(started["build_id"])
            if status["state"] == "published":
                return started, status
            await asyncio.sleep(0)
        return started, service.get_status(started["build_id"])

    started, status = asyncio.run(scenario())
    build_id = started["build_id"]
    assert status["state"] == "published"
    assert Path(status["staging_path"]).is_file()
    assert status["result"]["staged_sha256"] == hashlib.sha256(
        Path(status["staging_path"]).read_bytes()
    ).hexdigest()
    assert calls["pscad_service"] is pscad_service
    assert calls["workspace_root"] == values["workspace"].resolve()


def test_configured_executor_failure_is_contained_and_releases_lease(tmp_path):
    values = _inputs(tmp_path)

    async def failing_executor(plan, pscad_service, workspace_root, *, build_id, journal):
        raise RuntimeError("executor unavailable")

    service = ParametricLccBuilderService(
        pscad_service=object(),
        workspace_root=values["workspace"],
        executor_factory=failing_executor,
    )
    plan = _plan(service, values)

    async def scenario():
        started = await service.build_parametric_model(
            values["request"],
            template_path=values["template_path"],
            project_name=values["project_name"],
            folder=values["folder"],
            expected_plan_hash=plan["plan_hash"],
            confirm=True,
        )
        for _ in range(20):
            status = service.get_status(started["build_id"])
            if status["state"] == "failed":
                return status
            await asyncio.sleep(0)
        return service.get_status(started["build_id"])

    status = asyncio.run(scenario())

    assert status["state"] == "failed"
    assert status["error"]["code"] == "LCC_BUILD_FAILED"
    assert not (values["workspace"] / ".pscad-mcp" / "lcc-build.lock").exists()
