from typing import Annotated, Any, Dict, List
from mcp.server.fastmcp import FastMCP
from pydantic import Field
from ..core.connection_manager import pscad_manager
from .registration import register_tool

SimulationTaskParameters = Annotated[
    Dict[str, Any],
    Field(
        description=(
            'Supported keys controlgroup, volley, and affinity; example '
            '{"controlgroup": "A", "volley": 2, "affinity": 1}.'
        )
    ),
]

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


async def create_simulation_set(sim_set_name: str) -> Dict[str, Any]:
    """Create a workspace-level simulation set."""
    return await pscad_manager.service.create_simulation_set(sim_set_name)


async def remove_simulation_set(
    sim_set_name: str, confirm: bool = False
) -> Dict[str, str]:
    """Remove a workspace-level simulation set after confirmation."""
    return await pscad_manager.service.remove_simulation_set(
        sim_set_name, confirm=confirm
    )


async def list_simulation_set_tasks(sim_set_name: str) -> List[str]:
    """List the tasks assigned to a workspace-level simulation set."""
    return await pscad_manager.service.list_simulation_set_tasks(sim_set_name)


async def remove_tasks_from_set(
    sim_set_name: str, task_names: List[str], confirm: bool = False
) -> Dict[str, List[str]]:
    """Remove tasks from a simulation set after confirmation."""
    return await pscad_manager.service.remove_tasks_from_set(
        sim_set_name, task_names, confirm=confirm
    )


async def get_simulation_task_parameters(
    sim_set_name: str, task_name: str
) -> Dict[str, Any]:
    """Read normalized task parameters from a simulation set."""
    return await pscad_manager.service.get_simulation_task_parameters(
        sim_set_name, task_name
    )


async def set_simulation_task_parameters(
    sim_set_name: str, task_name: str, parameters: SimulationTaskParameters
) -> Dict[str, Any]:
    """Update supported simulation task parameters and verify read-back."""
    return await pscad_manager.service.set_simulation_task_parameters(
        sim_set_name, task_name, parameters
    )


async def get_simulation_set_details(sim_set_name: str) -> Dict[str, Any]:
    """Read normalized details for a workspace-level simulation set."""
    return await pscad_manager.service.get_simulation_set_details(sim_set_name)

def register_simset_tools(mcp: FastMCP):
    """Register tools for batch simulation management."""
    register_tool(mcp, list_simulation_sets)
    register_tool(mcp, run_simulation_set)
    register_tool(mcp, add_task_to_set)
    register_tool(mcp, create_simulation_set)
    register_tool(mcp, remove_simulation_set)
    register_tool(mcp, list_simulation_set_tasks)
    register_tool(mcp, remove_tasks_from_set)
    register_tool(mcp, get_simulation_task_parameters)
    register_tool(mcp, set_simulation_task_parameters)
    register_tool(mcp, get_simulation_set_details)
