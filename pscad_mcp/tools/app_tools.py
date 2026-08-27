import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.backend.base import BackendError
from ..core.connection_manager import pscad_manager
from ..core.path_policy import PathPolicy
from ..utils.doc_manager import doc_manager
from .registration import register_tool

path_policy = PathPolicy()

async def get_local_pscad() -> str:
    """Attach to a running local PSCAD instance or launch a new one."""
    return await pscad_manager.attach_local()

async def get_pscad_status() -> dict[str, Any]:
    """Get detailed health and status of the PSCAD instance."""
    try:
        return await pscad_manager.get_status()
    except Exception as e:
        return {
            "connected": False,
            "executor": pscad_manager.service.executor_status(),
            **pscad_manager.error_payload(e, "get_pscad_status"),
        }

async def sync_documentation() -> list[str]:
    """Synchronize AI reference files with the currently installed library version."""
    return await asyncio.to_thread(doc_manager.sync)

async def list_documentation() -> list[str]:
    """List available PSCAD API documentation modules that can be read."""
    doc_manager.raise_for_issue("list_documentation")
    try:
        if not doc_manager.md_dir.is_dir():
            return ["No documentation found. Run sync_documentation first."]
        paths = tuple(doc_manager.md_dir.iterdir())
        docs = [
            path.stem.replace("_", ".")
            for path in paths
            if path.is_file() and path.suffix == ".md"
        ]
    except FileNotFoundError:
        return ["No documentation found. Run sync_documentation first."]
    except BackendError:
        raise
    except Exception:
        raise doc_manager.storage_error("list_documentation", "md") from None
    return sorted(docs)

async def read_documentation(module_name: str) -> str:
    """Read the Markdown documentation for a specific PSCAD module (e.g., 'mhi.pscad.types')."""
    doc_manager.raise_for_issue("read_documentation")
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
    except BackendError:
        raise
    except Exception:
        raise doc_manager.storage_error("read_documentation", "md") from None
    
    if filepath is None:
        return f"Error: Documentation for '{module_name}' not found. Available modules: {', '.join(await list_documentation())}"

    try:
        return filepath.read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"Error: Documentation for '{module_name}' not found. Available modules: {', '.join(await list_documentation())}"
    except BackendError:
        raise
    except Exception:
        raise doc_manager.storage_error("read_documentation", "md") from None


def register_documentation_resources(mcp: FastMCP) -> None:
    @mcp.resource(
        "pscad-docs://modules/{module_name}",
        name="pscad_documentation_module",
        description="Read one locally generated PSCAD API documentation module.",
        mime_type="text/markdown",
    )
    async def documentation_module(module_name: str) -> str:
        return await read_documentation(module_name)

async def repair_connection() -> str:
    """Force-reset the connection to PSCAD."""
    return await pscad_manager.repair_connection()

async def quit_pscad(confirm: bool = False) -> str | dict[str, Any]:
    """Terminate the PSCAD application."""
    try:
        return await pscad_manager.quit_pscad(confirm=confirm)
    except Exception as e:
        return pscad_manager.error_payload(e, "quit_pscad")

def register_app_tools(mcp: FastMCP):
    """Register core application lifecycle and sync tools."""
    register_tool(mcp, get_local_pscad)
    register_tool(mcp, get_pscad_status)
    register_tool(mcp, sync_documentation)
    register_tool(mcp, list_documentation)
    register_tool(mcp, read_documentation)
    register_tool(mcp, repair_connection)
    register_tool(mcp, quit_pscad)
