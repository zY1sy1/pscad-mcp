from dataclasses import replace

from pscad_mcp.topology.connectivity import build_connectivity
from pscad_mcp.topology.models import (
    ProjectTopology,
    TopologyBoundaryLink,
    TopologyComponent,
    TopologyConductor,
    TopologyLabel,
    TopologyPort,
)


def _component(object_id, name, point, kind="electrical", dimension=1):
    key = f"Main:{object_id}"
    port = TopologyPort(
        key=f"{key}:{name}",
        component_key=key,
        name=name,
        absolute=point,
        kind=kind,
        dimension=dimension,
    )
    return TopologyComponent(
        key=key,
        canvas_key="Main",
        object_id=str(object_id),
        definition="test:component",
        location=point,
        ports=(port,),
    )


def test_vertices_ports_and_t_junction_form_one_confirmed_net():
    topology = ProjectTopology(
        project_name="case",
        pscad_version="4.6.2",
        components=(
            _component(1, "A", (0, 0)),
            _component(2, "B", (20, 0)),
        ),
        conductors=(
            TopologyConductor(
                "Main:10",
                "Main",
                "10",
                "wire",
                "electrical",
                ((0, 0), (20, 0)),
            ),
            TopologyConductor(
                "Main:11",
                "Main",
                "11",
                "wire",
                "electrical",
                ((10, 0), (10, 10)),
            ),
        ),
    )
    result = build_connectivity(topology)
    assert len(result.topology.nets) == 1
    assert result.topology.nets[0].port_keys == ("Main:1:A", "Main:2:B")
    assert result.ambiguous_crossings == ()

    reversed_topology = replace(
        topology,
        components=tuple(reversed(topology.components)),
        conductors=tuple(reversed(topology.conductors)),
    )
    assert build_connectivity(reversed_topology).topology.nets == result.topology.nets


def test_interior_crossing_is_reported_but_not_joined():
    topology = ProjectTopology(
        project_name="case",
        pscad_version="4.6.2",
        conductors=(
            TopologyConductor(
                "Main:10",
                "Main",
                "10",
                "wire",
                "electrical",
                ((0, 0), (20, 0)),
            ),
            TopologyConductor(
                "Main:11",
                "Main",
                "11",
                "wire",
                "electrical",
                ((10, -10), (10, 10)),
            ),
        ),
    )
    result = build_connectivity(topology)
    assert len(result.topology.nets) == 2
    assert result.ambiguous_crossings == (("Main:10", "Main:11", (10, 0)),)


def test_collinear_overlap_and_explicit_bus_touch_join():
    topology = ProjectTopology(
        project_name="case",
        pscad_version="4.6.2",
        conductors=(
            TopologyConductor(
                "Main:10", "Main", "10", "wire", "electrical", ((0, 0), (20, 0))
            ),
            TopologyConductor(
                "Main:11", "Main", "11", "wire", "electrical", ((10, 0), (30, 0))
            ),
            TopologyConductor(
                "Main:12", "Main", "12", "bus", "electrical", ((30, 0), (50, 0))
            ),
            TopologyConductor(
                "Main:13", "Main", "13", "wire", "electrical", ((40, 0), (40, 10))
            ),
        ),
    )
    result = build_connectivity(topology)
    assert len(result.topology.nets) == 1
    assert result.topology.nets[0].conductor_keys == (
        "Main:10",
        "Main:11",
        "Main:12",
        "Main:13",
    )


def test_bus_and_wire_interior_crossing_stays_separate():
    topology = ProjectTopology(
        project_name="case",
        pscad_version="4.6.2",
        conductors=(
            TopologyConductor(
                "Main:10", "Main", "10", "bus", "electrical", ((0, 0), (20, 0))
            ),
            TopologyConductor(
                "Main:11",
                "Main",
                "11",
                "wire",
                "electrical",
                ((10, -10), (10, 10)),
            ),
        ),
    )
    result = build_connectivity(topology)
    assert len(result.topology.nets) == 2
    assert result.ambiguous_crossings == (("Main:10", "Main:11", (10, 0)),)


