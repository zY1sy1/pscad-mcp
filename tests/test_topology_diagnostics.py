from collections import Counter
from dataclasses import replace
import time

import pytest

from pscad_mcp.topology.diagnostics.generic import (
    diagnose_generic,
    infer_candidate_edges,
)
from pscad_mcp.topology.hashing import topology_sha256
from pscad_mcp.topology.connectivity import build_connectivity
from pscad_mcp.topology.models import (
    ProjectTopology,
    TopologyBoundaryLink,
    TopologyComponent,
    TopologyConductor,
    TopologyPort,
)
from tests.topology_fakes import (
    topology_with_candidate_only_connection,
    topology_with_incompatible_nearby_ports,
    topology_with_nearby_dangling_endpoint,
    topology_with_seeded_defects,
    topology_with_unconnected_ports,
)


def test_required_and_optional_unconnected_ports_have_distinct_severity():
    topology = topology_with_unconnected_ports(required=True, optional=True)
    findings = diagnose_generic(topology)
    by_code = {item.code: item for item in findings}
    assert by_code["REQUIRED_PORT_UNCONNECTED"].severity == "error"
    assert by_code["PORT_UNCONNECTED"].severity == "info"


def test_generic_rules_report_all_confirmed_structural_defects():
    topology = topology_with_seeded_defects()
    codes = {item.code for item in diagnose_generic(topology)}
    assert {
        "WIRE_DANGLING_ENDPOINT",
        "ISOLATED_NETWORK",
        "PORT_KIND_MISMATCH",
        "PORT_DIMENSION_MISMATCH",
        "CROSSING_AMBIGUOUS",
        "LABEL_CONFLICT",
        "SOURCE_CONFLICT",
    } <= codes


def test_generic_findings_follow_fixed_rule_order():
    topology = replace(
        topology_with_seeded_defects(),
        unresolved=("live_hierarchy_unavailable:Main/7:SubSystem",),
    )
    codes = [item.code for item in diagnose_generic(topology)]
    first_occurrences = list(dict.fromkeys(codes))
    assert first_occurrences == [
        "PORT_UNCONNECTED",
        "WIRE_DANGLING_ENDPOINT",
        "ISOLATED_NETWORK",
        "PORT_KIND_MISMATCH",
        "PORT_DIMENSION_MISMATCH",
        "CROSSING_AMBIGUOUS",
        "LABEL_CONFLICT",
        "SOURCE_CONFLICT",
        "TOPOLOGY_INCOMPLETE",
    ]


def test_generic_findings_use_exact_public_contracts():
    findings = list(diagnose_generic(topology_with_seeded_defects()))
    findings.extend(
        diagnose_generic(
            topology_with_unconnected_ports(required=True, optional=True)
        )
    )
    findings.extend(
        diagnose_generic(
            replace(
                topology_with_unconnected_ports(
                    required=False,
                    optional=False,
                ),
                unresolved=("missing:item",),
            )
        )
    )
    expected = {
        "PORT_UNCONNECTED": (
            "info",
            "derived",
            "Review the port contract and connect it manually if the design requires it.",
        ),
        "REQUIRED_PORT_UNCONNECTED": (
            "error",
            "derived",
            "Connect the required port manually or correct its audited definition contract.",
        ),
        "WIRE_DANGLING_ENDPOINT": (
            "error",
            "derived",
            "Inspect the endpoint and add or correct the intended connection manually.",
        ),
        "ISOLATED_NETWORK": (
            "warning",
            "derived",
            "Review the isolated conductors and remove or connect them manually.",
        ),
        "PORT_KIND_MISMATCH": (
            "error",
            "conflict",
            "Correct the port or conductor type before connecting them.",
        ),
        "PORT_DIMENSION_MISMATCH": (
            "error",
            "conflict",
            "Correct the port dimensions or split the net manually.",
        ),
        "CROSSING_AMBIGUOUS": (
            "warning",
            "unresolved",
            "Add an explicit junction or reroute one conductor to make intent clear.",
        ),
        "LABEL_CONFLICT": (
            "error",
            "conflict",
            "Rename or correct the conflicting labels manually.",
        ),
        "SOURCE_CONFLICT": (
            "warning",
            "conflict",
            "Review unsaved canvas changes and the saved project before relying on this field.",
        ),
        "TOPOLOGY_INCOMPLETE": (
            "warning",
            "unresolved",
            "Inspect the reported capability or source gaps before validating the project.",
        ),
    }
    by_code = {item.code: item for item in findings}
    assert set(by_code) == set(expected)
    for code, (severity, status, action) in expected.items():
        finding = by_code[code]
        assert (finding.severity, finding.status, finding.confidence) == (
            severity,
            status,
            1.0,
        )
        assert finding.suggested_action == action

    assert by_code["REQUIRED_PORT_UNCONNECTED"].message == (
        "Required active port 'Main:1:P' has no confirmed net."
    )
    assert by_code["CROSSING_AMBIGUOUS"].message == (
        "Conductors cross at '(320,0)' without explicit junction evidence."
    )
    assert by_code["SOURCE_CONFLICT"].message == (
        "Live and saved evidence disagree for 'Main:1'."
    )
    assert by_code["TOPOLOGY_INCOMPLETE"].message == (
        "Topology evidence is incomplete for 1 source items."
    )


