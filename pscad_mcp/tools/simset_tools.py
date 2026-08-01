from typing import List
from mcp.server.fastmcp import FastMCP
from ..core.connection_manager import pscad_manager

async def list_simulation_sets(project_name: str) -> List[str]:
    """List all simulation sets defined in the PSCAD application."""
    return await pscad_manager.service.list_simulation_sets(project_name)

async def run_simulation_set(project_name: str, sim_set_name: str) -> str:
    """Run a specific simulation set (batch of tasks)."""
    return await pscad_manager.service.run_simulation_set(
        project_name, sim_set_name
    )

async def add_task_to_set(project_name: str, sim_set_name: str, task_project_name: str) -> str:
    """Add a project task to an existing simulation set."""
    return await pscad_manager.service.add_task_to_set(
        project_name, sim_set_name, task_project_name
    )

def register_simset_tools(mcp: FastMCP):
    """Register tools for batch simulation management."""
    mcp.tool()(list_simulation_sets)
    mcp.tool()(run_simulation_set)
    mcp.tool()(add_task_to_set)
