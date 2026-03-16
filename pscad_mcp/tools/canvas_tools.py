from typing import List, Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
from ..core.connection_manager import pscad_manager
from ..core.executor import robust_executor


async def _get_canvas(project_name: str, canvas_name: str = "Main"):
    """Internal helper to retrieve a project and its canvas."""
    pscad = pscad_manager.pscad
    project = await robust_executor.run_safe(pscad.project, project_name)
    canvas = await robust_executor.run_safe(project.canvas, canvas_name)
    return project, canvas


def _serialize_component(c) -> Dict[str, Any]:
    """Convert a PSCAD component to a JSON-serializable dict."""
    result = {"id": c.id}
    try:
        result["name"] = c.name
    except Exception:
        result["name"] = None
    try:
        result["definition"] = str(c.defn_name)
    except Exception:
        result["definition"] = None
    try:
        loc = c.location
        result["location"] = [loc[0], loc[1]]
    except Exception:
        result["location"] = None
    return result


def _serialize_port(port) -> Dict[str, Any]:
    """Convert a PSCAD Port namedtuple to a JSON-serializable dict."""
    return {
        "x": port.x,
        "y": port.y,
        "name": str(port.name),
        "dim": port.dim if hasattr(port, 'dim') else None,
        "type": str(port.type) if hasattr(port, 'type') else None,
    }


async def add_component(
    project_name: str, library: str, name: str,
    x: int = 1, y: int = 1, orient: int = 0,
    parameters: Optional[Dict[str, Any]] = None,
    canvas_name: str = "Main"
) -> Dict[str, Any]:
    """Add a component from a library to the canvas at (x, y).

    Args:
        project_name: Target project name.
        library: Library containing the component definition (e.g. 'master').
        name: Component definition name in the library (e.g. 'source3').
        x: X grid coordinate.
        y: Y grid coordinate.
        orient: Orientation (0=normal, 1=rotated right, etc.).
        parameters: Optional dict of initial parameter values.
        canvas_name: Canvas page name (default 'Main').
    """
    _, canvas = await _get_canvas(project_name, canvas_name)
    params = parameters or {}
    component = await robust_executor.run_safe(
        canvas.add_component, library, name, x, y, orient, **params
    )
    return _serialize_component(component)


async def create_component(
    project_name: str, definition: str,
    x: int = 1, y: int = 1, orient: int = 0,
    parameters: Optional[Dict[str, Any]] = None,
    canvas_name: str = "Main"
) -> Dict[str, Any]:
    """Create a component from a definition string (e.g. 'master:source3') on the canvas.

    Args:
        project_name: Target project name.
        definition: Component definition string (e.g. 'master:source3', 'master:ground').
        x: X grid coordinate.
        y: Y grid coordinate.
        orient: Orientation (0=normal).
        parameters: Optional dict of initial parameter values.
        canvas_name: Canvas page name (default 'Main').
    """
    _, canvas = await _get_canvas(project_name, canvas_name)
    params = parameters or {}
    component = await robust_executor.run_safe(
        canvas.create_component, definition, x, y, orient, **params
    )
    return _serialize_component(component)


async def create_wire(
    project_name: str, vertices: List[List[int]],
    canvas_name: str = "Main"
) -> Dict[str, Any]:
    """Create a wire connecting a series of (x, y) points on the canvas.

    Args:
        project_name: Target project name.
        vertices: List of [x, y] coordinate pairs, e.g. [[10, 5], [20, 5]].
        canvas_name: Canvas page name (default 'Main').
    """
    _, canvas = await _get_canvas(project_name, canvas_name)
    tuples = [tuple(v) for v in vertices]
    wire = await robust_executor.run_safe(canvas.create_wire, *tuples)
    result = {"id": wire.id}
    try:
        eps = wire.endpoints()
        result["endpoints"] = [[eps[0].x, eps[0].y], [eps[1].x, eps[1].y]]
    except Exception:
        result["endpoints"] = [list(tuples[0]), list(tuples[-1])]
    return result


async def create_bus(
    project_name: str, vertices: List[List[int]],
    parameters: Optional[Dict[str, Any]] = None,
    canvas_name: str = "Main"
) -> Dict[str, Any]:
    """Create a 3-phase electrical bus on the canvas.

    Args:
        project_name: Target project name.
        vertices: List of [x, y] coordinate pairs for the bus path.
        parameters: Optional bus parameters (Name, BaseKV, VA, VM, type).
        canvas_name: Canvas page name (default 'Main').
    """
    _, canvas = await _get_canvas(project_name, canvas_name)
    tuples = [tuple(v) for v in vertices]
    bus = await robust_executor.run_safe(canvas.create_bus, *tuples)
    if parameters:
        await robust_executor.run_safe(bus.parameters, parameters=parameters)
    result = {"id": bus.id}
    try:
        result["name"] = bus.name
    except Exception:
        result["name"] = None
    return result


async def create_connection(
    project_name: str, p1: List[int], p2: List[int],
    label: Optional[str] = None, electrical: Optional[bool] = None,
    canvas_name: str = "Main"
) -> Dict[str, Any]:
    """Create a smart connection between two points. Uses wires if no label, or node labels if label is provided.

    Args:
        project_name: Target project name.
        p1: First point [x, y].
        p2: Second point [x, y].
        label: Optional node label name. If provided, creates labeled connection.
        electrical: Required if label is set. True=electrical, False=data label.
        canvas_name: Canvas page name (default 'Main').
    """
    _, canvas = await _get_canvas(project_name, canvas_name)
    kwargs = {}
    if label is not None:
        kwargs["label"] = label
    if electrical is not None:
        kwargs["electrical"] = electrical
    result_label = await robust_executor.run_safe(
        canvas.create_connection, tuple(p1), tuple(p2), **kwargs
    )
    if result_label:
        return {"label": result_label}
    return {"connected": True}


