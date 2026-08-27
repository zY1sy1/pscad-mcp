import asyncio

from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import PscadService
from pscad_mcp.hvdc.service import HvdcDomainService
from pscad_mcp.main import create_server
from pscad_mcp.tools import mmc_tools
from tests.mmc_parametric_fakes import valid_request


EXPECTED_MMC_TOOLS = {
    "audit_mmc_template",
    "derive_mmc_parameters",
    "plan_parametric_mmc_model",
    "build_parametric_mmc_model",
    "get_parametric_mmc_build_status",
    "recommend_mmc_simulation",
    "validate_mmc_model",
}


def test_exact_mmc_tools_are_registered() -> None:
    tools = create_server()._tool_manager.list_tools()
    names = {tool.name for tool in tools}
    assert EXPECTED_MMC_TOOLS <= names
    assert len(names) == 90
    assert not {"plan_mmc_model", "build_mmc_model", "get_mmc_build_status"} & names


def test_build_wrapper_preserves_confirmation_default_and_forwards_hash(monkeypatch) -> None:
    calls = []

    class Service:
        async def build_model(self, request, expected_plan_hash, project_name, folder, **kwargs):
            calls.append((request, expected_plan_hash, project_name, folder, kwargs))
            return {"state": "validated"}

    monkeypatch.setattr(mmc_tools, "_service", lambda: Service())
    result = asyncio.run(
        mmc_tools.build_parametric_mmc_model(
            valid_request(model_fidelity="average_value"),
            "a" * 64,
            "MMC_CASE",
            "D:/workspace",
        )
    )
    assert result == {"state": "validated"}
    assert calls[0][1:] == (
        "a" * 64,
        "MMC_CASE",
        "D:/workspace",
        {"template_path": None, "library_path": None, "confirm": False},
    )


def test_mmc_tools_wires_core_service_through_hvdc_domain_boundary(
    monkeypatch, tmp_path
) -> None:
    core_service = PscadService(
        lambda: object(),
        path_policy=PathPolicy(workspace_root=str(tmp_path)),
    )
    monkeypatch.setattr(mmc_tools.pscad_manager, "_service", core_service)
    monkeypatch.setattr(mmc_tools, "_service_instance", None)
    monkeypatch.setattr(mmc_tools, "_service_backend", None)

    builder = mmc_tools._service()

    assert builder.pscad_service is core_service
    assert isinstance(builder.scenario_service, HvdcDomainService)
    assert builder.scenario_service.backend_service is core_service
