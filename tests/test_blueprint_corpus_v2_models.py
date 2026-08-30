from __future__ import annotations

from dataclasses import replace

import pytest

from pscad_mcp.builders.blueprint.corpus_models import (
    CorpusCanvas,
    CorpusComponent,
    CorpusConnection,
    ProjectGraph,
)
from pscad_mcp.builders.blueprint.corpus_relation_models import (
    CorpusCandidateEdge,
    CorpusComponentOccurrence,
    CorpusConductorOccurrence,
    CorpusConfirmedNet,
    CorpusDefinitionClassification,
    CorpusHierarchyRelation,
    CorpusInstancePort,
    CorpusLabelOccurrence,
    CorpusPortNetMembership,
    CorpusUnresolvedEvidence,
)
from pscad_mcp.builders.blueprint.corpus_writer import parse_project_graph
from pscad_mcp.builders.blueprint.models import freeze
from pscad_mcp.core.backend.base import BackendError


def relation_graph() -> ProjectGraph:
    components = (
        CorpusComponent(
            "source:left",
            "canvas:main",
            "definition:master:gain",
            "LEFT",
            (0, 0),
            0,
            freeze({"View": "0"}),
            True,
        ),
        CorpusComponent(
            "source:right",
            "canvas:child",
            "definition:master:gain",
            "RIGHT",
            (36, 0),
            0,
            freeze({"View": "0"}),
            True,
        ),
        CorpusComponent(
            "source:label",
            "canvas:main",
            "definition:master:datalabel",
            "ENABLE",
            (18, 0),
            0,
            freeze({"Name": "ENABLE"}),
            True,
        ),
    )
    connection = CorpusConnection(
        "source:wire",
        "canvas:main",
        "wireorthogonal",
        ((0, 0), (36, 0)),
        (),
        None,
        "geometry_only",
    )
    left_port = CorpusInstancePort(
        "occurrence:left/port:out#0",
        "occurrence:left",
        "source:left",
        "definition:master:gain/port:out#0",
        "OUT",
        0,
        (18, 0),
        (18, 0),
        "data",
        1,
        True,
        "0" * 64,
    )
    right_port = CorpusInstancePort(
        "occurrence:right/port:in#0",
        "occurrence:right",
        "source:right",
        "definition:master:gain/port:in#0",
        "IN",
        0,
        (-18, 0),
        (18, 0),
        "data",
        1,
        True,
        "0" * 64,
    )
    net_key = "e" * 64
    return ProjectGraph(
        project_id="fixture-v2",
        source_sha256="0" * 64,
        dependency_hashes=freeze({}),
        name="FixtureV2",
        pscad_version="4.6.2",
        target="EMTDC",
        settings=freeze({}),
        canvases=(
            CorpusCanvas("canvas:main", "Main", "definition:user:main", "usercanvas"),
            CorpusCanvas("canvas:child", "Child", "definition:user:child", "usercanvas"),
        ),
        components=components,
        connections=(connection,),
        schema_version=2,
        normalization_profile="pscad-xml-v2",
        definition_classifications=(
            CorpusDefinitionClassification(
                "definition:master:gain",
                "master",
                "4.6.2",
                "gain",
                "port_bearing",
                (
                    "definition:master:gain/port:in#0",
                    "definition:master:gain/port:out#0",
                ),
                "0" * 64,
            ),
            CorpusDefinitionClassification(
                "definition:master:datalabel",
                "master",
                "4.6.2",
                "datalabel",
                "port_bearing",
                ("definition:master:datalabel/port:label#0",),
                "0" * 64,
            ),
        ),
        component_occurrences=(
            CorpusComponentOccurrence(
                "occurrence:left",
                "source:left",
                "occurrence:canvas:main",
                "canvas:main",
                "definition:master:gain",
                ("project:fixture-v2",),
                "LEFT",
                (0, 0),
                0,
                freeze({"View": "0"}),
            ),
            CorpusComponentOccurrence(
                "occurrence:right",
                "source:right",
                "occurrence:canvas:child",
                "canvas:child",
                "definition:master:gain",
                ("project:fixture-v2", "source:right"),
                "RIGHT",
                (36, 0),
                0,
                freeze({"View": "0"}),
            ),
        ),
        conductor_occurrences=(
            CorpusConductorOccurrence(
                "occurrence:wire",
                "source:wire",
                "occurrence:canvas:main",
                "wire",
                "data",
                ((0, 0), (36, 0)),
            ),
        ),
        label_occurrences=(
            CorpusLabelOccurrence(
                "occurrence:label",
                "source:label",
                "occurrence:canvas:main",
                "ENABLE",
                "data",
                "occurrence:canvas:main",
                (18, 0),
            ),
        ),
        instance_ports=(left_port, right_port),
        confirmed_nets=(
            CorpusConfirmedNet(
                net_key,
                "data",
                (left_port.key, right_port.key),
                ("occurrence:wire",),
                ("occurrence:label",),
                ((0, 0), (18, 0), (36, 0)),
            ),
        ),
        port_net_memberships=(
            CorpusPortNetMembership(
                "membership:left",
                "occurrence:left",
                left_port.key,
                net_key,
                "data",
            ),
            CorpusPortNetMembership(
                "membership:right",
                "occurrence:right",
                right_port.key,
                net_key,
                "data",
            ),
        ),
        hierarchy_relations=(
            CorpusHierarchyRelation(
                "hierarchy:left-right",
                "occurrence:left",
                "occurrence:canvas:child",
                left_port.key,
                right_port.key,
                "data",
                1,
            ),
        ),
        candidate_edges=(
            CorpusCandidateEdge(
                "occurrence:wire@36,0",
                right_port.key,
                0.75,
                ("nearby compatible dangling endpoint",),
                (),
            ),
        ),
        unresolved_evidence=(
            CorpusUnresolvedEvidence(
                "CROSSING_AMBIGUOUS",
                ("occurrence:wire",),
                ("source:wire",),
                "engineering",
            ),
        ),
        confirmed_relation_signature="d" * 64,
        definition_catalog_signature="c" * 64,
    )


