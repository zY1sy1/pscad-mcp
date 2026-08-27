from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from pscad_mcp.builders.blueprint.corpus_extractor import extract_project
from pscad_mcp.builders.blueprint.corpus_models import CorpusSource, CorpusSpec
from pscad_mcp.builders.blueprint.corpus_writer import (
    KIND_ORDER,
    canonical_json,
    canonical_jsonl,
    derive_records,
    validate_candidate,
    write_corpus_candidate,
)
from pscad_mcp.core.backend.base import BackendError


FIXTURES = Path(__file__).parent / "fixtures" / "blueprint_corpus"


def copy_fixture(tmp_path: Path, name: str) -> Path:
    destination = tmp_path / name
    shutil.copyfile(FIXTURES / name, destination)
    return destination


def source_contract(path: Path, *, project_id: str = "minimal") -> CorpusSource:
    data = path.read_bytes()
    return CorpusSource(
        project_id=project_id,
        basename=path.name,
        byte_length=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        pscad_versions=("4.6.2",),
        dependencies=(),
    )


def fixture_corpus(tmp_path: Path) -> tuple[CorpusSpec, object]:
    source = copy_fixture(tmp_path, "minimal.pscx")
    admitted = source_contract(source)
    spec = CorpusSpec(
        schema_version=1,
        normalization_profile="pscad-xml-v1",
        name="fixture_v1",
        inclusion_policy="explicit-entry-points-v1",
        exclusion_policy="no-backups-builds-results-v1",
        entry_points=(admitted,),
    )
    return spec, extract_project(tmp_path, admitted)


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_records_are_derived_in_stable_kind_and_key_order(tmp_path):
    spec, graph = fixture_corpus(tmp_path)

    records = derive_records(spec.name, spec.normalization_profile, graph)

    observed_kinds = [record.kind for record in records]
    assert set(observed_kinds) == set(KIND_ORDER)
    assert [KIND_ORDER[kind] for kind in observed_kinds] == sorted(KIND_ORDER[kind] for kind in observed_kinds)
    assert [record.record_key for record in records if record.kind == "definition"] == sorted(
        record.record_key for record in records if record.kind == "definition"
    )
    assert all(record.source_sha256 == graph.source_sha256 for record in records)
    assert all(record.corpus_name == "fixture_v1" for record in records)
    assert canonical_jsonl(records) == canonical_jsonl(tuple(reversed(records)))


def test_canonical_json_is_ascii_sorted_finite_and_newline_terminated():
    assert canonical_json({"z": "\u4e2d", "a": [2, 1]}) == b'{"a":[2,1],"z":"\\u4e2d"}\n'

    with pytest.raises(TypeError):
        canonical_json({"bad": float("nan")})


def test_write_candidate_creates_self_validating_manifest_graph_and_records(tmp_path):
    spec, graph = fixture_corpus(tmp_path)
    destination = tmp_path / "candidate"

    manifest = write_corpus_candidate(spec, [graph], destination)
    reparsed = validate_candidate(destination, spec)

    assert manifest == reparsed
    assert manifest.project_count == 1
    assert manifest.projects[0].project_id == "minimal"
    assert manifest.projects[0].record_count == len(derive_records(spec.name, spec.normalization_profile, graph))
    assert set(tree_bytes(destination)) == {
        "source-spec.json",
        "manifest.json",
        "graphs/minimal.json",
        "records/minimal.jsonl",
    }
    assert destination.joinpath("graphs/minimal.json").read_bytes() == canonical_json(graph.to_dict())


def test_repeated_candidate_generation_is_byte_identical(tmp_path):
    spec, graph = fixture_corpus(tmp_path)
    destination = tmp_path / "candidate"

    write_corpus_candidate(spec, [graph], destination)
    first = tree_bytes(destination)
    write_corpus_candidate(spec, [graph], destination)

    assert tree_bytes(destination) == first


@pytest.mark.parametrize("tamper", ["graph", "record", "manifest", "extra"])
def test_candidate_validation_fails_on_artifact_drift_or_extra_files(tmp_path, tamper):
    spec, graph = fixture_corpus(tmp_path)
    destination = tmp_path / "candidate"
    write_corpus_candidate(spec, [graph], destination)
    if tamper == "graph":
        value = json.loads((destination / "graphs/minimal.json").read_text(encoding="ascii"))
        value["name"] = "Changed"
        (destination / "graphs/minimal.json").write_text(json.dumps(value), encoding="ascii")
    elif tamper == "record":
        path = destination / "records/minimal.jsonl"
        path.write_bytes(path.read_bytes().replace(b'"resolved":true', b'"resolved":false', 1))
    elif tamper == "manifest":
        value = json.loads((destination / "manifest.json").read_text(encoding="ascii"))
        value["project_count"] = 2
        (destination / "manifest.json").write_text(json.dumps(value), encoding="ascii")
    else:
        (destination / "unexpected.bin").write_bytes(b"extra")

    with pytest.raises(BackendError) as raised:
        validate_candidate(destination, spec)
    assert raised.value.code == "CORPUS_MANIFEST_INVALID"


def test_candidate_validation_rejects_denied_fields_and_absolute_paths(tmp_path):
    spec, graph = fixture_corpus(tmp_path)
    destination = tmp_path / "candidate"
    write_corpus_candidate(spec, [graph], destination)
    graph_path = destination / "graphs/minimal.json"
    value = json.loads(graph_path.read_text(encoding="ascii"))
    value["source_path"] = "C:\\Users\\private\\model.pscx"
    graph_path.write_text(json.dumps(value), encoding="ascii")

    with pytest.raises(BackendError) as raised:
        validate_candidate(destination, spec)
    assert raised.value.code == "CORPUS_MANIFEST_INVALID"


def test_candidate_validation_rejects_absolute_path_embedded_in_text(tmp_path):
    spec, graph = fixture_corpus(tmp_path)
    graph = replace(graph, name=r"Opened from C:\Users\private\model.pscx")

    with pytest.raises(BackendError) as raised:
        write_corpus_candidate(spec, [graph], tmp_path / "candidate")

    assert raised.value.code == "CORPUS_MANIFEST_INVALID"


def test_validation_failure_does_not_replace_existing_destination(tmp_path, monkeypatch):
    spec, graph = fixture_corpus(tmp_path)
    destination = tmp_path / "candidate"
    destination.mkdir()
    (destination / "sentinel").write_text("old", encoding="ascii")
    from pscad_mcp.builders.blueprint import corpus_writer

    failure = BackendError("CORPUS_MANIFEST_INVALID", "candidate rejected", "corpus", "validate_candidate")
    monkeypatch.setattr(corpus_writer, "validate_candidate", lambda *args, **kwargs: (_ for _ in ()).throw(failure))

    with pytest.raises(BackendError):
        write_corpus_candidate(spec, [graph], destination)

    assert tree_bytes(destination) == {"sentinel": b"old"}
