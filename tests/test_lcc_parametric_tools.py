import asyncio
from pathlib import Path
from types import SimpleNamespace

from pscad_mcp.main import create_server
from pscad_mcp.tools import lcc_parametric_tools


def test_parametric_lcc_tools_are_registered():
    tools = create_server()._tool_manager.list_tools()
    names = {tool.name for tool in tools}
    expected = {
        "derive_lcc_parameters",
        "audit_lcc_template",
        "plan_parametric_lcc_model",
        "build_parametric_lcc_model",
        "get_parametric_lcc_build_status",
        "validate_lcc_operating_modes",
    }
    assert expected <= names
    assert len(names) == 85
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name["plan_parametric_lcc_model"].parameters["required"]) == {
        "request", "template_path", "project_name", "folder",
    }
    assert set(by_name["build_parametric_lcc_model"].parameters["required"]) == {
        "request", "expected_plan_hash", "template_path", "project_name", "folder",
    }
    for tool_name in ("plan_parametric_lcc_model", "build_parametric_lcc_model"):
        properties = by_name[tool_name].parameters["properties"]
        for field in ("template_path", "project_name", "folder"):
            assert properties[field]["type"] == "string"
            assert "default" not in properties[field]


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


def _public_request():
    return {
        "topology": "bipolar",
        "ratings": {
            "rated_power_mw": 1, "dc_voltage_kv": 1, "dc_current_ka": 1,
            "ac_voltage_kv": 1, "frequency_hz": 50, "scr": 1,
        },
        "engineering_overrides": {
            "smoothing_reactor_mh": 1, "filter_capacitance_uf": 1,
            "min_firing_angle_deg": 5, "max_firing_angle_deg": 45,
        },
        "return_path_assets": ["neutral_bus"],
    }


def test_plan_wrapper_forwards_template_and_owned_target_arguments(monkeypatch):
    calls = []

    class Service:
        def plan_parametric_model(self, request, **kwargs):
            calls.append((request, kwargs))
            return {"plan_hash": "ok"}

    monkeypatch.setattr(lcc_parametric_tools, "_service", lambda: Service())
    result = asyncio.run(
        lcc_parametric_tools.plan_parametric_lcc_model(
            _public_request(),
            template_path="D:/templates/source.pscx",
            project_name="Case",
            folder="D:/workspace/models",
        )
    )
    assert result == {"plan_hash": "ok"}
    assert calls[0][1] == {
        "template_path": "D:/templates/source.pscx",
        "project_name": "Case",
        "folder": "D:/workspace/models",
    }


def test_build_wrapper_forwards_same_plan_inputs(monkeypatch):
    calls = []

    class Service:
        async def build_parametric_model(self, request, **kwargs):
            calls.append((request, kwargs))
            return {"status": "accepted"}

    monkeypatch.setattr(lcc_parametric_tools, "_service", lambda: Service())
    result = asyncio.run(
        lcc_parametric_tools.build_parametric_lcc_model(
            _public_request(),
            template_path="D:/templates/source.pscx",
            project_name="Case",
            folder="D:/workspace/models",
            expected_plan_hash="abc",
            confirm=True,
        )
    )
    assert result == {"status": "accepted"}
    assert calls[0][1] == {
        "template_path": "D:/templates/source.pscx",
        "project_name": "Case",
        "folder": "D:/workspace/models",
        "expected_plan_hash": "abc",
        "confirm": True,
    }
