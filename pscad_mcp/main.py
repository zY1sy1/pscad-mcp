import logging
from mcp.server.fastmcp import FastMCP
from .tools.app_tools import register_app_tools
from .tools.project_tools import register_project_tools
from .tools.data_tools import register_data_tools
from .tools.simset_tools import register_simset_tools

# Configure central logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("pscad-mcp")

def create_server() -> FastMCP:
    """
    Factory to create and configure the FastMCP server.
    Applies modularity by registering tools from separate modules.
    """
    mcp = FastMCP("PSCAD-Modular")

    # Register tool groups (SRP)
    register_app_tools(mcp)
    register_project_tools(mcp)
    register_data_tools(mcp)
    register_simset_tools(mcp)
    
    logger.info("PSCAD MCP Server initialized with modular tools.")
    return mcp

def main():
    """Main entry point."""
    mcp = create_server()
    mcp.run()

if __name__ == "__main__":
    main()
