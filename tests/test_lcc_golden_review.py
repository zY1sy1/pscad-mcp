"""Synthetic fixtures exercise provenance gates, never licensed acceptance."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts import generate_lcc_golden as generator


def artifact(path: Path) -> dict:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def write_review(reference: Path, blueprint: Path, compiler: Path) -> Path:
    root = blueprint.parent
    files = {}
    for name in ("reference.pscx", "reference.pslx", "reference_01.out", "reference.inf"):
        path = root / name
        path.write_text("synthetic test fixture: " + name, encoding="utf-8")
        files[name] = artifact(path)
    settings = json.loads(blueprint.read_text(encoding="utf-8"))["settings"]
    record = {
        "schema_version": 1,
        "review_status": "approved",
        "review_id": "unit-test-review",
        "reviewer": "unit-test-reviewer",
        "reviewed_at_utc": "2026-09-26T00:00:00Z",
        "scope": "lcc.fixed_autonomous",
        "reference_kind": "independent_manual_assembly",
        "independence_statement": "Synthetic test only; not a licensed reference.",
        "target_blueprint_sha256": artifact(blueprint)["sha256"],
        "acceptance_sha256": artifact(root / "acceptance.json")["sha256"],
        "normalized_output": artifact(reference),
        "source_project": files["reference.pscx"],
        "source_libraries": [files["reference.pslx"]],
        "raw_outputs": [files["reference_01.out"]],
        "output_metadata": [files["reference.inf"]],
        "compiler": artifact(compiler),
        "emtdc_time_step_s": settings["time_step_s"],
        "output_step_s": settings["output_step_s"],
    }
    path = root / "review.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


@pytest.fixture
def inputs(tmp_path):
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps({"channels": {"V": {
        "units": "kV", "time": [0, 1], "values": [1, 1],
    }}}), encoding="utf-8")
    blueprint = tmp_path / "blueprint.json"
    blueprint.write_text(json.dumps({
        "settings": {"time_step_s": 0.001, "output_step_s": 0.001},
        "outputs": [{"path": "V", "units": "kV"}],
    }), encoding="utf-8")
    (tmp_path / "acceptance.json").write_text(json.dumps({"golden": {
        "comparison_window": [0, 1], "alignment": {"channel": "V"},
    }}), encoding="utf-8")
    library = tmp_path / "library.pslx"
    compiler = tmp_path / "compiler.exe"
    library.write_text("test target library", encoding="utf-8")
    compiler.write_text("test compiler", encoding="utf-8")
    (tmp_path / "golden.json").write_text("original", encoding="utf-8")
    return reference, blueprint, library, compiler


def test_confirmed_reference_cannot_be_generated_without_independent_review(inputs):
    with pytest.raises(ValueError, match="independent review"):
        generator.generate(*inputs)
    assert (inputs[1].parent / "golden.json").read_text() == "original"


@pytest.mark.parametrize("field,value", [
    ("review_status", "pending"),
    ("reviewer", ""),
    ("reviewed_at_utc", "yesterday"),
    ("scope", "mmc.avm_half_bridge"),
    ("reference_kind", "builder_self_reference"),
    ("independence_statement", ""),
    ("target_blueprint_sha256", "0" * 64),
    ("acceptance_sha256", "0" * 64),
    ("emtdc_time_step_s", 0.002),
    ("raw_outputs", []),
    ("output_metadata", []),
])
def test_unreviewed_or_unbound_reference_never_replaces_golden(inputs, field, value):
    review = write_review(inputs[0], inputs[1], inputs[3])
    payload = json.loads(review.read_text())
    payload[field] = value
    review.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        generator.generate(*inputs, review_record=review)
    assert (inputs[1].parent / "golden.json").read_text() == "original"


def test_changed_reference_source_is_rejected(inputs):
    review = write_review(inputs[0], inputs[1], inputs[3])
    (review.parent / "reference_01.out").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        generator.generate(*inputs, review_record=review)
    assert (inputs[1].parent / "golden.json").read_text() == "original"


def test_generated_reference_retains_review_and_original_source_identities(inputs):
    review = write_review(inputs[0], inputs[1], inputs[3])
    output = generator.generate(*inputs, review_record=review)
    source = json.loads(output.read_text())["source"]
    assert source["review_record_sha256"] == artifact(review)["sha256"]
    assert source["review"]["review_id"] == "unit-test-review"
    assert source["review"]["normalized_output"] == artifact(inputs[0])
    assert source["review"]["raw_outputs"] == [artifact(review.parent / "reference_01.out")]


@pytest.mark.parametrize("changed_name", ["review.json", "reference_01.out"])
def test_reviewed_inputs_cannot_change_between_validation_and_write(inputs, monkeypatch, changed_name):
    review = write_review(inputs[0], inputs[1], inputs[3])
    original = generator._windowed_channel

    def mutate_after_validation(*args):
        result = original(*args)
        (review.parent / changed_name).write_text("changed after review validation", encoding="utf-8")
        return result

    monkeypatch.setattr(generator, "_windowed_channel", mutate_after_validation)
    with pytest.raises(ValueError, match="changed"):
        generator.generate(*inputs, review_record=review)
    assert (inputs[1].parent / "golden.json").read_text() == "original"
