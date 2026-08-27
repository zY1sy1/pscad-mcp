from unittest.mock import AsyncMock, patch

import pytest

from pscad_mcp.main import create_server
from pscad_mcp.tools import topology_tools


@pytest.mark.asyncio
async def test_inspect_tool_routes_only_to_topology_service():
    with patch.object(topology_tools, "pscad_manager") as manager:
        expected = {"project_name": "case", "topology_hash": "a" * 64}
        manager.service.topology_service.inspect_payload = AsyncMock(
            return_value=expected
        )
        result = await topology_tools.inspect_project_topology(
            "case", "Main", "conservative"
        )
    assert result == expected
    manager.service.topology_service.inspect_payload.assert_awaited_once_with(
        "case", "Main", mode="conservative"
    )


@pytest.mark.asyncio
async def test_diagnose_tool_routes_ruleset_and_mode():
    with patch.object(topology_tools, "pscad_manager") as manager:
        manager.service.topology_service.diagnose_payload = AsyncMock(
            return_value={"valid": False}
        )
        result = await topology_tools.diagnose_project_topology(
            "case", "Main", "generic", "infer"
        )
    assert result == {"valid": False}
    manager.service.topology_service.diagnose_payload.assert_awaited_once_with(
        "case", "Main", ruleset="generic", mode="infer"
    )


def test_topology_tools_are_registered_exactly_once():
    names = {tool.name for tool in create_server()._tool_manager.list_tools()}
    assert {"inspect_project_topology", "diagnose_project_topology"} <= names
    assert len(names) == 85
