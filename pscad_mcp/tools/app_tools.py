from typing import List, Dict, Any, Optional
import os
from mcp.server.fastmcp import FastMCP
from ..core.connection_manager import pscad_manager
from ..utils.doc_manager import doc_manager
from ..core.path_policy import PathPolicy

path_policy = PathPolicy()

async def get_local_pscad() -> str:
    """Attach to a running local PSCAD instance or launch a new one."""
    return await pscad_manager.attach_local()

async def get_pscad_status() -> Dict[str, Any]:
    """Get detailed health and status of the PSCAD instance."""
    try:
        return await pscad_manager.get_status()
    except Exception as e:
        return {
            "connected": False,
            **pscad_manager.error_payload(e, "get_pscad_status"),
        }

async def sync_documentation() -> List[str]:
    """Synchronize AI reference files with the currently installed library version."""
    return doc_manager.sync()

async def list_documentation() -> List[str]:
    """List available PSCAD API documentation modules that can be read."""
    if not os.path.exists(doc_manager.md_dir):
        return ["No documentation found. Run sync_documentation first."]
    
    docs = []
    for f in os.listdir(doc_manager.md_dir):
        if f.endswith(".md"):
            # Return original module names (e.g. mhi_pscad_types.md -> mhi.pscad.types)
            module_name = f[:-3].replace("_", ".")
            docs.append(module_name)
    return sorted(docs)

async def read_documentation(module_name: str) -> str:
    """Read the Markdown documentation for a specific PSCAD module (e.g., 'mhi.pscad.types')."""
    # Normalize input
    normalized_name = module_name.replace(".", "_")
    if not normalized_name.endswith(".md"):
        normalized_name += ".md"
        
    try:
        filepath = path_policy.resolve_child(
            doc_manager.md_dir,
            normalized_name,
            suffixes={".md"},
            must_exist=True,
        )
    except (FileNotFoundError, ValueError):
        filepath = None
    
    if filepath is None:
        return f"Error: Documentation for '{module_name}' not found. Available modules: {', '.join(await list_documentation())}"
        
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()

async def repair_connection() -> str:
    """Force-reset the connection to PSCAD."""
    return await pscad_manager.repair_connection()

async def quit_pscad(confirm: bool = False) -> Any:
    """Terminate the PSCAD application."""
    try:
        return await pscad_manager.quit_pscad(confirm=confirm)
    except Exception as e:
        return pscad_manager.error_payload(e, "quit_pscad")

def register_app_tools(mcp: FastMCP):
    """Register core application lifecycle and sync tools."""
    mcp.tool()(get_local_pscad)
    mcp.tool()(get_pscad_status)
    mcp.tool()(sync_documentation)
    mcp.tool()(list_documentation)
    mcp.tool()(read_documentation)
    mcp.tool()(repair_connection)
    mcp.tool()(quit_pscad)
