from typing import Dict, Any
from mcp.server.fastmcp import FastMCP
from ..core.connection_manager import pscad_manager
from .registration import register_tool

async def get_project_output(
    project_name: str, structured: bool = False
) -> str | list[Dict[str, Any]]:
    """Get text output or normalized structured messages from a PSCAD project."""
    return await pscad_manager.service.get_project_output(
        project_name, structured=structured
    )

async def read_output_file(
    file_path: str,
    max_samples: int = 10_000,
    channel: str | None = None,
    summary_only: bool = False,
) -> Dict[str, Any]:
    """Read sampled traces or bounded channel summaries from a PSOUT file."""
    return await pscad_manager.service.read_output_file(
        file_path,
        max_samples=max_samples,
        channel=channel,
        summary_only=summary_only,
    )

def register_data_tools(mcp: FastMCP):
    """Register tools for reading simulation results and output."""
    register_tool(mcp, get_project_output)
    register_tool(mcp, read_output_file)
