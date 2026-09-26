from __future__ import annotations

from pscad_mcp.builders.blueprint.corpus_assets import (
    load_corpus_blueprints,
    load_packaged_corpus_graphs,
    load_packaged_corpus_manifest,
    load_packaged_corpus_record_files,
)
from pscad_mcp.builders.blueprint.corpus_writer import write_corpus_candidate
from tests.test_blueprint_corpus_v2_models import relation_graph
from tests.test_blueprint_corpus_writer import v2_spec


def test_packaged_corpus_manifest_graphs_records_and_blueprints_load():
    manifest = load_packaged_corpus_manifest("moxing_v1")

    graphs = load_packaged_corpus_graphs(manifest)
    record_files = load_packaged_corpus_record_files(manifest)
    blueprints = load_corpus_blueprints(manifest)

    assert manifest.project_count == 4
    assert len(graphs) == 4
    assert {graph.project_id for graph in graphs} == {project.project_id for project in manifest.projects}
    assert set(record_files) == {project.project_id for project in manifest.projects}
    assert all(content.endswith(b"\n") for content in record_files.values())
    assert len(blueprints) == 4
    assert all(not blueprint.operations for blueprint in blueprints)
    assert all(blueprint.publication.delivery_package is False for blueprint in blueprints)


def test_v2_packaged_manifest_graphs_and_records_keep_relationship_signatures(
    tmp_path,
    monkeypatch,
):
    from pscad_mcp.builders.blueprint import corpus_assets

    graph = relation_graph()
    spec = v2_spec(graph)
    destination = tmp_path / spec.name
    write_corpus_candidate(spec, (graph,), destination)
    monkeypatch.setattr(corpus_assets, "_corpus_root", lambda _name: destination)

    manifest = load_packaged_corpus_manifest(spec.name)
    graphs = load_packaged_corpus_graphs(manifest)
    records = load_packaged_corpus_record_files(manifest)

    assert manifest.schema_version == 2
    assert graphs == (graph,)
    assert manifest.projects[0].confirmed_relation_signature == (
        graph.confirmed_relation_signature
    )
    assert records[graph.project_id].endswith(b"\n")
