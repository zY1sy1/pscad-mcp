from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from pscad_mcp.builders.blueprint.corpus_extractor import (
    extract_project,
    graph_signature,
)
from pscad_mcp.builders.blueprint.corpus_models import CorpusSource, CorpusSpec
from pscad_mcp.builders.blueprint.corpus_relations import build_relationship_truth
from pscad_mcp.builders.blueprint.corpus_writer import parse_project_graph
from pscad_mcp.topology.connectivity import build_connectivity
from pscad_mcp.topology.hashing import topology_sha256
from pscad_mcp.topology.models import ProjectTopology
from pscad_mcp.topology.providers.pscx import PscxSnapshotProvider

FIXTURES = Path(__file__).parent / "fixtures" / "blueprint_corpus"


def _arrange(tmp_path):
    source_path = tmp_path / "repeated-module-v2.pscx"
    source_path.write_bytes((FIXTURES / source_path.name).read_bytes())
    payload = source_path.read_bytes()
    source = CorpusSource(
        project_id="repeated-module-v2",
        basename=source_path.name,
        byte_length=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        pscad_versions=("4.6.2",),
        dependencies=(),
    )
    spec = CorpusSpec(
        schema_version=2,
        normalization_profile="pscad-xml-v2",
        name="fixture-v2",
        inclusion_policy="explicit-entry-points-v1",
        exclusion_policy="no-backups-builds-results-v1",
        entry_points=(source,),
        definition_sources=(),
    )
    graph = extract_project(
        tmp_path,
        source,
        schema_version=2,
        normalization_profile="pscad-xml-v2",
    )
    return source_path, spec, graph


def _project_topology(snapshot):
    return ProjectTopology(
        project_name=snapshot.project_name,
        pscad_version=snapshot.pscad_version,
        project_path=snapshot.project_path,
        canvases=snapshot.canvases,
        components=snapshot.components,
        conductors=snapshot.conductors,
        labels=snapshot.labels,
        boundary_links=snapshot.boundary_links,
        unresolved=snapshot.unresolved,
        source_fingerprints=((snapshot.source, snapshot.source_fingerprint or ""),),
        source_capabilities=snapshot.capabilities,
        grid_step=snapshot.grid_step,
    )


def _definition_name(value: str) -> str:
    return value.rsplit(":", 1)[-1].casefold()


def _structural_topology_projection(topology):
    component_by_port = {
        port.key: (
            _definition_name(component.definition),
            component.name or "",
            component.location,
            port.name,
            port.absolute,
            port.kind,
            port.dimension,
        )
        for component in topology.components
        for port in component.ports
    }
    conductor_by_key = {
        item.key: (item.kind, item.namespace, item.vertices)
        for item in topology.conductors
    }
    label_by_key = {
        item.key: (item.name, item.namespace, item.location)
        for item in topology.labels
    }
    return tuple(
        sorted(
            (
                net.namespace,
                tuple(sorted(component_by_port[key] for key in net.port_keys if key in component_by_port)),
                tuple(sorted(conductor_by_key[key] for key in net.conductor_keys)),
                tuple(sorted(label_by_key[key] for key in net.label_keys)),
                net.junctions,
            )
            for net in topology.nets
        )
    )


def test_corpus_projection_matches_canonical_confirmed_topology(tmp_path):
    source_path, spec, raw = _arrange(tmp_path)
    snapshot = PscxSnapshotProvider().read(source_path, "Main")
    expected = build_connectivity(_project_topology(snapshot)).topology

    projected = build_relationship_truth(raw, spec, {}, infer=False)

    assert _structural_topology_projection(projected.topology) == (
        _structural_topology_projection(expected)
    )
    assert projected.confirmed_topology_hash == topology_sha256(projected.topology)
    assert projected.graph.confirmed_nets
    assert projected.graph.port_net_memberships
    assert len(projected.graph.hierarchy_relations) == 2
    net_keys_by_port = {
        port_key: net.key
        for net in projected.graph.confirmed_nets
        for port_key in net.port_keys
    }
    assert all(
        net_keys_by_port[item.outer_port_key]
        == net_keys_by_port[item.inner_port_key]
        for item in projected.graph.hierarchy_relations
    )
    assert parse_project_graph(projected.graph.to_dict()) == projected.graph


def test_candidate_edges_do_not_change_confirmed_relationship_signature(tmp_path):
    _source_path, spec, raw = _arrange(tmp_path)
    main_wire = next(
        item
        for item in raw.connections
        if item.canvas_key == "canvas:main" and item.kind != "hierarchy"
    )
    nearby = replace(
        raw,
        connections=tuple(
            replace(item, vertices=((90, 0), (108, 0)))
            if item.key == main_wire.key
            else item
            for item in raw.connections
        ),
    )

    conservative = build_relationship_truth(nearby, spec, {}, infer=False).graph
    inferred = build_relationship_truth(nearby, spec, {}, infer=True).graph

    assert conservative.candidate_edges == ()
    assert inferred.candidate_edges
    assert conservative.confirmed_relation_signature == (
        inferred.confirmed_relation_signature
    )
    assert graph_signature(conservative) != graph_signature(inferred)
