from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.connection_manager import pscad_manager
from .registration import register_tool


async def inspect_project_topology(
    project_name: str,
    canvas_name: str = "Main",
    mode: str = "conservative",
) -> dict[str, Any]:
    """Inspect confirmed project topology without modifying PSCAD state."""
    return await pscad_manager.service.topology_service.inspect_payload(
        project_name,
        canvas_name,
        mode=mode,
    )


async def diagnose_project_topology(
    project_name: str,
    canvas_name: str = "Main",
    ruleset: str = "generic+hvdc-auto",
    mode: str = "conservative",
) -> dict[str, Any]:
    """Run read-only topology diagnostics with optional explicit inference."""
    return await pscad_manager.service.topology_service.diagnose_payload(
        project_name,
        canvas_name,
        ruleset=ruleset,
        mode=mode,
    )


def register_topology_tools(mcp: FastMCP) -> None:
    register_tool(mcp, inspect_project_topology)
    register_tool(mcp, diagnose_project_topology)
