from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from pscad_mcp.builders.blueprint.corpus_extractor import extract_project
from pscad_mcp.builders.blueprint.corpus_models import CorpusCanvas, CorpusSource
from pscad_mcp.builders.blueprint.corpus_relations import expand_hierarchy_occurrences
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
