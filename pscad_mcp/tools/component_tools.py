from typing import Any, Dict

from mcp.server.fastmcp import FastMCP

from ..core.connection_manager import pscad_manager
from .registration import register_tool


async def get_component_location(
    project_name: str, component_id: int
) -> Dict[str, Any]:
    """Get a component's grid location."""
    return await pscad_manager.service.get_component_location(
        project_name, component_id
    )


async def set_component_location(
    project_name: str, component_id: int, x: int, y: int
) -> str:
    """Move a component to a grid location."""
    return await pscad_manager.service.set_component_location(
        project_name, component_id, x, y
    )


async def rotate_component(
    project_name: str,
    component_id: int,
    direction: str = "right",
) -> str:
    """Rotate a component right, left, or 180 degrees."""
    return await pscad_manager.service.rotate_component(
        project_name, component_id, direction
    )


async def mirror_component(
    project_name: str,
    component_id: int,
    axis: str = "horizontal",
) -> str:
    """Mirror a component horizontally or vertically."""
    return await pscad_manager.service.mirror_component(
        project_name, component_id, axis
    )


async def clone_component(
    project_name: str, component_id: int, x: int, y: int
) -> Dict[str, Any]:
    """Duplicate a component at a new grid location."""
    return await pscad_manager.service.clone_component(
        project_name, component_id, x, y
    )


async def get_component_ports(
    project_name: str, component_id: int
) -> Dict[str, Dict[str, Any]]:
    """List a component's named ports and absolute locations."""
    return await pscad_manager.service.get_component_ports(
        project_name, component_id
    )


async def get_component_port(
    project_name: str, component_id: int, port_name: str
) -> Dict[str, Any]:
    """Get one named component port."""
    return await pscad_manager.service.get_component_port(
        project_name, component_id, port_name
    )


async def enable_component(project_name: str, component_id: int) -> str:
    """Enable a component."""
    return await pscad_manager.service.set_component_enabled(
        project_name, component_id, True
    )


async def disable_component(project_name: str, component_id: int) -> str:
    """Disable a component."""
    return await pscad_manager.service.set_component_enabled(
        project_name, component_id, False
    )


async def delete_component(
    project_name: str,
    component_id: int,
    confirm: bool = False,
) -> str:
    """Delete a component after explicit confirmation."""
    return await pscad_manager.service.delete_component(
        project_name, component_id, confirm=confirm
    )


def register_component_tools(mcp: FastMCP):
    """Register per-component tools."""
    register_tool(mcp, get_component_location)
    register_tool(mcp, set_component_location)
    register_tool(mcp, rotate_component)
    register_tool(mcp, mirror_component)
    register_tool(mcp, clone_component)
    register_tool(mcp, get_component_ports)
    register_tool(mcp, get_component_port)
    register_tool(mcp, enable_component)
    register_tool(mcp, disable_component)
    register_tool(mcp, delete_component)
