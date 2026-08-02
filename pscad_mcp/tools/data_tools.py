from typing import Dict, Any
from mcp.server.fastmcp import FastMCP
from ..core.connection_manager import pscad_manager
from .registration import register_tool

async def get_project_output(project_name: str) -> str:
    """Get the text output messages from the PSCAD project's runtime."""
    return await pscad_manager.service.get_project_output(project_name)

async def read_output_file(file_path: str, max_samples: int = 10_000) -> Dict[str, Any]:
    """Read traces from a .psout file using the current MHI PSOUT API."""
    return await pscad_manager.service.read_output_file(
        file_path, max_samples=max_samples
    )

def register_data_tools(mcp: FastMCP):
    """Register tools for reading simulation results and output."""
    register_tool(mcp, get_project_output)
    register_tool(mcp, read_output_file)
