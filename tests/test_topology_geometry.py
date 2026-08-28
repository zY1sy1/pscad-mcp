import pytest

from pscad_mcp.topology.geometry import (
    GeometryError,
    Segment,
    absolute_port,
    classify_intersection,
    normalize_vertices,
)


def test_absolute_port_supports_all_legacy_orientation_codes():
    expected = {
        0: (13, 22),
        1: (8, 23),
        2: (7, 18),
        3: (12, 17),
        4: (7, 22),
        5: (8, 17),
        6: (13, 18),
        7: (12, 23),
    }
    assert {
        code: absolute_port((10, 20), (3, 2), code) for code in range(8)
    } == expected


def test_segment_relations_distinguish_t_junction_crossing_and_overlap():
    horizontal = Segment((0, 0), (20, 0))
    t_junction = classify_intersection(
        horizontal, Segment((10, 0), (10, 10))
    )
    crossing = classify_intersection(
        horizontal, Segment((10, -10), (10, 10))
    )
    overlap = classify_intersection(horizontal, Segment((5, 0), (25, 0)))
    assert (t_junction.kind, t_junction.points) == (
        "t_junction",
        ((10, 0),),
    )
    assert (crossing.kind, crossing.points) == ("crossing", ((10, 0),))
    assert (overlap.kind, overlap.points) == (
        "overlap",
        ((5, 0), (20, 0)),
    )


def test_endpoint_touch_and_non_intersection_are_classified_explicitly():
    horizontal = Segment((0, 0), (20, 0))
    endpoint = classify_intersection(horizontal, Segment((20, 0), (20, 10)))
    disjoint = classify_intersection(horizontal, Segment((30, 0), (30, 10)))
    assert (endpoint.kind, endpoint.points) == ("endpoint", ((20, 0),))
    assert (disjoint.kind, disjoint.points) == ("none", ())


def test_normalize_vertices_rejects_diagonal_and_zero_length_segments():
    with pytest.raises(GeometryError, match="orthogonal"):
        normalize_vertices(((0, 0), (1, 1)))
    with pytest.raises(GeometryError, match="zero-length"):
        normalize_vertices(((0, 0), (0, 0)))


def test_absolute_port_rejects_unsupported_orientation():
    with pytest.raises(GeometryError, match="unsupported orientation"):
        absolute_port((0, 0), (1, 1), 8)
