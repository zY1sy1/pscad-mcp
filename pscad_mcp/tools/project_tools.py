from typing import List, Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
from ..core.connection_manager import pscad_manager
from ..core.executor import robust_executor
from .registration import register_tool

async def load_projects(filenames: List[str]) -> str:
    """Load projects or workspace into PSCAD."""
    return await pscad_manager.service.load_projects(filenames)

async def list_projects() -> List[Dict[str, str]]:
    """List all projects in the workspace."""
    return await pscad_manager.service.list_projects()

async def run_project(project_name: str) -> str:
    """Start simulation for a given project."""
    return await pscad_manager.service.run_project(project_name)

async def get_run_status(project_name: str) -> Dict[str, Any]:
    """Get simulation progress and state."""
    return await pscad_manager.service.get_run_status(project_name)

async def find_components(
    project_name: str, 
    definition: Optional[str] = None, 
    name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Find components matching criteria in a project."""
    return await pscad_manager.service.find_components(
        project_name, definition=definition, name=name
    )

async def get_component_parameters(project_name: str, component_id: int) -> Dict[str, Any]:
    """Get all parameter values for a specific component by its ID."""
    return await pscad_manager.service.get_component_parameters(
        project_name, component_id
    )

async def set_component_parameters(project_name: str, component_id: int, parameters: Dict[str, Any]) -> str:
    """Set parameter values for a specific component."""
    return await pscad_manager.service.set_component_parameters(
        project_name, component_id, parameters
    )

async def validate_component_parameters(project_name: str, component_id: int, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Validate if the given parameters are within the legal range for a component."""
    return await pscad_manager.service.validate_component_parameters(
        project_name, component_id, parameters
    )

async def pause_simulation(project_name: str) -> str:
    """Pause the running simulation for a project."""
    return await pscad_manager.service.pause_simulation(project_name)


async def stop_simulation(project_name: str) -> str:
    """Stop/terminate the running simulation for a project."""
    return await pscad_manager.service.stop_simulation(project_name)


async def get_project_settings(
    project_name: str,
    mode: str = "project",
    parameter_grid: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Get project settings or a normalized parameter-grid view."""
    if mode == "project" and parameter_grid is None:
        return await pscad_manager.service.get_project_settings(project_name)
    return await pscad_manager.service.get_project_settings(
        project_name,
        mode=mode,
        parameter_grid=parameter_grid,
    )

async def set_project_settings(
    project_name: str,
    settings: Dict[str, Any],
    mode: str = "project",
    parameter_grid: Optional[Dict[str, Any]] = None,
) -> str | Dict[str, Any]:
    """Update project settings or run a parameter-grid action."""
    if mode == "project" and parameter_grid is None:
        return await pscad_manager.service.set_project_settings(
            project_name,
            settings,
        )
    return await pscad_manager.service.set_project_settings(
        project_name,
        settings,
        mode=mode,
        parameter_grid=parameter_grid,
    )


def _value_in_range(value: Any, legal_range: Any) -> bool:
    """Validate common numeric, enum, and collection ranges returned by MHI."""
    if isinstance(legal_range, range):
        return value in legal_range
    if isinstance(legal_range, (tuple, list)) and len(legal_range) == 2:
        lower, upper = legal_range
        if all(isinstance(item, (int, float)) for item in (lower, upper)):
            return lower <= value <= upper
    try:
        return value in legal_range
    except (TypeError, ValueError):
        return False

def register_project_tools(mcp: FastMCP):
    """Register tools for managing projects and components."""
    register_tool(mcp, load_projects)
    register_tool(mcp, list_projects)
    register_tool(mcp, run_project)
    register_tool(mcp, get_run_status)
    register_tool(mcp, find_components)
    register_tool(mcp, get_component_parameters)
    register_tool(mcp, set_component_parameters)
    register_tool(mcp, validate_component_parameters)
    register_tool(mcp, pause_simulation)
    register_tool(mcp, stop_simulation)
    register_tool(mcp, get_project_settings)
    register_tool(mcp, set_project_settings)
