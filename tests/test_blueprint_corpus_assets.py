from __future__ import annotations

from pscad_mcp.builders.blueprint.corpus_assets import (
    load_corpus_blueprints,
    load_packaged_corpus_graphs,
    load_packaged_corpus_manifest,
    load_packaged_corpus_record_files,
)


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
