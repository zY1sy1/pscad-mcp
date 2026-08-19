"""LCC compatibility names for the shared deterministic routing primitives."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Callable, TypeVar

from ....core.backend.base import BackendError
from ..common import routing as _common_routing


def _layout_error(message: str, **details: Any) -> BackendError:
    return BackendError("LCC_LAYOUT_INVALID", message, "hvdc", "validate_lcc_layout", details)


_T = TypeVar("_T")


def _lcc_layout(call: Callable[[], _T]) -> _T:
    try:
        return call()
    except BackendError as error:
        if error.code != "BUILDER_LAYOUT_INVALID":
            raise
        raise _layout_error(str(error), **error.details) from error


def transform_offset(x: int, y: int, orientation: int) -> tuple[int, int]:
    return _lcc_layout(lambda: _common_routing.transform_offset(x, y, orientation))


def absolute_port(origin: tuple[int, int], offset: tuple[int, int], orientation: int) -> tuple[int, int]:
    return _lcc_layout(lambda: _common_routing.absolute_port(origin, offset, orientation))


def validate_orthogonal_route(vertices: Sequence[Sequence[int]]) -> tuple[tuple[int, int], ...]:
    return _lcc_layout(lambda: _common_routing.validate_orthogonal_route(vertices))


def route_intersects_rectangles(vertices: Sequence[Sequence[int]], rectangles: Sequence[Any]) -> None:
    return _lcc_layout(lambda: _common_routing.route_intersects_rectangles(vertices, rectangles))


__all__ = ["absolute_port", "route_intersects_rectangles", "transform_offset", "validate_orthogonal_route"]
