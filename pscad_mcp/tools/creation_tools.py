from typing import List, Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
from ..core.connection_manager import pscad_manager
from .registration import register_tool


async def create_case(
    filename: str,
    folder: Optional[str] = None,
    confirm: bool = False,
) -> Dict[str, str]:
    """Create a new empty PSCAD case project (.pscx)."""
    return await pscad_manager.service.create_project(
        "case", filename, folder, confirm=confirm
    )


async def create_library(
    filename: str,
    folder: Optional[str] = None,
    confirm: bool = False,
) -> Dict[str, str]:
    """Create a new empty PSCAD library project (.pslx)."""
    return await pscad_manager.service.create_project(
        "library", filename, folder, confirm=confirm
    )


async def save_project(project_name: str, confirm: bool = False) -> str:
    """Save a project to disk."""
    return await pscad_manager.service.save_project(
        project_name, confirm=confirm
    )


async def save_project_as(
    project_name: str,
    filename: str,
    folder: Optional[str] = None,
    confirm: bool = False,
) -> str:
    """Save a project under a new filename."""
    return await pscad_manager.service.save_project_as(
        project_name, filename, folder, confirm=confirm
    )


async def build_project(project_name: str) -> str:
    """Compile/build a single project. May take a long time for large projects."""
    return await pscad_manager.service.build_project(project_name)


async def build_all_projects() -> str:
    """Compile/build all projects in the workspace."""
    return await pscad_manager.service.build_all_projects()


async def get_project_definitions(project_name: str) -> List[str]:
    """List all component definitions available in a project."""
    return await pscad_manager.service.get_project_definitions(project_name)


def register_creation_tools(mcp: FastMCP):
    """Register tools for creating and building projects."""
    register_tool(mcp, create_case)
    register_tool(mcp, create_library)
    register_tool(mcp, save_project)
    register_tool(mcp, save_project_as)
    register_tool(mcp, build_project)
    register_tool(mcp, build_all_projects)
    register_tool(mcp, get_project_definitions)
