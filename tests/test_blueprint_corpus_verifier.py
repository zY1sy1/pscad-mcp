from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import shutil

import pytest

from pscad_mcp.builders.blueprint.corpus_extractor import extract_project
from pscad_mcp.builders.blueprint.corpus_models import CorpusSource
from pscad_mcp.builders.blueprint.corpus_verifier import (
    generate_blueprint_candidate,
    verify_blueprint_candidate,
)
from pscad_mcp.builders.blueprint.corpus_writer import canonical_json
from pscad_mcp.builders.blueprint.schema import parse_blueprint
from pscad_mcp.core.backend.base import BackendError


FIXTURES = Path(__file__).parent / "fixtures" / "blueprint_corpus"


def fixture_graph(tmp_path: Path):
    source_path = tmp_path / "minimal.pscx"
    shutil.copyfile(FIXTURES / "minimal.pscx", source_path)
    content = source_path.read_bytes()
    source = CorpusSource(
        project_id="minimal",
        basename=source_path.name,
        byte_length=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        pscad_versions=("4.6.2",),
        dependencies=(),
    )
    return source, extract_project(tmp_path, source)


def test_blueprint_candidate_is_read_only_empty_hash_bound_and_schema_valid(tmp_path):
    source, graph = fixture_graph(tmp_path)

    value = generate_blueprint_candidate(source, graph)
    parsed = parse_blueprint(value)

    assert parsed.identity.name == "minimal-existing-v1"
    assert parsed.identity.inspection_profile == "corpus-existing-project-v1"
    assert parsed.operations == ()
    assert parsed.source_package["handling_policy"] == "read_only"
    assert parsed.source_package["required"][0] == {
        "path": "minimal.pscx",
        "kind": "file",
        "sha256": graph.source_sha256,
    }
    assert parsed.publication.delivery_package is False
    assert parsed.publication.scope == "evidence_only"
    assert parsed.acceptance["required_structure"][0] == {
        "logical_id": graph.components[0].key,
        "definition": graph.components[0].definition_key,
        "canvas": graph.components[0].canvas_key,
    }
    assert parsed.acceptance["required_parameters"][0]["value"] == "2.0"
    assert parsed.acceptance["outputs"][0] == {
        "channel": graph.output_channels[0].key,
        "units": "pu",
        "required": True,
    }


@pytest.mark.parametrize("contract", ["structure", "parameter", "output", "source_hash", "extra_required"])
def test_blueprint_graph_contract_drift_fails_verification(tmp_path, contract):
    source, graph = fixture_graph(tmp_path)
    value = generate_blueprint_candidate(source, graph)
    if contract == "structure":
        value["acceptance"]["required_structure"].pop()
    elif contract == "parameter":
        value["acceptance"]["required_parameters"][0]["value"] = "changed"
    elif contract == "output":
        value["acceptance"]["outputs"][0]["required"] = False
    elif contract == "source_hash":
        value["source_package"]["required"][0]["sha256"] = "0" * 64
    else:
        value["source_package"]["required"].append({"path": "support", "kind": "directory"})

    with pytest.raises(BackendError) as raised:
        verify_blueprint_candidate(value, graph)

    assert raised.value.code == "CORPUS_BLUEPRINT_MISMATCH"


def test_blueprint_verification_rejects_mutation_operations(tmp_path):
    source, graph = fixture_graph(tmp_path)
    value = generate_blueprint_candidate(source, graph)
    value["operations"] = [
        {
            "sequence": 1,
            "kind": "set_project_settings",
            "target": "project",
            "arguments": {"settings": {"time_duration": "10"}},
            "operation_id": "op-unsafe",
        }
    ]

    with pytest.raises(BackendError) as raised:
        verify_blueprint_candidate(value, graph)

    assert raised.value.code == "CORPUS_BLUEPRINT_UNSAFE"


def test_blueprint_generation_and_verification_do_not_mutate_graph(tmp_path):
    source, graph = fixture_graph(tmp_path)
    before = canonical_json(graph.to_dict())

    value = generate_blueprint_candidate(source, graph)
    verification = verify_blueprint_candidate(value, graph)

    assert verification.project_id == "minimal"
    assert verification.blueprint_name == "minimal-existing-v1"
    assert verification.source_hash_verified is True
    assert verification.operations_empty is True
    assert verification.status == "verified"
    assert canonical_json(graph.to_dict()) == before


def test_unresolved_output_is_retained_as_non_required_evidence(tmp_path):
    source, graph = fixture_graph(tmp_path)
    graph = replace(graph, output_channels=(replace(graph.output_channels[0], resolved=False),))

    value = generate_blueprint_candidate(source, graph)

    assert value["acceptance"]["outputs"][0]["required"] is False
    assert verify_blueprint_candidate(value, graph).status == "verified"
