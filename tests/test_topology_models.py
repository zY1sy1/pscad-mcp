import json
from dataclasses import FrozenInstanceError, replace
from typing import get_type_hints

import pytest

from pscad_mcp.topology import (
    CandidateEdge,
    DiagnosticFinding,
    EvidenceRef,
    ProjectTopology,
    TopologyCanvas,
    TopologyComponent,
    TopologyNet,
    TopologyPort,
    TopologySnapshot,
    canonical_sha256,
    topology_sha256,
)


def _build_topology(*, observed_at_ns: int = 123) -> ProjectTopology:
    evidence = EvidenceRef(
        source="live",
        reference="Main:7",
        fingerprint="a" * 64,
        observed_at_ns=observed_at_ns,
    )
    port = TopologyPort(
        key="Main:7:A",
        component_key="Main:7",
        name="A",
        absolute=(10, 20),
        kind="electrical",
        dimension=1,
        evidence=(evidence,),
    )
    component = TopologyComponent(
        key="Main:7",
        canvas_key="Main",
        object_id="7",
        definition="master:resistor",
        location=(10, 20),
        ports=(port,),
        evidence=(evidence,),
    )
    candidates = (
        CandidateEdge(
            left="Main:7:A",
            right="Main:8:B",
            confidence=0.75,
            reasons=("same-coordinate",),
        ),
    )
    return ProjectTopology(
        project_name="case",
        pscad_version="4.6.2",
        project_path="C:/cases/case.pscx",
        canvases=(TopologyCanvas(key="Main", name="Main"),),
        components=(component,),
        candidate_edges=candidates,
        source_fingerprints=(("live", "b" * 64),),
        source_capabilities=(("live.components", True),),
        timings_ms=(("capture", 2.5),),
    )


def test_topology_records_are_json_safe_frozen_and_replace_compatible():
    topology = _build_topology()

    encoded = json.dumps(topology.to_dict(), sort_keys=True)

    assert json.loads(encoded)["components"][0]["ports"][0]["absolute"] == [10, 20]
    with pytest.raises(FrozenInstanceError):
        topology.project_name = "other"
    assert replace(topology, project_name="other").project_name == "other"


def test_topology_hash_excludes_unconfirmed_and_observation_metadata():
    topology = _build_topology(observed_at_ns=123)
    evidence = EvidenceRef(
        source="pscx",
        reference="different-reference",
        fingerprint="c" * 64,
        status="derived",
        observed_at_ns=999,
    )
    port = replace(topology.components[0].ports[0], evidence=(evidence,))
    component = replace(topology.components[0], ports=(port,), evidence=(evidence,))
    changed_metadata = replace(
        topology,
        project_path="D:/other/location.pscx",
        components=(component,),
        candidate_edges=(
            CandidateEdge(
                left="unresolved:left",
                right="unresolved:right",
                confidence=0.01,
                reasons=("different",),
                counter_evidence=("missing-port",),
            ),
        ),
        source_fingerprints=(("pscx", "d" * 64),),
        source_capabilities=(("pscx.components", True),),
        timings_ms=(("capture", 999.0),),
    )

    payload = changed_metadata.confirmed_payload()

    assert "project_path" not in payload
    assert "candidate_edges" not in payload
    assert "source_fingerprints" not in payload
    assert "source_capabilities" not in payload
    assert "timings_ms" not in payload
    assert "evidence" not in json.dumps(payload)
    assert "observed_at_ns" not in json.dumps(payload)
    assert topology_sha256(topology) == topology_sha256(changed_metadata)


def test_topology_hash_is_stable_under_reversed_topology_collections():
    topology = _build_topology()
    evidence = topology.components[0].evidence
    second_ports = (
        TopologyPort(
            key="Main:8:B",
            component_key="Main:8",
            name="B",
            absolute=(30, 20),
            kind="electrical",
            dimension=1,
            evidence=evidence,
        ),
        TopologyPort(
            key="Main:8:A",
            component_key="Main:8",
            name="A",
            absolute=(20, 20),
            kind="electrical",
            dimension=1,
            evidence=evidence,
        ),
    )
    second = TopologyComponent(
        key="Main:8",
        canvas_key="Main",
        object_id="8",
        definition="master:resistor",
        parameters=(("z", {"nested": True}), ("a", 1)),
        ports=second_ports,
        evidence=evidence,
    )
    net = TopologyNet(
        key="electrical:1",
        namespace="electrical",
        port_keys=("Main:8:B", "Main:7:A", "Main:8:A"),
        conductor_keys=("wire:2", "wire:1"),
        label_keys=("label:z", "label:a"),
        junctions=((30, 20), (10, 20)),
    )
    ordered = replace(
        topology,
        components=(topology.components[0], second),
        nets=(net,),
        unresolved=("z:item", "a:item"),
    )
    reversed_collections = replace(
        ordered,
        canvases=tuple(reversed(ordered.canvases)),
        components=tuple(
            replace(
                component,
                ports=tuple(reversed(component.ports)),
                parameters=tuple(reversed(component.parameters)),
            )
            for component in reversed(ordered.components)
        ),
        nets=(
            replace(
                net,
                port_keys=tuple(reversed(net.port_keys)),
                conductor_keys=tuple(reversed(net.conductor_keys)),
                label_keys=tuple(reversed(net.label_keys)),
                junctions=tuple(reversed(net.junctions)),
            ),
        ),
        unresolved=tuple(reversed(ordered.unresolved)),
    )

    assert topology_sha256(ordered) == topology_sha256(reversed_collections)


def test_canonical_sha256_preserves_generic_list_order():
    assert canonical_sha256(["a", "b"]) != canonical_sha256(["b", "a"])


def test_component_orientation_uses_pscad_integer_codes():
    assert get_type_hints(TopologyComponent)["orientation"] == int | None


def test_diagnostic_and_capability_annotations_match_public_contracts():
    assert get_type_hints(DiagnosticFinding)["evidence"] == tuple[str, ...]
    assert get_type_hints(TopologySnapshot)["capabilities"] == tuple[
        tuple[str, bool], ...
    ]
    assert get_type_hints(ProjectTopology)["source_capabilities"] == tuple[
        tuple[str, bool], ...
    ]
