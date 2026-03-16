from typing import Dict, Any
from mcp.server.fastmcp import FastMCP
from ..core.connection_manager import pscad_manager
from ..core.executor import robust_executor
from .canvas_tools import _serialize_component, _serialize_port


async def _get_component(project_name: str, component_id: int):
    """Internal helper to retrieve a component by project name and ID."""
    pscad = pscad_manager.pscad
    project = await robust_executor.run_safe(pscad.project, project_name)
    return await robust_executor.run_safe(project.component, component_id)


async def get_component_location(project_name: str, component_id: int) -> Dict[str, Any]:
    """Get a component's (x, y) grid location.

    Args:
        project_name: Project containing the component.
        component_id: The component's ID.
    """
    component = await _get_component(project_name, component_id)
    loc = await robust_executor.run_safe(component.get_location)
    return {"id": component_id, "x": loc[0], "y": loc[1]}


async def set_component_location(project_name: str, component_id: int, x: int, y: int) -> str:
    """Move a component to a new (x, y) grid location.

    Args:
        project_name: Project containing the component.
        component_id: The component's ID.
        x: New X grid coordinate.
        y: New Y grid coordinate.
    """
    component = await _get_component(project_name, component_id)
    await robust_executor.run_safe(component.set_location, x, y)
    return f"Component {component_id} moved to ({x}, {y})."


async def rotate_component(project_name: str, component_id: int, direction: str = "right") -> str:
    """Rotate a component. Direction: 'right' (90 CW), 'left' (90 CCW), or '180'.

    Args:
        project_name: Project containing the component.
        component_id: The component's ID.
        direction: 'right', 'left', or '180'.
    """
    component = await _get_component(project_name, component_id)
    if direction == "right":
        await robust_executor.run_safe(component.rotate_right)
    elif direction == "left":
        await robust_executor.run_safe(component.rotate_left)
    elif direction == "180":
        await robust_executor.run_safe(component.rotate_180)
    else:
        raise ValueError(f"Invalid direction '{direction}'. Use 'right', 'left', or '180'.")
    return f"Component {component_id} rotated {direction}."


async def mirror_component(project_name: str, component_id: int, axis: str = "horizontal") -> str:
    """Mirror or flip a component. Axis: 'horizontal' (mirror) or 'vertical' (flip).

    Args:
        project_name: Project containing the component.
        component_id: The component's ID.
        axis: 'horizontal' for mirror, 'vertical' for flip.
    """
    component = await _get_component(project_name, component_id)
    if axis == "horizontal":
        await robust_executor.run_safe(component.mirror)
    elif axis == "vertical":
        await robust_executor.run_safe(component.flip)
    else:
        raise ValueError(f"Invalid axis '{axis}'. Use 'horizontal' or 'vertical'.")
    return f"Component {component_id} mirrored along {axis} axis."


async def clone_component(project_name: str, component_id: int, x: int, y: int) -> Dict[str, Any]:
    """Duplicate a component to a new location. Returns info about the new component.

    Args:
        project_name: Project containing the component.
        component_id: The component's ID to clone.
        x: X grid coordinate for the clone.
        y: Y grid coordinate for the clone.
    """
    component = await _get_component(project_name, component_id)
    new_component = await robust_executor.run_safe(component.clone, x, y)
    return _serialize_component(new_component)


async def get_component_ports(project_name: str, component_id: int) -> Dict[str, Dict[str, Any]]:
    """Get all ports of a component with their absolute locations (accounting for rotation/mirror).

    Args:
        project_name: Project containing the component.
        component_id: The component's ID.
    """
    component = await _get_component(project_name, component_id)
    ports = await robust_executor.run_safe(component.ports)
    return {name: _serialize_port(port) for name, port in ports.items()}


async def get_component_port(project_name: str, component_id: int, port_name: str) -> Dict[str, Any]:
    """Get a single named port's absolute location on a component.

    Args:
        project_name: Project containing the component.
        component_id: The component's ID.
        port_name: Name of the port to retrieve.
    """
    component = await _get_component(project_name, component_id)
    port = await robust_executor.run_safe(component.port, port_name)
    if port is None:
        raise ValueError(f"Port '{port_name}' not found on component {component_id}.")
    return _serialize_port(port)


async def enable_component(project_name: str, component_id: int) -> str:
    """Enable a disabled component.

    Args:
        project_name: Project containing the component.
        component_id: The component's ID.
    """
    component = await _get_component(project_name, component_id)
    await robust_executor.run_safe(component.enable)
    return f"Component {component_id} enabled."


async def disable_component(project_name: str, component_id: int) -> str:
    """Disable a component (excluded from simulation).

    Args:
        project_name: Project containing the component.
        component_id: The component's ID.
    """
    component = await _get_component(project_name, component_id)
    await robust_executor.run_safe(component.disable)
    return f"Component {component_id} disabled."


async def delete_component(project_name: str, component_id: int) -> str:
    """Delete a single component by its ID.

    Args:
        project_name: Project containing the component.
        component_id: The component's ID.
    """
    component = await _get_component(project_name, component_id)
    await robust_executor.run_safe(component.delete)
    return f"Component {component_id} deleted."


def register_component_tools(mcp: FastMCP):
    """Register tools for per-component operations."""
    mcp.tool()(get_component_location)
    mcp.tool()(set_component_location)
    mcp.tool()(rotate_component)
    mcp.tool()(mirror_component)
    mcp.tool()(clone_component)
    mcp.tool()(get_component_ports)
    mcp.tool()(get_component_port)
    mcp.tool()(enable_component)
    mcp.tool()(disable_component)
    mcp.tool()(delete_component)
