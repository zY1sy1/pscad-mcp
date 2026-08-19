import json
import pytest
from pathlib import Path

import asyncio

from pscad_mcp.main import create_server
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.hvdc.service import HvdcDomainService
from pscad_mcp.hvdc.profiles import list_profiles, load_profile


EXPECTED = {
    "inspect_hvdc_project", "get_hvdc_assets", "get_hvdc_mappings",
    "validate_hvdc_project", "run_hvdc_scenario", "get_hvdc_scenario_status",
    "analyze_hvdc_results", "compare_hvdc_scenarios", "list_hvdc_profiles",
    "register_hvdc_profile",
}


def test_hvdc_tools_are_registered_without_removing_generic_tools():
    names = {tool.name for tool in create_server()._tool_manager.list_tools()}
    assert EXPECTED <= names
    assert len(names) == 73


def test_inspect_hvdc_project_is_json_safe(tmp_path):
    path = tmp_path / "case.pscx"
    path.write_text("<project version='4.6.2'><definitions><Definition name='RectCC'/><Definition name='RectPole'/><Definition name='InverterPole'/></definitions><canvas name='Main'><label>Idc</label></canvas></project>", encoding="utf-8")
    service = HvdcDomainService(path_policy=type("Policy", (), {"resolve": lambda self, candidate, **kwargs: path})())
    result = service.inspect_project(str(path))
    assert result["topology"]["family"] == "lcc"
    assert json.loads(json.dumps(result))


def test_validation_reports_missing_required_assets(tmp_path):
    path = tmp_path / "case.pscx"
    path.write_text("<project><definitions><Definition name='RectCC'/></definitions></project>", encoding="utf-8")
    service = HvdcDomainService(path_policy=type("Policy", (), {"resolve": lambda self, candidate, **kwargs: path})())
    result = service.validate_project(str(path), profile="hvdc_breaker_difforder")
    assert result["valid"] is False
    assert result["missing_assets"]


def test_profile_registration_uses_workspace_path_policy(tmp_path):
    mapping = tmp_path / "custom.json"
    mapping.write_text('{"required_assets": [], "mappings": []}', encoding="utf-8")
    service = HvdcDomainService(path_policy=PathPolicy(workspace_root=str(tmp_path)))
    result = service.register_profile("custom", str(mapping))
    assert result["registered"] is True
    persisted = tmp_path / ".pscad-mcp" / "hvdc-profiles" / "custom.json"
    assert persisted.exists()
    assert load_profile("custom", workspace_root=tmp_path) == {"required_assets": [], "mappings": []}


def test_profile_registration_validates_schema(tmp_path):
    mapping = tmp_path / "invalid.json"
    mapping.write_text('{"required_assets": [], "mappings": [{"aliases": ["Idc"]}]}', encoding="utf-8")
    service = HvdcDomainService(path_policy=PathPolicy(workspace_root=str(tmp_path)))
    with pytest.raises(BackendError) as raised:
        service.register_profile("invalid", str(mapping))
    assert raised.value.code == "INVALID_ARGUMENT"
    assert not (tmp_path / ".pscad-mcp" / "hvdc-profiles" / "invalid.json").exists()


def test_profile_registration_rejects_missing_schema_sections(tmp_path):
    mapping = tmp_path / "empty.json"
    mapping.write_text("{}", encoding="utf-8")
    service = HvdcDomainService(path_policy=PathPolicy(workspace_root=str(tmp_path)))
    with pytest.raises(BackendError) as raised:
        service.register_profile("empty", str(mapping))
    assert raised.value.code == "INVALID_ARGUMENT"


def test_profile_registration_rejects_builtin_overwrite(tmp_path):
    mapping = tmp_path / "replacement.json"
    mapping.write_text('{"required_assets": [], "mappings": []}', encoding="utf-8")
    service = HvdcDomainService(path_policy=PathPolicy(workspace_root=str(tmp_path)))
    with pytest.raises(BackendError) as raised:
        service.register_profile("lcc_bipolar_generic", str(mapping))
    assert raised.value.code == "INVALID_ARGUMENT"