def test_v2_graph_round_trips_every_relation_record():
    graph = relation_graph()

    reparsed = parse_project_graph(graph.to_dict())

    assert reparsed == graph
    assert reparsed.schema_version == 2
    assert reparsed.confirmed_nets[0].port_keys == (
        "occurrence:left/port:out#0",
        "occurrence:right/port:in#0",
    )


def test_v1_graph_round_trip_omits_v2_fields():
    graph = ProjectGraph(
        project_id="fixture-v1",
        source_sha256="0" * 64,
        dependency_hashes=freeze({}),
        name="FixtureV1",
        pscad_version="4.6.2",
        target="EMTDC",
        settings=freeze({}),
    )

    value = graph.to_dict()
    reparsed = parse_project_graph(value)

    assert "schema_version" not in value
    assert reparsed.schema_version == 1
    assert reparsed.component_occurrences == ()
    assert reparsed.to_dict() == value


def test_v2_graph_rejects_a_membership_with_a_missing_net():
    graph = relation_graph()
    broken = replace(
        graph,
        port_net_memberships=(
            replace(graph.port_net_memberships[0], net_key="f" * 64),
        ),
    )

    with pytest.raises(BackendError) as raised:
        parse_project_graph(broken.to_dict())

    assert raised.value.code == "CORPUS_MANIFEST_INVALID"


def test_v2_graph_rejects_nonfinite_candidate_confidence():
    graph = relation_graph()
    broken = replace(
        graph,
        candidate_edges=(replace(graph.candidate_edges[0], confidence=float("nan")),),
    )

    with pytest.raises(BackendError) as raised:
        parse_project_graph(broken.to_dict())

    assert raised.value.code == "CORPUS_MANIFEST_INVALID"


def test_v2_graph_requires_exactly_one_membership_for_each_net_port():
    graph = relation_graph()
    broken = replace(graph, port_net_memberships=graph.port_net_memberships[:1])

    with pytest.raises(BackendError) as raised:
        parse_project_graph(broken.to_dict())

    assert raised.value.code == "CORPUS_MANIFEST_INVALID"


def test_v2_graph_rejects_candidate_with_missing_conductor():
    graph = relation_graph()
    broken = replace(
        graph,
        candidate_edges=(
            replace(graph.candidate_edges[0], left="occurrence:missing@36,0"),
        ),
    )

    with pytest.raises(BackendError) as raised:
        parse_project_graph(broken.to_dict())

    assert raised.value.code == "CORPUS_MANIFEST_INVALID"


@pytest.mark.parametrize("version", [2.0, True])
def test_v2_graph_requires_an_exact_integer_schema_version(version):
    value = relation_graph().to_dict()
    value["schema_version"] = version

    with pytest.raises(BackendError) as raised:
        parse_project_graph(value)

    assert raised.value.code == "CORPUS_MANIFEST_INVALID"
