from pathlib import Path
from types import SimpleNamespace

from pscad_mcp.main import create_server
from pscad_mcp.tools import lcc_parametric_tools


def test_parametric_lcc_tools_are_registered():
    names = {tool.name for tool in create_server()._tool_manager.list_tools()}
    expected = {
        "derive_lcc_parameters",
        "audit_lcc_template",
        "plan_parametric_lcc_model",
        "build_parametric_lcc_model",
        "get_parametric_lcc_build_status",
        "validate_lcc_operating_modes",
    }
    assert expected <= names
    assert len(names) == 83


def test_parametric_service_uses_configured_workspace_path_policy(monkeypatch, tmp_path):
    backend = SimpleNamespace(
        path_policy=SimpleNamespace(workspace_root=tmp_path),
    )
    monkeypatch.setattr(lcc_parametric_tools.pscad_manager, "_service", backend)
    monkeypatch.setattr(lcc_parametric_tools, "_service_instance", None)
    monkeypatch.setattr(lcc_parametric_tools, "_service_backend", None)

    service = lcc_parametric_tools._service()

    assert service.pscad_service is backend
    assert service.workspace_root == Path(tmp_path).resolve()


def test_parametric_service_preserves_unconfigured_workspace_as_unavailable(monkeypatch):
    backend = SimpleNamespace(
        path_policy=SimpleNamespace(workspace_root=None),
    )
    monkeypatch.setattr(lcc_parametric_tools.pscad_manager, "_service", backend)
    monkeypatch.setattr(lcc_parametric_tools, "_service_instance", None)
    monkeypatch.setattr(lcc_parametric_tools, "_service_backend", None)

    service = lcc_parametric_tools._service()

    assert service.pscad_service is backend
    assert service.workspace_root is None
