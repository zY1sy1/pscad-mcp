import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.routing import (
    absolute_port,
    route_intersects_rectangles,
    transform_offset,
    validate_orthogonal_route,
)


def test_transform_offset_covers_all_pscad_orientations():
    expected = {
        0: (12, 6),
        1: (-6, 12),
        2: (-12, -6),
        3: (6, -12),
        4: (-12, 6),
        5: (-6, -12),
        6: (12, -6),
        7: (6, 12),
    }

    for orientation, point in expected.items():
        assert transform_offset(12, 6, orientation) == point


def test_absolute_port_adds_origin_after_orientation_transform():
    assert absolute_port((100, 50), (12, 6), 1) == (94, 62)


@pytest.mark.parametrize("vertices", [[(0, 0)], [(0, 0), (0, 0)], [(0, 0), (1, 1)]])
def test_orthogonal_routes_reject_invalid_segments(vertices):
    with pytest.raises(BackendError) as raised:
        validate_orthogonal_route(vertices)
    assert raised.value.code == "LCC_LAYOUT_INVALID"


def test_orthogonal_routes_return_normalized_vertices():
    route = validate_orthogonal_route([(0, 0), (10, 0), (10, 5)])

    assert route == ((0, 0), (10, 0), (10, 5))


def test_route_intersection_rejects_crossing_component_rectangle():
    rectangles = [(4, -2, 6, 2)]

    with pytest.raises(BackendError) as raised:
        route_intersects_rectangles([(0, 0), (10, 0)], rectangles)
    assert raised.value.code == "LCC_LAYOUT_INVALID"


def test_route_intersection_allows_endpoint_on_rectangle_boundary():
    assert route_intersects_rectangles([(0, 0), (4, 0)], [(4, -2, 6, 2)]) is None

