from typing import List, Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
from ..core.connection_manager import pscad_manager
from ..core.executor import robust_executor

BUILD_TIMEOUT = 300.0


async def create_case(filename: str, folder: Optional[str] = None) -> Dict[str, str]:
    """Create a new empty PSCAD case project (.pscx)."""
    pscad = pscad_manager.pscad
    kwargs = {"filename": filename}
    if folder is not None:
        kwargs["folder"] = folder
    project = await robust_executor.run_safe(pscad.create_case, **kwargs)
    return {"name": project.name, "filename": str(getattr(project, 'filename', filename))}


async def create_library(filename: str, folder: Optional[str] = None) -> Dict[str, str]:
    """Create a new empty PSCAD library project (.pslx)."""
    pscad = pscad_manager.pscad
    kwargs = {"filename": filename}
    if folder is not None:
        kwargs["folder"] = folder
    project = await robust_executor.run_safe(pscad.create_library, **kwargs)
    return {"name": project.name, "filename": str(getattr(project, 'filename', filename))}


async def save_project(project_name: str) -> str:
    """Save a project to disk."""
    pscad = pscad_manager.pscad
    project = await robust_executor.run_safe(pscad.project, project_name)
    await robust_executor.run_safe(project.save)
    return f"Project '{project_name}' saved."


async def save_project_as(project_name: str, filename: str, folder: Optional[str] = None) -> str:
    """Save a project under a new filename."""
    pscad = pscad_manager.pscad
    project = await robust_executor.run_safe(pscad.project, project_name)
    kwargs = {"filename": filename}
    if folder is not None:
        kwargs["folder"] = folder
    await robust_executor.run_safe(project.save_as, **kwargs)
    return f"Project '{project_name}' saved as '{filename}'."


async def build_project(project_name: str) -> str:
    """Compile/build a single project. May take a long time for large projects."""
    pscad = pscad_manager.pscad
    project = await robust_executor.run_safe(pscad.project, project_name)
    await robust_executor.run_safe(project.build, timeout=BUILD_TIMEOUT)
    return f"Project '{project_name}' built successfully."


async def build_all_projects() -> str:
    """Compile/build all projects in the workspace."""
    pscad = pscad_manager.pscad
    await robust_executor.run_safe(pscad.build_all, timeout=BUILD_TIMEOUT)
    return "All projects built successfully."


async def get_project_definitions(project_name: str) -> List[str]:
    """List all component definitions available in a project."""
    pscad = pscad_manager.pscad
    project = await robust_executor.run_safe(pscad.project, project_name)
    definitions = await robust_executor.run_safe(project.definitions)
    return [str(d.name) for d in definitions]


def register_creation_tools(mcp: FastMCP):
    """Register tools for creating and building projects."""
    mcp.tool()(create_case)
    mcp.tool()(create_library)
    mcp.tool()(save_project)
    mcp.tool()(save_project_as)
    mcp.tool()(build_project)
    mcp.tool()(build_all_projects)
    mcp.tool()(get_project_definitions)