def test_profile_registration_rejects_existing_user_profile_overwrite(tmp_path):
    mapping = tmp_path / "custom.json"
    mapping.write_text('{"required_assets": [], "mappings": []}', encoding="utf-8")
    service = HvdcDomainService(path_policy=PathPolicy(workspace_root=str(tmp_path)))
    registered = service.register_profile("existing", str(mapping))
    persisted = Path(registered["mapping_file"])
    original = persisted.read_bytes()
    mapping.write_text('{"required_assets": ["breaker"], "mappings": []}', encoding="utf-8")
    with pytest.raises(BackendError) as raised:
        service.register_profile("existing", str(mapping))
    assert raised.value.code == "HVDC_PROFILE_ALREADY_EXISTS"
    assert persisted.read_bytes() == original


def test_user_profiles_are_isolated_by_workspace_root(tmp_path):
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    workspace_a.mkdir()
    workspace_b.mkdir()
    mapping = workspace_a / "scope-probe.json"
    mapping.write_text('{"required_assets": [], "mappings": []}', encoding="utf-8")
    service_a = HvdcDomainService(path_policy=PathPolicy(workspace_root=str(workspace_a)))
    service_a.register_profile("scope_probe", str(mapping))

    assert "scope_probe" in list_profiles(workspace_a)
    assert "scope_probe" not in list_profiles(workspace_b)
    with pytest.raises(BackendError) as raised:
        load_profile("scope_probe", workspace_root=workspace_b)
    assert raised.value.code == "HVDC_PROFILE_NOT_FOUND"


def test_profile_load_rejects_traversal_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text('{"required_assets": [], "mappings": []}', encoding="utf-8")

    with pytest.raises(BackendError) as raised:
        load_profile("../../../outside", workspace_root=workspace)

    assert raised.value.code == "INVALID_ARGUMENT"
    assert raised.value.operation == "load_profile"


def test_profile_parent_name_cannot_traverse_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    profile_dir = workspace / ".pscad-mcp" / "hvdc-profiles"
    profile_dir.mkdir(parents=True)
    (tmp_path / "outside.json").write_text('{"required_assets": [], "mappings": []}', encoding="utf-8")
    (profile_dir / "child.json").write_text(
        '{"extends": "../../../outside", "required_assets": [], "mappings": []}',
        encoding="utf-8",
    )

    with pytest.raises(BackendError) as raised:
        load_profile("child", workspace_root=workspace)

    assert raised.value.code == "INVALID_ARGUMENT"
    assert raised.value.operation == "load_profile"


def test_inspection_cache_is_scoped_by_canvas_name(tmp_path):
    path = tmp_path / "case.pscx"
    path.write_text(
        "<project><canvas name='Main'><label>Main signal</label></canvas>"
        "<canvas name='Aux'><label>Aux signal</label></canvas></project>",
        encoding="utf-8",
    )
    service = HvdcDomainService()
    main = service.inspect_project(str(path), canvas_name="Main")
    aux = service.inspect_project(str(path), canvas_name="Aux")
    assert {item["text"] for item in main["evidence"]["labels"]} == {"Main signal"}
    assert {item["text"] for item in aux["evidence"]["labels"]} == {"Aux signal"}


def test_project_inspection_preserves_workspace_error_code():
    from pscad_mcp.core.backend.base import BackendError
    service = HvdcDomainService()
    with pytest.raises(BackendError) as raised:
        service.inspect_project("case.pscx")
    assert raised.value.code in {"WORKSPACE_NOT_CONFIGURED", "NOT_FOUND"}


def test_read_only_inspection_accepts_existing_absolute_pscx_outside_workspace(tmp_path):
    path = tmp_path / "outside.pscx"
    path.write_text("<project><canvas name='Main'><label>Idc</label></canvas></project>", encoding="utf-8")
    service = HvdcDomainService()
    result = service.inspect_project(str(path))
    assert result["project"]["name"] == "outside"


def test_validation_fails_closed_on_mapping_conflicts(tmp_path):
    path = tmp_path / "conflict.pscx"
    path.write_text("<project><definitions><Definition name='RectCC'/><Definition name='RectPole'/><Definition name='InverterPole'/></definitions><canvas name='Main'><label>Idc</label><label>Idc (kV)</label></canvas></project>", encoding="utf-8")
    service = HvdcDomainService()
    result = service.validate_project(str(path), profile="lcc_bipolar_generic")
    assert result["valid"] is False
    assert any(error["code"] == "HVDC_MAPPING_CONFLICT" for error in result["errors"])
