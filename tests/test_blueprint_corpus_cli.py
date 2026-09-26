from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from scripts.build_blueprint_corpus import _definition_bindings

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "build_blueprint_corpus.py"
FIXTURE = Path(__file__).parent / "fixtures" / "blueprint_corpus" / "minimal.pscx"


def run_cli(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def arrange_source(tmp_path: Path) -> tuple[Path, Path, Path]:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "minimal.pscx"
    shutil.copyfile(FIXTURE, source)
    content = source.read_bytes()
    spec = {
        "schema_version": 1,
        "normalization_profile": "pscad-xml-v1",
        "name": "fixture_v1",
        "inclusion_policy": "explicit-entry-points-v1",
        "exclusion_policy": "no-backups-builds-results-v1",
        "entry_points": [
            {
                "project_id": "minimal",
                "basename": "minimal.pscx",
                "byte_length": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "pscad_versions": ["4.6.2"],
                "dependencies": [],
            }
        ],
    }
    spec_path = tmp_path / "source-spec.json"
    spec_path.write_text(json.dumps(spec), encoding="ascii")
    return source_root, spec_path, source


def arrange_v2_source(tmp_path: Path):
    source_root = tmp_path / "source-v2"
    source_root.mkdir()
    source = source_root / "repeated-module-v2.pscx"
    shutil.copyfile(
        Path(__file__).parent / "fixtures" / "blueprint_corpus" / source.name,
        source,
    )
    master = tmp_path / "master.pslx"
    shutil.copyfile(
        Path(__file__).parent / "fixtures" / "blueprint_corpus" / "master-462.pslx",
        master,
    )
    source_bytes = source.read_bytes()
    master_bytes = master.read_bytes()
    spec = {
        "schema_version": 2,
        "normalization_profile": "pscad-xml-v2",
        "name": "fixture_v2",
        "inclusion_policy": "explicit-entry-points-v1",
        "exclusion_policy": "no-backups-builds-results-v1",
        "definition_sources": [
            {
                "namespace": "master",
                "basename": master.name,
                "byte_length": len(master_bytes),
                "sha256": hashlib.sha256(master_bytes).hexdigest(),
                "pscad_versions": ["4.6.2"],
                "policy": "ports-and-classification-v1",
            }
        ],
        "entry_points": [
            {
                "project_id": "repeated-module-v2",
                "basename": source.name,
                "byte_length": len(source_bytes),
                "sha256": hashlib.sha256(source_bytes).hexdigest(),
                "pscad_versions": ["4.6.2"],
                "dependencies": [],
            }
        ],
    }
    spec_path = tmp_path / "source-spec-v2.json"
    spec_path.write_text(json.dumps(spec), encoding="ascii")
    output = tmp_path / "proposed" / "fixture_v2"
    args = [
        "--source-root",
        str(source_root),
        "--spec",
        str(spec_path),
        "--output",
        str(output),
        "--definition-source",
        f"master@4.6.2={master}",
    ]
    return source_root, spec_path, output, master, args


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_cli_requires_explicit_source_spec_and_output():
    result = run_cli(["generate"])

    assert result.returncode == 2
    assert "--source-root" in result.stderr
    assert "--spec" in result.stderr
    assert "--output" in result.stderr


def test_generate_writes_valid_corpus_and_blueprint_candidates_without_source_mutation(tmp_path):
    source_root, spec_path, source = arrange_source(tmp_path)
    output = tmp_path / "proposed" / "fixture_v1"
    before = source.read_bytes()

    result = run_cli(
        [
            "generate",
            "--source-root",
            str(source_root),
            "--spec",
            str(spec_path),
            "--output",
            str(output),
        ]
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary == {
        "blueprints": ["minimal-existing-v1"],
        "command": "generate",
        "corpus": "fixture_v1",
        "projects": ["minimal"],
        "status": "generated",
    }
    assert str(source_root) not in result.stdout
    assert source.read_bytes() == before
    assert (output / "manifest.json").is_file()
    assert (output / "graphs" / "minimal.json").is_file()
    assert (output / "records" / "minimal.jsonl").is_file()
    blueprint = output.with_name("fixture_v1-blueprints") / "minimal-existing-v1" / "blueprint.json"
    assert json.loads(blueprint.read_text(encoding="ascii"))["operations"] == []


def test_verify_is_read_only_and_compare_reports_drift_without_rewriting(tmp_path):
    source_root, spec_path, source = arrange_source(tmp_path)
    output = tmp_path / "proposed" / "fixture_v1"
    arguments = ["--source-root", str(source_root), "--spec", str(spec_path), "--output", str(output)]
    generated = run_cli(["generate", *arguments])
    assert generated.returncode == 0, generated.stderr
    blueprints = output.with_name("fixture_v1-blueprints")
    before_output = tree_bytes(output)
    before_blueprints = tree_bytes(blueprints)
    before_source = source.read_bytes()

    verified = run_cli(["verify", *arguments])
    compared = run_cli(["compare", *arguments])

    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["status"] == "verified"
    assert compared.returncode == 0, compared.stderr
    assert json.loads(compared.stdout)["status"] == "identical"
    assert tree_bytes(output) == before_output
    assert tree_bytes(blueprints) == before_blueprints
    assert source.read_bytes() == before_source

    graph_path = output / "graphs" / "minimal.json"
    graph_path.write_bytes(graph_path.read_bytes() + b" ")
    drifted = run_cli(["compare", *arguments])

    assert drifted.returncode == 1
    assert json.loads(drifted.stdout)["status"] == "different"
    assert graph_path.read_bytes().endswith(b" ")
    assert source.read_bytes() == before_source


def test_cli_rejects_output_that_overlaps_source_root(tmp_path):
    source_root, spec_path, source = arrange_source(tmp_path)
    before = source.read_bytes()

    result = run_cli(
        [
            "generate",
            "--source-root",
            str(source_root),
            "--spec",
            str(spec_path),
            "--output",
            str(source_root / "derived"),
        ]
    )

    assert result.returncode == 1
    assert json.loads(result.stdout) == {"code": "CORPUS_OUTPUT_UNSAFE", "status": "failed"}
    assert not (source_root / "derived").exists()
    assert source.read_bytes() == before


def test_compare_uses_shared_blueprint_root_for_packaged_corpus_layout(tmp_path):
    source_root, spec_path, _ = arrange_source(tmp_path)
    output = tmp_path / "package" / "assets" / "corpora" / "fixture_v1"
    arguments = ["--source-root", str(source_root), "--spec", str(spec_path), "--output", str(output)]
    generated = run_cli(["generate", *arguments])
    assert generated.returncode == 0, generated.stderr
    proposed_blueprints = output.with_name("fixture_v1-blueprints")
    packaged_blueprints = output.parent.parent / "blueprints"
    packaged_blueprints.mkdir()
    shutil.move(
        str(proposed_blueprints / "minimal-existing-v1"),
        str(packaged_blueprints / "minimal-existing-v1"),
    )
    proposed_blueprints.rmdir()
    unrelated = packaged_blueprints / "unrelated-v1"
    unrelated.mkdir()
    (unrelated / "blueprint.json").write_text("{}\n", encoding="ascii")

    compared = run_cli(["compare", *arguments])
    verified = run_cli(["verify", *arguments])

    assert compared.returncode == 0, compared.stderr
    assert json.loads(compared.stdout)["status"] == "identical"
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["status"] == "verified"
    assert (unrelated / "blueprint.json").read_text(encoding="ascii") == "{}\n"


def test_v2_preflight_requires_every_versioned_definition_source(tmp_path):
    _source_root, spec_path, output, _master, args = arrange_v2_source(tmp_path)
    value = json.loads(spec_path.read_text(encoding="ascii"))
    value["definition_sources"].append(
        {
            **value["definition_sources"][0],
            "basename": "master-463.pslx",
            "pscad_versions": ["4.6.3"],
        }
    )
    spec_path.write_text(json.dumps(value), encoding="ascii")

    result = run_cli(["preflight", *args])

    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "code": "CORPUS_DEFINITION_SOURCE_MISMATCH",
        "status": "failed",
    }
    assert str(tmp_path) not in result.stdout
    assert not output.exists()


@pytest.mark.parametrize(
    "binding",
    (
        "master@4.6.2@extra=C:/definitions/master.pslx",
        "master@4.6.2=definitions/master.pslx",
    ),
)
def test_definition_source_bindings_reject_malformed_or_relative_values(binding):
    with pytest.raises(BackendError) as raised:
        _definition_bindings([binding])

    assert raised.value.code == "CORPUS_DEFINITION_SOURCE_MISMATCH"
    assert raised.value.details == {}


def test_definition_source_bindings_reject_duplicate_namespace_and_version():
    with pytest.raises(BackendError) as raised:
        _definition_bindings(
            [
                "master@4.6.2=C:/definitions/master-one.pslx",
                "master@4.6.2=C:/definitions/master-two.pslx",
            ]
        )

    assert raised.value.code == "CORPUS_DEFINITION_SOURCE_MISMATCH"
    assert raised.value.details == {}


def test_v2_generate_verify_compare_use_the_same_relation_graph(tmp_path):
    _source_root, _spec_path, output, _master, args = arrange_v2_source(tmp_path)

    generated = run_cli(["generate", *args])
    verified = run_cli(["verify", *args])
    compared = run_cli(["compare", *args])

    assert generated.returncode == verified.returncode == compared.returncode == 0
    assert json.loads(generated.stdout)["schema_version"] == 2
    assert json.loads(verified.stdout)["status"] == "verified"
    assert json.loads(compared.stdout)["status"] == "identical"
    assert (output.with_name("fixture_v2-blueprints") / "repeated-module-v2-existing-v2" / "blueprint.json").is_file()


def test_v2_projection_failure_preserves_existing_corpus_and_blueprints(tmp_path):
    _source_root, spec_path, output, _master, args = arrange_v2_source(tmp_path)
    generated = run_cli(["generate", *args])
    assert generated.returncode == 0, generated.stderr
    blueprints = output.with_name("fixture_v2-blueprints")
    before_output = tree_bytes(output)
    before_blueprints = tree_bytes(blueprints)

    value = json.loads(spec_path.read_text(encoding="ascii"))
    value["definition_sources"].append(
        {
            **value["definition_sources"][0],
            "basename": "master-463.pslx",
            "pscad_versions": ["4.6.3"],
        }
    )
    spec_path.write_text(json.dumps(value), encoding="ascii")
    failed = run_cli(["generate", *args])

    assert failed.returncode == 1
    assert json.loads(failed.stdout) == {
        "code": "CORPUS_DEFINITION_SOURCE_MISMATCH",
        "status": "failed",
    }
    assert str(tmp_path) not in failed.stdout
    assert tree_bytes(output) == before_output
    assert tree_bytes(blueprints) == before_blueprints


def test_propose_spec_rejects_incomplete_definition_bindings(tmp_path):
    source_root, spec_path, _source = arrange_source(tmp_path)
    master = tmp_path / "master.pslx"
    shutil.copyfile(
        Path(__file__).parent / "fixtures" / "blueprint_corpus" / "master-462.pslx",
        master,
    )
    proposal = tmp_path / "source-spec-v2-proposal.json"

    result = run_cli(
        [
            "propose-spec",
            "--source-root",
            str(source_root),
            "--spec",
            str(spec_path),
            "--proposal",
            str(proposal),
            "--definition-source",
            f"unused@4.6.2={master}",
        ]
    )

    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "code": "CORPUS_DEFINITION_SOURCE_MISMATCH",
        "status": "failed",
    }
    assert str(tmp_path) not in result.stdout
    assert not proposal.exists()


