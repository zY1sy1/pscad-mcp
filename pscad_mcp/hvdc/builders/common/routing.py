"""Deterministic orientation and orthogonal-routing primitives."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ....core.backend.base import BackendError


def _layout_error(message: str, **details: Any) -> BackendError:
    return BackendError("BUILDER_LAYOUT_INVALID", message, "hvdc", "validate_builder_layout", details)


def _coordinate(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _layout_error(f"{context} must be an integer.", context=context)
    return value


def transform_offset(x: int, y: int, orientation: int) -> tuple[int, int]:
    x = _coordinate(x, "offset.x")
    y = _coordinate(y, "offset.y")
    orientation = _coordinate(orientation, "orientation")
    if not 0 <= orientation <= 7:
        raise _layout_error("orientation must be between 0 and 7.", orientation=orientation)
    return {
        0: (x, y),
        1: (-y, x),
        2: (-x, -y),
        3: (y, -x),
        4: (-x, y),
        5: (-y, -x),
        6: (x, -y),
        7: (y, x),
    }[orientation]


def absolute_port(origin: tuple[int, int], offset: tuple[int, int], orientation: int) -> tuple[int, int]:
    if len(origin) != 2 or len(offset) != 2:
        raise _layout_error("origin and offset require two coordinates.")
    origin_point = (_coordinate(origin[0], "origin.x"), _coordinate(origin[1], "origin.y"))
    transformed = transform_offset(offset[0], offset[1], orientation)
    return (origin_point[0] + transformed[0], origin_point[1] + transformed[1])


def validate_orthogonal_route(vertices: Sequence[Sequence[int]]) -> tuple[tuple[int, int], ...]:
    if isinstance(vertices, (str, bytes, bytearray)) or not isinstance(vertices, Sequence):
        raise _layout_error("route vertices must be an array.")
    if len(vertices) < 2:
        raise _layout_error("routes require at least two vertices.")
    parsed: list[tuple[int, int]] = []
    for index, vertex in enumerate(vertices):
        if isinstance(vertex, (str, bytes, bytearray)) or not isinstance(vertex, Sequence) or len(vertex) != 2:
            raise _layout_error("route vertices require two coordinates.", vertex=index)
        parsed.append((_coordinate(vertex[0], f"vertices[{index}].x"), _coordinate(vertex[1], f"vertices[{index}].y")))
    for index, (left, right) in enumerate(zip(parsed, parsed[1:])):
        if left == right:
            raise _layout_error("route contains a zero-length segment.", segment=index)
        if left[0] != right[0] and left[1] != right[1]:
            raise _layout_error("route contains a diagonal segment.", segment=index)
    return tuple(parsed)


def _rectangle(value: Any, index: int) -> tuple[int, int, int, int]:
    if isinstance(value, Mapping):
        keys = {"left", "top", "right", "bottom"}
        if keys <= set(value):
            values = (value["left"], value["top"], value["right"], value["bottom"])
        elif {"x", "y", "width", "height"} <= set(value):
            x = _coordinate(value["x"], f"rectangles[{index}].x")
            y = _coordinate(value["y"], f"rectangles[{index}].y")
            width = _coordinate(value["width"], f"rectangles[{index}].width")
            height = _coordinate(value["height"], f"rectangles[{index}].height")
            values = (x, y, x + width, y + height)
        else:
            raise _layout_error("rectangle requires left/top/right/bottom.", rectangle=index)
    else:
        if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence) or len(value) != 4:
            raise _layout_error("rectangles require four coordinates.", rectangle=index)
        values = tuple(value)
    parsed = tuple(_coordinate(item, f"rectangles[{index}][{coordinate_index}]") for coordinate_index, item in enumerate(values))
    left, top, right, bottom = parsed
    if left == right or top == bottom:
        raise _layout_error("rectangles must have non-zero area.", rectangle=index)
    return (min(left, right), min(top, bottom), max(left, right), max(top, bottom))


def route_intersects_rectangles(vertices: Sequence[Sequence[int]], rectangles: Sequence[Any]) -> None:
    route = validate_orthogonal_route(vertices)
    for rectangle_index, rectangle_value in enumerate(rectangles):
        left, top, right, bottom = _rectangle(rectangle_value, rectangle_index)
        for point in route:
            if left < point[0] < right and top < point[1] < bottom:
                raise _layout_error("route enters a declared component rectangle.", rectangle=rectangle_index, point=list(point))
        for start, end in zip(route, route[1:]):
            if start[0] == end[0]:
                x = start[0]
                if left < x < right and max(top, min(start[1], end[1])) < min(bottom, max(start[1], end[1])):
                    raise _layout_error("route crosses a declared component rectangle.", rectangle=rectangle_index)
            else:
                y = start[1]
                if top < y < bottom and max(left, min(start[0], end[0])) < min(right, max(start[0], end[0])):
                    raise _layout_error("route crosses a declared component rectangle.", rectangle=rectangle_index)


__all__ = ["absolute_port", "route_intersects_rectangles", "transform_offset", "validate_orthogonal_route"]
