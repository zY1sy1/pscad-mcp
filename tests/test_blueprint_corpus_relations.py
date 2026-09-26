from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from pscad_mcp.builders.blueprint.corpus_extractor import extract_project
from pscad_mcp.builders.blueprint.corpus_models import (
    CorpusCanvas,
    CorpusDefinitionSource,
    CorpusSource,
)
from pscad_mcp.builders.blueprint.corpus_relations import (
    expand_hierarchy_occurrences,
    materialize_instance_ports,
)
from pscad_mcp.builders.blueprint.definition_catalog import load_definition_catalog
from pscad_mcp.core.backend.base import BackendError

FIXTURES = Path(__file__).parent / "fixtures" / "blueprint_corpus"


def _graph(tmp_path):
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
    return extract_project(
        tmp_path,
        source,
        schema_version=2,
        normalization_profile="pscad-xml-v2",
    )


def _mixed_graph_catalog(tmp_path):
    source_path = tmp_path / "mixed-signal-v2.pscx"
    source_path.write_bytes((FIXTURES / source_path.name).read_bytes())
    payload = source_path.read_bytes()
    graph = extract_project(
        tmp_path,
        CorpusSource(
            project_id="mixed-signal-v2",
            basename=source_path.name,
            byte_length=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            pscad_versions=("4.6.2",),
            dependencies=(),
        ),
        schema_version=2,
        normalization_profile="pscad-xml-v2",
    )
    master = tmp_path / "master.pslx"
    master.write_bytes((FIXTURES / "master-462.pslx").read_bytes())
    master_payload = master.read_bytes()
    master_source = CorpusDefinitionSource(
        namespace="master",
        basename=master.name,
        byte_length=len(master_payload),
        sha256=hashlib.sha256(master_payload).hexdigest(),
        pscad_versions=("4.6.2",),
        policy="ports-and-classification-v1",
    )
    catalog = load_definition_catalog(
        (master_source,),
        {master_source.keys[0]: master},
    )
    return graph, catalog, expand_hierarchy_occurrences(graph)


def test_repeated_child_definitions_expand_to_distinct_occurrences(tmp_path):
    graph = _graph(tmp_path)

    expanded = expand_hierarchy_occurrences(graph)

    child_components = [
        item
        for item in expanded.components
        if item.source_component_key.endswith("/component:leaf@0,0#1")
    ]
    assert len(child_components) == 2
    assert child_components[0].key != child_components[1].key
    assert child_components[0].canvas_key != child_components[1].canvas_key
    assert child_components[0].hierarchy_path != child_components[1].hierarchy_path
    child_conductors = [
        item
        for item in expanded.conductors
        if item.source_connection_key.startswith("canvas:gainblock/connection:")
    ]
    assert len(child_conductors) == 2
    assert len(expanded.boundaries) == 2
    assert all(boundary.page_port_names == ("IN", "OUT") for boundary in expanded.boundaries)


def test_hierarchy_cycle_fails_closed(tmp_path):
    graph = _graph(tmp_path)
    leaf = next(item for item in graph.components if item.name == "LEAF")
    hierarchy = next(item for item in graph.connections if item.kind == "hierarchy")
    damaged = replace(
        graph,
        components=tuple(
            replace(item, definition_key="definition:user:gainblock")
            if item.key == leaf.key
            else item
            for item in graph.components
        ),
        connections=(
            *graph.connections,
            replace(
                hierarchy,
                key="hierarchy:cycle",
                endpoints=(leaf.key, leaf.key),
            ),
        ),
    )

    with pytest.raises(BackendError) as raised:
        expand_hierarchy_occurrences(damaged)

    assert raised.value.code == "CORPUS_RELATION_INCOMPLETE"


def test_hierarchy_expansion_is_deterministic_under_reversed_inputs(tmp_path):
    graph = _graph(tmp_path)
    reversed_graph = replace(
        graph,
        definitions=tuple(reversed(graph.definitions)),
        canvases=tuple(reversed(graph.canvases)),
        components=tuple(reversed(graph.components)),
        connections=tuple(reversed(graph.connections)),
    )

    assert expand_hierarchy_occurrences(reversed_graph) == expand_hierarchy_occurrences(
        graph
    )


