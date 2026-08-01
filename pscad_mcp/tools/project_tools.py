from typing import List, Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
from ..core.connection_manager import pscad_manager
from ..core.executor import robust_executor

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


async def get_project_settings(project_name: str) -> Dict[str, Any]:
    """Get application settings exposed by the current PSCAD API."""
    return await pscad_manager.service.get_project_settings(project_name)

async def set_project_settings(project_name: str, settings: Dict[str, Any]) -> str:
    """Update application settings exposed by the current PSCAD API."""
    return await pscad_manager.service.set_project_settings(
        project_name,
        settings,
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
    mcp.tool()(load_projects)
    mcp.tool()(list_projects)
    mcp.tool()(run_project)
    mcp.tool()(get_run_status)
    mcp.tool()(find_components)
    mcp.tool()(get_component_parameters)
    mcp.tool()(set_component_parameters)
    mcp.tool()(validate_component_parameters)
    mcp.tool()(pause_simulation)
    mcp.tool()(stop_simulation)
    mcp.tool()(get_project_settings)
    mcp.tool()(set_project_settings)
