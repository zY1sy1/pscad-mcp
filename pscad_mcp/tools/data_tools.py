from typing import Dict, Any
from mcp.server.fastmcp import FastMCP
from ..core.connection_manager import pscad_manager

async def get_project_output(project_name: str) -> str:
    """Get the text output messages from the PSCAD project's runtime."""
    return await pscad_manager.service.get_project_output(project_name)

async def read_output_file(file_path: str, max_samples: int = 10_000) -> Dict[str, Any]:
    """Read traces from a .psout file using the current MHI PSOUT API."""
    try:
        return await pscad_manager.service.read_output_file(
            file_path, max_samples=max_samples
        )
    except Exception as e:
        return {"error": str(e)}

def register_data_tools(mcp: FastMCP):
    """Register tools for reading simulation results and output."""
    mcp.tool()(get_project_output)
    mcp.tool()(read_output_file)
