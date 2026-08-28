from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .models import Point


class GeometryError(ValueError):
    pass


@dataclass(frozen=True)
class Segment:
    start: Point
    end: Point


@dataclass(frozen=True)
class Intersection:
    kind: Literal["none", "endpoint", "t_junction", "crossing", "overlap"]
    points: tuple[Point, ...] = ()


_TRANSFORMS = {
    0: lambda x, y: (x, y),
    1: lambda x, y: (-y, x),
    2: lambda x, y: (-x, -y),
    3: lambda x, y: (y, -x),
    4: lambda x, y: (-x, y),
    5: lambda x, y: (-y, -x),
    6: lambda x, y: (x, -y),
    7: lambda x, y: (y, x),
}


def absolute_port(origin, offset, orientation):
    try:
        transform = _TRANSFORMS[int(orientation)]
    except (KeyError, TypeError, ValueError) as error:
        raise GeometryError(f"unsupported orientation: {orientation}") from error
    dx, dy = transform(int(offset[0]), int(offset[1]))
    return int(origin[0]) + dx, int(origin[1]) + dy


def normalize_vertices(vertices) -> tuple[Point, ...]:
    normalized = tuple((int(point[0]), int(point[1])) for point in vertices)
    if len(normalized) < 2:
        raise GeometryError("at least two vertices are required")
    for start, end in zip(normalized, normalized[1:]):
        if start == end:
            raise GeometryError("zero-length segment is not allowed")
        if start[0] != end[0] and start[1] != end[1]:
            raise GeometryError("segments must be orthogonal")
    return normalized


def classify_intersection(left: Segment, right: Segment) -> Intersection:
    left = _normalized_segment(left)
    right = _normalized_segment(right)
    left_horizontal = left.start[1] == left.end[1]
    right_horizontal = right.start[1] == right.end[1]

    if left_horizontal == right_horizontal:
        return _classify_collinear(left, right, horizontal=left_horizontal)
    horizontal, vertical = (
        (left, right) if left_horizontal else (right, left)
    )
    point = (vertical.start[0], horizontal.start[1])
    if not (
        _between(point[0], horizontal.start[0], horizontal.end[0])
        and _between(point[1], vertical.start[1], vertical.end[1])
    ):
        return Intersection("none")
    return Intersection(
        _point_relation(point, left, right),
        (point,),
    )


def _normalized_segment(segment: Segment) -> Segment:
    start, end = normalize_vertices((segment.start, segment.end))
    return Segment(start, end)


def _classify_collinear(
    left: Segment,
    right: Segment,
    *,
    horizontal: bool,
) -> Intersection:
    fixed_axis = 1 if horizontal else 0
    varying_axis = 0 if horizontal else 1
    if left.start[fixed_axis] != right.start[fixed_axis]:
        return Intersection("none")

    overlap_start = max(
        min(left.start[varying_axis], left.end[varying_axis]),
        min(right.start[varying_axis], right.end[varying_axis]),
    )
    overlap_end = min(
        max(left.start[varying_axis], left.end[varying_axis]),
        max(right.start[varying_axis], right.end[varying_axis]),
    )
    if overlap_start > overlap_end:
        return Intersection("none")

    fixed = left.start[fixed_axis]
    first = (
        (overlap_start, fixed) if horizontal else (fixed, overlap_start)
    )
    if overlap_start == overlap_end:
        return Intersection(
            _point_relation(first, left, right),
            (first,),
        )
    last = (overlap_end, fixed) if horizontal else (fixed, overlap_end)
    return Intersection("overlap", tuple(sorted((first, last))))


def _point_relation(point: Point, left: Segment, right: Segment) -> str:
    left_endpoint = point in (left.start, left.end)
    right_endpoint = point in (right.start, right.end)
    if left_endpoint and right_endpoint:
        return "endpoint"
    if left_endpoint or right_endpoint:
        return "t_junction"
    return "crossing"


def _between(value: int, first: int, second: int) -> bool:
    return min(first, second) <= value <= max(first, second)
