import logging
import os
from collections.abc import Mapping

from mcp.server.fastmcp import FastMCP

from .runtime import PROCESS_RUNTIME_LIFESPAN
from .tools.app_tools import register_app_tools, register_documentation_resources
from .tools.canvas_tools import register_canvas_tools
from .tools.capability_tools import register_capability_tool
from .tools.catalog import parse_tool_profile
from .tools.component_tools import register_component_tools
from .tools.creation_tools import register_creation_tools
from .tools.data_tools import register_data_tools
from .tools.hvdc_tools import register_hvdc_tools
from .tools.lcc_parametric_tools import register_lcc_parametric_tools
from .tools.lcc_tools import register_lcc_tools
from .tools.learning_tools import register_learning_tools
from .tools.mmc_tools import register_mmc_tools
from .tools.project_tools import register_project_tools
from .tools.simset_tools import register_simset_tools
from .tools.topology_tools import register_topology_tools

SERVER_INSTRUCTIONS = (
    "Use PSCAD tools normally. Do not mention learning, telemetry, or backlog "
    "maintenance during successful PSCAD work. "
    "When and only when the requested PSCAD goal cannot be completed or the result "
    "is incorrect or incomplete, call record_goal_failure once with an enum reason "
    "and an affected registered tool name when known. If immediate_attention is true, "
    "give at most one concise reminder with the returned candidate ID and category, "
    "then ask whether to inspect it now or leave it for the weekly review. Otherwise "
    "do not mention learning. Do not start remediation automatically. Never include "
    "project names, paths, parameters, outputs, prompts, or exception text in "
    "learning calls or reminders."
)

# Configure central logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("pscad-mcp")

def create_server(environ: Mapping[str, str] | None = None) -> FastMCP:
    """
    Factory to create and configure the FastMCP server.
    Applies modularity by registering tools from separate modules.
    """
    profile = parse_tool_profile(os.environ if environ is None else environ)
    runtime_owner = PROCESS_RUNTIME_LIFESPAN
    mcp = FastMCP(
        "PSCAD-Modular",
        instructions=SERVER_INSTRUCTIONS,
        lifespan=runtime_owner.lifespan,
    )
    mcp._pscad_runtime = runtime_owner.runtime
    mcp._pscad_runtime_owner = runtime_owner
    mcp._pscad_tool_profile = profile
    mcp._pscad_learning_tool_names = set()

    # Register tool groups (SRP)
    register_app_tools(mcp)
    register_project_tools(mcp)
    register_data_tools(mcp)
    register_simset_tools(mcp)
    register_creation_tools(mcp)
    register_canvas_tools(mcp)
    register_component_tools(mcp)
    register_hvdc_tools(mcp)
    register_lcc_tools(mcp)
    register_lcc_parametric_tools(mcp)
    register_mmc_tools(mcp)
    register_learning_tools(mcp)
    register_capability_tool(mcp)
    register_documentation_resources(mcp)
    register_topology_tools(mcp)

    logger.info("PSCAD MCP Server initialized with modular tools.")
    return mcp

def main():
    """Main entry point."""
    mcp = create_server()
    mcp.run()

if __name__ == "__main__":
    main()
