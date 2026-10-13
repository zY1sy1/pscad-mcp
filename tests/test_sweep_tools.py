from types import SimpleNamespace

import pytest

from pscad_mcp.main import create_server
from pscad_mcp.tools import sweep_tools
from pscad_mcp.tools.catalog import TOOL_GROUPS
from tests.test_sweep_workflow import campaign as _campaign_fixture

campaign = _campaign_fixture


def test_sweep_profile_exposes_the_complete_workflow_and_exact_plan_gate():
    server = create_server(environ={"PSCAD_MCP_TOOL_PROFILE": "sweep"})
    names = {tool.name for tool in server._tool_manager.list_tools()}
    assert names == TOOL_GROUPS["sweep"] | {"get_pscad_capabilities"}
    create = server._tool_manager.get_tool("create_parameter_sweep")
    assert set(create.parameters["required"]) == {"spec", "expected_plan_hash"}
    assert create.parameters["properties"]["confirm"]["default"] is False


@pytest.mark.asyncio
async def test_registered_tools_run_the_full_sweep_and_serialize_confirmation_errors(
    campaign, monkeypatch
):
    service, spec, sessions, _ = campaign
    monkeypatch.setattr(
        sweep_tools,
        "pscad_manager",
        SimpleNamespace(service=SimpleNamespace(path_policy=service.path_policy)),
    )
    monkeypatch.setattr(sweep_tools, "_sweep_service", service)
    monkeypatch.setattr(sweep_tools, "_policy", service.path_policy)
    server = create_server(environ={"PSCAD_MCP_TOOL_PROFILE": "sweep"})
    tools = server._tool_manager
    plan = await tools.get_tool("plan_parameter_sweep").fn(spec)
    error = await tools.get_tool("create_parameter_sweep").fn(spec, plan["plan_hash"])
    assert error["error"]["code"] == "CONFIRMATION_REQUIRED"
    created = await tools.get_tool("create_parameter_sweep").fn(
        spec, plan["plan_hash"], confirm=True
    )
    cid = created["campaign_id"]
    await tools.get_tool("run_parameter_sweep").fn(cid, confirm=True)
    await service.wait(cid, timeout=5)
    status = await tools.get_tool("get_parameter_sweep_status").fn(
        cid, include_report=True, offset=1, limit=1
    )
    assert status["state"] == "completed"
    assert [s["name"] for s in status["report"]["scenarios"]] == ["double"]
    result = await tools.get_tool("analyze_parameter_sweep").fn(cid)
    assert result["evaluated_count"] == 3
    assert all(s.closed for s in sessions)


@pytest.mark.asyncio
async def test_domain_shutdown_cancels_and_cleans_the_sweep(campaign, monkeypatch):
    service, spec, sessions, _ = campaign
    from tests.test_sweep_workflow import FakeSession, create

    service.session_factory = lambda: FakeSession(sessions, hold=True)
    monkeypatch.setattr(sweep_tools, "_sweep_service", service)
    cid = create(service, spec)
    await service.start(cid, confirm=True)
    await sweep_tools.shutdown_sweep_service(timeout_s=3)
    assert service.status(cid)["state"] == "cancelled"
    assert all(s.closed for s in sessions)
    assert sweep_tools._sweep_service is None