def test_duplicate_canvas_owner_definition_fails_closed(tmp_path):
    graph = _graph(tmp_path)
    owner = graph.canvases[0].owner_definition
    damaged = replace(
        graph,
        canvases=(
            *graph.canvases,
            CorpusCanvas("canvas:duplicate", "Duplicate", owner, "usercanvas"),
        ),
    )

    with pytest.raises(BackendError) as raised:
        expand_hierarchy_occurrences(damaged)

    assert raised.value.code == "CORPUS_RELATION_INCOMPLETE"


def test_classification_and_ports_use_exact_contracts_conditions_and_geometry(
    tmp_path,
):
    graph, catalog, expanded = _mixed_graph_catalog(tmp_path)

    result = materialize_instance_ports(graph, catalog, expanded)

    assert {item.classification for item in result.classifications} == {
        "non_connective",
        "port_bearing",
    }
    controller = next(item for item in expanded.components if item.name == "CTRL")
    ports = [item for item in result.ports if item.component_key == controller.key]
    assert [
        (item.name, item.occurrence, item.active, item.absolute, item.namespace)
        for item in ports
    ] == [
        ("IN", 0, True, (0, 18), "data"),
        ("IN", 1, False, (18, 0), "data"),
    ]
    assert all(item.dimension == 1 for item in ports)
    assert all(
        label.source_component_key not in {item.source_component_key for item in ports}
        for label in expanded.labels
    )


@pytest.mark.parametrize(
    ("damage", "code"),
    [
        ("missing_definition", "CORPUS_DEFINITION_UNRESOLVED"),
        ("unsupported_condition", "CORPUS_PORT_CONDITION_UNRESOLVED"),
        ("invalid_orientation", "CORPUS_PORT_GEOMETRY_UNRESOLVED"),
        ("invalid_dimension", "CORPUS_RELATION_INCOMPLETE"),
        ("unknown_namespace", "CORPUS_RELATION_INCOMPLETE"),
    ],
)
def test_port_materialization_blocks_incomplete_truth(tmp_path, damage, code):
    graph, catalog, expanded = _mixed_graph_catalog(tmp_path)
    controller = next(item for item in expanded.components if item.name == "CTRL")
    if damage == "missing_definition":
        expanded = replace(
            expanded,
            components=tuple(
                replace(item, definition_key="definition:master:missing")
                if item.key == controller.key
                else item
                for item in expanded.components
            ),
        )
    elif damage == "invalid_orientation":
        expanded = replace(
            expanded,
            components=tuple(
                replace(item, orientation=99)
                if item.key == controller.key
                else item
                for item in expanded.components
            ),
        )
    else:
        definition = next(item for item in graph.definitions if item.name == "Controller")
        replacement = replace(
            definition.ports[0],
            condition="A-1" if damage == "unsupported_condition" else "true",
            dimension="invalid"
            if damage == "invalid_dimension"
            else definition.ports[0].dimension,
            kind="" if damage == "unknown_namespace" else definition.ports[0].kind,
            model="" if damage == "unknown_namespace" else definition.ports[0].model,
            type="" if damage == "unknown_namespace" else definition.ports[0].type,
            mode="" if damage == "unknown_namespace" else definition.ports[0].mode,
        )
        graph = replace(
            graph,
            definitions=tuple(
                replace(item, ports=(replacement, *item.ports[1:]))
                if item.key == definition.key
                else item
                for item in graph.definitions
            ),
        )

    with pytest.raises(BackendError) as raised:
        materialize_instance_ports(graph, catalog, expanded)

    assert raised.value.code == code
    assert str(tmp_path) not in str(raised.value.details)


def test_missing_explicit_child_fails_closed(tmp_path):
    graph = _graph(tmp_path)
    leaf = next(item for item in graph.components if item.name == "LEAF")
    damaged = replace(
        graph,
        connections=tuple(
            item
            for item in graph.connections
            if not (item.kind == "hierarchy" and item.endpoints[-1] == leaf.key)
        ),
    )

    with pytest.raises(BackendError) as raised:
        expand_hierarchy_occurrences(damaged)

    assert raised.value.code == "CORPUS_RELATION_INCOMPLETE"
