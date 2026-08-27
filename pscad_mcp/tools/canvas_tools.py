from typing import Annotated, Any, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..core.connection_manager import pscad_manager
from .pagination import PaginationLimit, PaginationOffset, slice_items
from .registration import register_tool

CanvasParameters = Annotated[
    Optional[dict[str, Any]],
    Field(
        description=(
            'Canvas parameter_name keys mapped to component or bus values; '
            'example {"R": 1.0, "Name": "Bus1"}.'
        )
    ),
]


async def add_component(
    project_name: str,
    library: str,
    name: str,
    x: int = 1,
    y: int = 1,
    orient: int = 0,
    parameters: CanvasParameters = None,
    canvas_name: str = "Main",
) -> dict[str, Any]:
    """Add a library component to a canvas."""
    return await pscad_manager.service.add_canvas_component(
        project_name,
        library,
        name,
        x,
        y,
        orient,
        parameters,
        canvas_name=canvas_name,
    )


async def create_component(
    project_name: str,
    definition: str,
    x: int = 1,
    y: int = 1,
    orient: int = 0,
    parameters: CanvasParameters = None,
    canvas_name: str = "Main",
) -> dict[str, Any]:
    """Create a component from a scoped definition such as master:source3."""
    return await pscad_manager.service.create_canvas_component(
        project_name,
        definition,
        x,
        y,
        orient,
        parameters,
        canvas_name=canvas_name,
    )


async def create_wire(
    project_name: str,
    vertices: list[list[int]],
    canvas_name: str = "Main",
) -> dict[str, Any]:
    """Create an orthogonal wire through the supplied vertices."""
    return await pscad_manager.service.create_wire(
        project_name, vertices, canvas_name=canvas_name
    )


async def create_bus(
    project_name: str,
    vertices: list[list[int]],
    parameters: CanvasParameters = None,
    canvas_name: str = "Main",
) -> dict[str, Any]:
    """Create an electrical bus through the supplied vertices."""
    return await pscad_manager.service.create_bus(
        project_name,
        vertices,
        parameters,
        canvas_name=canvas_name,
    )


async def create_connection(
    project_name: str,
    p1: list[int],
    p2: list[int],
    label: Optional[str] = None,
    electrical: Optional[bool] = None,
    canvas_name: str = "Main",
) -> dict[str, Any]:
    """Connect two points using a wire or matching node labels."""
    return await pscad_manager.service.create_connection(
        project_name,
        p1,
        p2,
        label,
        electrical,
        canvas_name=canvas_name,
    )


async def connect_ports(
    project_name: str,
    component1_id: int,
    port1_name: str,
    component2_id: int,
    port2_name: str,
    canvas_name: str = "Main",
) -> dict[str, Any]:
    """Connect two named component ports with a wire."""
    return await pscad_manager.service.connect_ports(
        project_name,
        component1_id,
        port1_name,
        component2_id,
        port2_name,
        canvas_name=canvas_name,
    )


async def create_annotation(
    project_name: str,
    x: int = 1,
    y: int = 1,
    line1: str = "",
    line2: str = "",
    canvas_name: str = "Main",
) -> dict[str, Any]:
    """Create a two-line annotation."""
    return await pscad_manager.service.create_annotation(
        project_name,
        x,
        y,
        line1,
        line2,
        canvas_name=canvas_name,
    )


async def create_graph_frame(
    project_name: str,
    x: int = 1,
    y: int = 1,
    canvas_name: str = "Main",
) -> dict[str, Any]:
    """Create an empty graph frame."""
    return await pscad_manager.service.create_graph_frame(
        project_name, x, y, canvas_name=canvas_name
    )


async def create_control_frame(
    project_name: str,
    x: int = 1,
    y: int = 1,
    canvas_name: str = "Main",
) -> dict[str, Any]:
    """Create an empty runtime control frame."""
    return await pscad_manager.service.create_control_frame(
        project_name, x, y, canvas_name=canvas_name
    )


async def list_canvas_components(
    project_name: str,
    canvas_name: str = "Main",
    offset: PaginationOffset = 0,
    limit: PaginationLimit = None,
) -> list[dict[str, Any]]:
    """List normalized objects on a canvas."""
    slice_items([], offset, limit, "list_canvas_components")
    values = await pscad_manager.service.list_canvas_components(
        project_name, canvas_name=canvas_name
    )
    return slice_items(values, offset, limit, "list_canvas_components")


async def find_empty_space(
    project_name: str,
    width: int,
    height: int,
    near_x: int = 1,
    near_y: int = 1,
    canvas_name: str = "Main",
) -> dict[str, Any]:
    """Find the closest empty rectangle near a point."""
    return await pscad_manager.service.find_empty_space(
        project_name,
        width,
        height,
        near_x,
        near_y,
        canvas_name=canvas_name,
    )


async def delete_components(
    project_name: str,
    component_ids: list[int],
    canvas_name: str = "Main",
    confirm: bool = False,
) -> str:
    """Delete components after explicit confirmation."""
    return await pscad_manager.service.delete_components(
        project_name, component_ids, confirm=confirm
    )


def register_canvas_tools(mcp: FastMCP) -> None:
    """Register Canvas creation, connection, query, and deletion tools."""
    register_tool(mcp, add_component)
    register_tool(mcp, create_component)
    register_tool(mcp, create_wire)
    register_tool(mcp, create_bus)
    register_tool(mcp, create_connection)
    register_tool(mcp, connect_ports)
    register_tool(mcp, create_annotation)
    register_tool(mcp, create_graph_frame)
    register_tool(mcp, create_control_frame)
    register_tool(mcp, list_canvas_components)
    register_tool(mcp, find_empty_space)
    register_tool(mcp, delete_components)