def test_finding_evidence_is_sorted_and_capped_at_fifty_items():
    topology = replace(
        topology_with_unconnected_ports(required=False, optional=False),
        unresolved=tuple(f"gap:{index:02d}" for index in reversed(range(52))),
    )
    finding = diagnose_generic(topology)[0]
    assert len(finding.evidence) == 50
    assert finding.evidence[:-1] == tuple(
        f"gap:{index:02d}" for index in range(49)
    )
    assert finding.evidence[-1] == "evidence_truncated:3"


def test_inference_never_changes_confirmed_nets_or_hash():
    topology = topology_with_nearby_dangling_endpoint(grid_step=18)
    candidates = infer_candidate_edges(topology)
    inferred = replace(topology, candidate_edges=candidates)
    assert candidates[0].confidence < 1.0
    assert candidates[0].reasons == (
        "nearby compatible dangling endpoint",
    )
    assert inferred.nets == topology.nets
    assert topology_sha256(inferred) == topology_sha256(topology)


def test_inference_rejects_cross_namespace_and_dimension_mismatch():
    topology = topology_with_incompatible_nearby_ports()
    assert infer_candidate_edges(topology) == ()


def test_candidate_edges_do_not_suppress_conservative_findings():
    topology = topology_with_candidate_only_connection()
    codes = {item.code for item in diagnose_generic(topology)}
    assert "PORT_UNCONNECTED" in codes
    assert "WIRE_DANGLING_ENDPOINT" in codes


def test_unresolved_source_evidence_produces_incomplete_finding():
    topology = replace(
        topology_with_unconnected_ports(required=False, optional=False),
        unresolved=("live_hierarchy_unavailable:Main/7:SubSystem",),
    )
    findings = diagnose_generic(topology)
    assert [item.code for item in findings] == ["TOPOLOGY_INCOMPLETE"]
    assert findings[0].status == "unresolved"


def test_unresolved_hierarchy_boundary_does_not_claim_required_port_is_open():
    boundary = TopologyBoundaryLink(
        key="Main:1:P->Main/1:Child:P",
        outer_port_key="Main:1:P",
        outer_canvas_key="Main",
        outer_point=(0, 0),
        inner_port_key="Main/1:Child:P",
        inner_canvas_key="Main/1:Child",
        inner_point=(0, 0),
        namespace="electrical",
        dimension=1,
    )
    topology = replace(
        topology_with_unconnected_ports(required=True, optional=False),
        boundary_links=(boundary,),
        unresolved=(f"hierarchy_boundary_unresolved:{boundary.key}",),
    )

    findings = diagnose_generic(topology)

    assert [item.code for item in findings] == ["TOPOLOGY_INCOMPLETE"]


def test_unknown_namespace_evidence_stays_unresolved_and_is_not_inferred():
    component = TopologyComponent(
        key="Main:1",
        canvas_key="Main",
        object_id="1",
        definition="test:unknown",
        ports=(
            TopologyPort(
                key="Main:1:P",
                component_key="Main:1",
                name="P",
                absolute=(18, 0),
                kind="unknown",
            ),
        ),
    )
    topology = build_connectivity(
        ProjectTopology(
            "case",
            "4.6.2",
            components=(component,),
            conductors=(
                TopologyConductor(
                    "Main:10",
                    "Main",
                    "10",
                    "wire",
                    "unknown",
                    ((0, 0), (0, 18)),
                ),
            ),
            grid_step=18,
        )
    ).topology

    assert infer_candidate_edges(topology) == ()
    assert [item.code for item in diagnose_generic(topology)] == [
        "PORT_UNCONNECTED",
        "TOPOLOGY_INCOMPLETE",
    ]


def scale_topology(object_count):
    pair_count = object_count // 2
    components = []
    conductors = []
    for index in range(pair_count):
        y = index * 18
        component_key = f"Main:C{index:04d}"
        components.append(
            TopologyComponent(
                key=component_key,
                canvas_key="Main",
                object_id=f"C{index:04d}",
                definition="test:load",
                location=(0, y),
                ports=(
                    TopologyPort(
                        key=f"{component_key}:P",
                        component_key=component_key,
                        name="P",
                        absolute=(0, y),
                        kind="electrical",
                        dimension=1,
                        required=True,
                    ),
                ),
            )
        )
        conductors.append(
            TopologyConductor(
                key=f"Main:W{index:04d}",
                canvas_key="Main",
                object_id=f"W{index:04d}",
                kind="wire",
                namespace="electrical",
                vertices=((0, y), (18, y)),
            )
        )
    return ProjectTopology(
        "case",
        "4.6.2",
        components=tuple(components),
        conductors=tuple(conductors),
        grid_step=18,
    )


@pytest.mark.parametrize(
    ("object_count", "dangling_count"),
    [(500, 250), (2000, 1000)],
)
def test_scale_topology_is_deterministic_with_exact_defect_counts(
    object_count,
    dangling_count,
):
    source = scale_topology(object_count)
    started = time.perf_counter()
    forward = build_connectivity(source).topology
    findings = diagnose_generic(forward)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    reversed_source = replace(
        source,
        components=tuple(reversed(source.components)),
        conductors=tuple(reversed(source.conductors)),
    )
    reversed_topology = build_connectivity(reversed_source).topology

    assert topology_sha256(forward) == topology_sha256(reversed_topology)
    assert Counter(item.code for item in findings) == {
        "WIRE_DANGLING_ENDPOINT": dangling_count,
    }
    assert elapsed_ms >= 0.0
