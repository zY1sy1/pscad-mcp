from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


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