def test_propose_spec_rejects_nonportable_definition_binding_namespace(tmp_path):
    source_root, spec_path, _source = arrange_source(tmp_path)
    master = tmp_path / "master.pslx"
    shutil.copyfile(
        Path(__file__).parent / "fixtures" / "blueprint_corpus" / "master-462.pslx",
        master,
    )
    proposal = tmp_path / "source-spec-v2-proposal.json"

    result = run_cli(
        [
            "propose-spec",
            "--source-root",
            str(source_root),
            "--spec",
            str(spec_path),
            "--proposal",
            str(proposal),
            "--definition-source",
            f"MASTER@4.6.2={master}",
        ]
    )

    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "code": "CORPUS_DEFINITION_SOURCE_MISMATCH",
        "status": "failed",
    }
    assert str(tmp_path) not in result.stdout
    assert not proposal.exists()


def test_propose_spec_writes_portable_v2_candidate_without_overwrite(tmp_path):
    source_root, spec_path, _source = arrange_source(tmp_path)
    master = tmp_path / "master.pslx"
    shutil.copyfile(
        Path(__file__).parent / "fixtures" / "blueprint_corpus" / "master-462.pslx",
        master,
    )
    proposal = tmp_path / "source-spec-v2-proposal.json"
    args = [
        "propose-spec",
        "--source-root",
        str(source_root),
        "--spec",
        str(spec_path),
        "--proposal",
        str(proposal),
        "--definition-source",
        f"master@4.6.2={master}",
    ]

    proposed = run_cli(args)
    repeated = run_cli(args)

    assert proposed.returncode == 0
    value = json.loads(proposal.read_text(encoding="ascii"))
    assert value["schema_version"] == 2
    assert value["normalization_profile"] == "pscad-xml-v2"
    assert str(tmp_path) not in proposal.read_text(encoding="ascii")
    assert repeated.returncode == 1
    assert json.loads(repeated.stdout)["status"] == "failed"