async def connect_ports(
    project_name: str,
    component1_id: int, port1_name: str,
    component2_id: int, port2_name: str,
    canvas_name: str = "Main"
) -> Dict[str, Any]:
    """Connect two component ports with a wire. Resolves port locations automatically.

    Args:
        project_name: Target project name.
        component1_id: ID of the first component.
        port1_name: Name of the port on the first component.
        component2_id: ID of the second component.
        port2_name: Name of the port on the second component.
        canvas_name: Canvas page name (default 'Main').
    """
    project, canvas = await _get_canvas(project_name, canvas_name)
    comp1 = await robust_executor.run_safe(canvas.component, component1_id)
    comp2 = await robust_executor.run_safe(canvas.component, component2_id)
    port1 = await robust_executor.run_safe(comp1.port, port1_name)
    port2 = await robust_executor.run_safe(comp2.port, port2_name)
    if port1 is None:
        raise ValueError(f"Port '{port1_name}' not found on component {component1_id}")
    if port2 is None:
        raise ValueError(f"Port '{port2_name}' not found on component {component2_id}")
    wire = await robust_executor.run_safe(
        canvas.create_wire, (port1.x, port1.y), (port2.x, port2.y)
    )
    return {
        "wire_id": wire.id,
        "from": {"component_id": component1_id, "port": port1_name, "x": port1.x, "y": port1.y},
        "to": {"component_id": component2_id, "port": port2_name, "x": port2.x, "y": port2.y},
    }


async def create_annotation(
    project_name: str, x: int = 1, y: int = 1,
    line1: str = "", line2: str = "",
    canvas_name: str = "Main"
) -> Dict[str, Any]:
    """Create a two-line text annotation on the canvas.

    Args:
        project_name: Target project name.
        x: X grid coordinate.
        y: Y grid coordinate.
        line1: First line of text.
        line2: Second line of text.
        canvas_name: Canvas page name (default 'Main').
    """
    _, canvas = await _get_canvas(project_name, canvas_name)
    component = await robust_executor.run_safe(canvas.create_annotation, x, y, line1, line2)
    return _serialize_component(component)


async def create_graph_frame(
    project_name: str, x: int = 1, y: int = 1,
    canvas_name: str = "Main"
) -> Dict[str, Any]:
    """Create an empty graph frame container for output visualization.

    Args:
        project_name: Target project name.
        x: X grid coordinate.
        y: Y grid coordinate.
        canvas_name: Canvas page name (default 'Main').
    """
    _, canvas = await _get_canvas(project_name, canvas_name)
    graph_frame = await robust_executor.run_safe(canvas.create_graph_frame, x, y)
    return {"id": graph_frame.id}


async def create_control_frame(
    project_name: str, x: int = 1, y: int = 1,
    canvas_name: str = "Main"
) -> Dict[str, Any]:
    """Create a runtime control frame for interactive simulation controls.

    Args:
        project_name: Target project name.
        x: X grid coordinate.
        y: Y grid coordinate.
        canvas_name: Canvas page name (default 'Main').
    """
    _, canvas = await _get_canvas(project_name, canvas_name)
    frame, controls = await robust_executor.run_safe(canvas.create_control_frame, x, y)
    return {
        "frame_id": frame.id,
        "control_ids": [c.id for c in controls],
    }


async def list_canvas_components(
    project_name: str, canvas_name: str = "Main"
) -> List[Dict[str, Any]]:
    """List all components on a canvas with their id, name, definition, and location.

    Args:
        project_name: Target project name.
        canvas_name: Canvas page name (default 'Main').
    """
    _, canvas = await _get_canvas(project_name, canvas_name)
    components = await robust_executor.run_safe(canvas.components)
    return [_serialize_component(c) for c in components]


async def find_empty_space(
    project_name: str, width: int, height: int,
    near_x: int = 1, near_y: int = 1,
    canvas_name: str = "Main"
) -> Dict[str, Any]:
    """Find the closest empty rectangle of given size near a point.

    Args:
        project_name: Target project name.
        width: Required width in grid units.
        height: Required height in grid units.
        near_x: X coordinate to search near.
        near_y: Y coordinate to search near.
        canvas_name: Canvas page name (default 'Main').
    """
    _, canvas = await _get_canvas(project_name, canvas_name)
    rect = await robust_executor.run_safe(
        canvas.closest_empty_rect, width, height, (near_x, near_y)
    )
    return {"x": rect.x, "y": rect.y, "width": rect.width, "height": rect.height}


async def delete_components(
    project_name: str, component_ids: List[int],
    canvas_name: str = "Main"
) -> str:
    """Delete one or more components from the canvas by their IDs.

    Args:
        project_name: Target project name.
        component_ids: List of component IDs to delete.
        canvas_name: Canvas page name (default 'Main').
    """
    _, canvas = await _get_canvas(project_name, canvas_name)
    components = []
    for cid in component_ids:
        c = await robust_executor.run_safe(canvas.component, cid)
        components.append(c)
    await robust_executor.run_safe(canvas.delete, *components)
    return f"Deleted {len(component_ids)} component(s)."


def register_canvas_tools(mcp: FastMCP):
    """Register tools for canvas operations: component placement, wiring, visualization."""
    mcp.tool()(add_component)
    mcp.tool()(create_component)
    mcp.tool()(create_wire)
    mcp.tool()(create_bus)
    mcp.tool()(create_connection)
    mcp.tool()(connect_ports)
    mcp.tool()(create_annotation)
    mcp.tool()(create_graph_frame)
    mcp.tool()(create_control_frame)
    mcp.tool()(list_canvas_components)
    mcp.tool()(find_empty_space)
    mcp.tool()(delete_components)