def test_same_name_labels_join_only_inside_namespace_and_scope():
    labels = (
        TopologyLabel(
            "Main:20", "Main", "20", "NODE", "electrical", "Main", (0, 0)
        ),
        TopologyLabel(
            "Main:21", "Main", "21", "NODE", "electrical", "Main", (100, 0)
        ),
        TopologyLabel("Main:22", "Main", "22", "NODE", "data", "Main", (0, 20)),
    )
    conductors = tuple(
        TopologyConductor(
            f"Main:{30 + index}",
            "Main",
            str(30 + index),
            "wire",
            label.namespace,
            (label.location, (label.location[0] + 10, label.location[1])),
        )
        for index, label in enumerate(labels)
    )
    result = build_connectivity(
        ProjectTopology(
            "case", "4.6.2", conductors=conductors, labels=labels
        )
    )
    assert sorted(len(net.label_keys) for net in result.topology.nets) == [1, 2]


def test_explicit_page_port_link_joins_only_the_named_hierarchy_boundary():
    outer = _component(1, "IN", (20, 0))
    conductors = (
        TopologyConductor(
            "Main:10", "Main", "10", "wire", "electrical", ((0, 0), (20, 0))
        ),
        TopologyConductor(
            "Main/1:SubSystem:10",
            "Main/1:SubSystem",
            "10",
            "wire",
            "electrical",
            ((0, 0), (20, 0)),
        ),
    )
    boundary = TopologyBoundaryLink(
        key="Main:1:IN->Main/1:SubSystem:IN",
        outer_port_key="Main:1:IN",
        outer_canvas_key="Main",
        outer_point=(20, 0),
        inner_port_key="Main/1:SubSystem:IN",
        inner_canvas_key="Main/1:SubSystem",
        inner_point=(0, 0),
        namespace="electrical",
        dimension=1,
    )
    result = build_connectivity(
        ProjectTopology(
            "case",
            "4.6.2",
            components=(outer,),
            conductors=conductors,
            boundary_links=(boundary,),
        )
    )
    assert len(result.topology.nets) == 1
    assert result.topology.nets[0].conductor_keys == (
        "Main/1:SubSystem:10",
        "Main:10",
    )
    assert result.topology.nets[0].port_keys == (
        "Main/1:SubSystem:IN",
        "Main:1:IN",
    )


def test_boundary_link_with_mismatched_outer_port_point_fails_closed():
    outer = _component(1, "IN", (99, 0))
    conductors = (
        TopologyConductor(
            "Main:10", "Main", "10", "wire", "electrical", ((0, 0), (20, 0))
        ),
        TopologyConductor(
            "Main/1:SubSystem:10",
            "Main/1:SubSystem",
            "10",
            "wire",
            "electrical",
            ((0, 0), (20, 0)),
        ),
    )
    boundary = TopologyBoundaryLink(
        key="Main:1:IN->Main/1:SubSystem:IN",
        outer_port_key="Main:1:IN",
        outer_canvas_key="Main",
        outer_point=(20, 0),
        inner_port_key="Main/1:SubSystem:IN",
        inner_canvas_key="Main/1:SubSystem",
        inner_point=(0, 0),
        namespace="electrical",
        dimension=1,
    )
    result = build_connectivity(
        ProjectTopology(
            "case",
            "4.6.2",
            components=(outer,),
            conductors=conductors,
            boundary_links=(boundary,),
        )
    )
    assert len(result.topology.nets) == 2
    assert result.topology.unresolved == (
        "invalid_boundary_link:Main:1:IN->Main/1:SubSystem:IN",
    )


def test_malformed_and_unknown_namespace_conductors_fail_closed():
    component = TopologyComponent(
        key="Main:1",
        canvas_key="Main",
        object_id="1",
        definition="test:component",
        ports=(
            TopologyPort(
                key="Main:1:P",
                component_key="Main:1",
                name="P",
                absolute=None,
                kind="unknown",
            ),
        ),
    )
    topology = ProjectTopology(
        "case",
        "4.6.2",
        components=(component,),
        conductors=(
            TopologyConductor(
                "Main:bad", "Main", "bad", "wire", "electrical", ((0, 0),)
            ),
            TopologyConductor(
                "Main:unknown",
                "Main",
                "unknown",
                "wire",
                "unknown",
                ((0, 0), (18, 0)),
            ),
        ),
        labels=(
            TopologyLabel(
                "Main:label", "Main", "label", "X", "unknown", "Main", (36, 0)
            ),
        ),
    )
    result = build_connectivity(topology)
    assert result.topology.nets == ()
    assert result.malformed_conductors == ("Main:bad",)
    assert result.topology.unresolved == (
        "malformed_conductor:Main:bad",
        "missing_port_geometry:Main:1:P",
        "unknown_conductor_namespace:Main:unknown",
        "unknown_label_namespace:Main:label",
    )
