from pscad_mcp.topology.models import (
    EvidenceRef,
    TopologyBoundaryLink,
    TopologyCanvas,
    TopologyComponent,
    TopologyConductor,
    TopologyPort,
    TopologySnapshot,
)
from pscad_mcp.topology.reconcile import reconcile_snapshots


def _component(source, object_id, *, location, kind="unknown", dimension=None):
    key = f"Main:{object_id}"
    evidence = (EvidenceRef(source, key),)
    return TopologyComponent(
        key=key,
        canvas_key="Main",
        object_id=str(object_id),
        definition="master:resistor",
        location=location,
        ports=(
            TopologyPort(
                key=f"{key}:A",
                component_key=key,
                name="A",
                absolute=location,
                kind=kind,
                dimension=dimension,
                evidence=evidence,
            ),
        ),
        evidence=evidence,
    )


def test_live_state_wins_and_conflicting_saved_location_is_preserved():
    live = TopologySnapshot(
        "live",
        "case",
        project_path="C:/workspace/case.pscx",
        pscad_version="4.6.2",
        components=(_component("live", 7, location=(20, 0)),),
        capabilities=(("components", True), ("hierarchy", False)),
        source_fingerprint="l" * 64,
        grid_step=18,
    )
    saved = TopologySnapshot(
        "pscx",
        "case",
        components=(
            _component(
                "pscx",
                7,
                location=(10, 0),
                kind="electrical",
                dimension=1,
            ),
        ),
        source_fingerprint="s" * 64,
    )
    topology = reconcile_snapshots(live, saved)
    assert topology.components[0].location == (20, 0)
    assert topology.components[0].ports[0].kind == "electrical"
    assert "location" in {conflict.field for conflict in topology.conflicts}
    assert topology.source_fingerprints == (
        ("live", "l" * 64),
        ("pscx", "s" * 64),
    )
    assert topology.project_path == "C:/workspace/case.pscx"
    assert topology.pscad_version == "4.6.2"
    assert topology.grid_step == 18
    assert topology.source_capabilities == (
        ("live.components", True),
        ("live.hierarchy", False),
    )


def test_saved_only_objects_are_stale_and_excluded_from_effective_graph():
    live = TopologySnapshot(
        "live",
        "case",
        components=(_component("live", 7, location=(0, 0)),),
    )
    saved = TopologySnapshot(
        "pscx",
        "case",
        components=(_component("pscx", 8, location=(10, 0)),),
    )
    topology = reconcile_snapshots(live, saved)
    assert [component.object_id for component in topology.components] == ["7"]
    assert "stale_file_evidence:Main:8" in topology.unresolved


def test_file_only_conductor_is_not_current_when_live_did_not_observe_it():
    live = TopologySnapshot("live", "case")
    saved = TopologySnapshot(
        "pscx",
        "case",
        conductors=(
            TopologyConductor(
                "Main:9",
                "Main",
                "9",
                "wire",
                "electrical",
                ((0, 0), (18, 0)),
            ),
        ),
    )
    topology = reconcile_snapshots(live, saved)
    assert topology.conductors == ()
    assert "stale_file_evidence:Main:9" in topology.unresolved


def test_file_only_mode_preserves_all_saved_objects():
    saved = TopologySnapshot(
        "pscx",
        "case",
        components=(_component("pscx", 8, location=(10, 0)),),
    )
    topology = reconcile_snapshots(None, saved)
    assert [component.object_id for component in topology.components] == ["8"]


def test_file_only_mode_preserves_explicit_hierarchy_boundary_links():
    boundary = TopologyBoundaryLink(
        key="Main:7:IN->Main/7:SubSystem:IN",
        outer_port_key="Main:7:IN",
        outer_canvas_key="Main",
        outer_point=(18, 0),
        inner_port_key="Main/7:SubSystem:IN",
        inner_canvas_key="Main/7:SubSystem",
        inner_point=(0, 0),
        namespace="electrical",
    )
    saved = TopologySnapshot(
        "pscx",
        "case",
        canvases=(
            TopologyCanvas("Main", "Main"),
            TopologyCanvas(
                "Main/7:SubSystem",
                "SubSystem",
                parent_key="Main",
                page_ports=("Main/7:SubSystem:IN",),
            ),
        ),
        boundary_links=(boundary,),
    )
    topology = reconcile_snapshots(None, saved)
    assert topology.boundary_links == (boundary,)


def test_live_only_and_unconfirmed_hierarchy_evidence_remain_unresolved():
    boundary = TopologyBoundaryLink(
        key="Main:7:IN->Main/7:SubSystem:IN",
        outer_port_key="Main:7:IN",
        outer_canvas_key="Main",
        outer_point=(18, 0),
        inner_port_key="Main/7:SubSystem:IN",
        inner_canvas_key="Main/7:SubSystem",
        inner_point=(0, 0),
        namespace="electrical",
    )
    live = TopologySnapshot(
        "live",
        "case",
        canvases=(TopologyCanvas("Main", "Main"),),
        components=(_component("live", 7, location=(18, 0)),),
    )
    saved = TopologySnapshot(
        "pscx",
        "case",
        canvases=(
            TopologyCanvas("Main", "Main"),
            TopologyCanvas(
                "Main/7:SubSystem", "SubSystem", parent_key="Main"
            ),
        ),
        boundary_links=(boundary,),
    )
    topology = reconcile_snapshots(live, saved)
    assert topology.boundary_links == ()
    assert topology.unresolved == (
        "hierarchy_boundary_unconfirmed:Main:7:IN->Main/7:SubSystem:IN",
        "unsaved_live_evidence:Main:7",
    )


def test_live_only_boundary_link_is_reported_as_unsaved_evidence():
    boundary = TopologyBoundaryLink(
        key="Main:7:IN->Main/7:SubSystem:IN",
        outer_port_key="Main:7:IN",
        outer_canvas_key="Main",
        outer_point=(18, 0),
        inner_port_key="Main/7:SubSystem:IN",
        inner_canvas_key="Main/7:SubSystem",
        inner_point=(0, 0),
        namespace="electrical",
    )
    live = TopologySnapshot(
        "live", "case", boundary_links=(boundary,)
    )
    topology = reconcile_snapshots(live, None)
    assert topology.boundary_links == (boundary,)
    assert topology.unresolved == (
        "unsaved_live_evidence:Main:7:IN->Main/7:SubSystem:IN",
    )
