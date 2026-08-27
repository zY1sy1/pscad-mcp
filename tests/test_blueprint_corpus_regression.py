from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from pscad_mcp.builders.blueprint.corpus_schema import parse_corpus_spec
from scripts.build_blueprint_corpus import generate_corpus


ROOT = Path(__file__).parents[1]
SPEC_PATH = ROOT / "pscad_mcp" / "assets" / "corpora" / "moxing_v1" / "source-spec.json"
PACKAGED_CORPUS = SPEC_PATH.parent
PACKAGED_BLUEPRINTS = ROOT / "pscad_mcp" / "assets" / "blueprints"

pytestmark = pytest.mark.skipif(
    os.getenv("PSCAD_MCP_CORPUS_SOURCE") is None,
    reason="requires PSCAD_MCP_CORPUS_SOURCE for local read-only corpus regression",
)


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _admitted_hashes(source_root: Path, spec) -> dict[str, tuple[int, str]]:
    observed: dict[str, tuple[int, str]] = {}
    for source in spec.entry_points:
        for basename in (source.basename, *(dependency.basename for dependency in source.dependencies)):
            path = source_root / basename
            assert path.is_file() and not path.is_symlink()
            content = path.read_bytes()
            observed[basename] = (len(content), hashlib.sha256(content).hexdigest())
    return observed


def test_moxing_corpus_and_blueprints_regenerate_byte_identically(tmp_path):
    source_root = Path(os.environ["PSCAD_MCP_CORPUS_SOURCE"]).resolve(strict=True)
    spec = parse_corpus_spec(json.loads(SPEC_PATH.read_text(encoding="ascii")))
    before = _admitted_hashes(source_root, spec)
    generated_corpus = tmp_path / "moxing_v1"

    generate_corpus(source_root, spec, generated_corpus)

    generated_blueprints = generated_corpus.with_name("moxing_v1-blueprints")
    assert _tree_bytes(generated_corpus) == _tree_bytes(PACKAGED_CORPUS)
    for source in spec.entry_points:
        name = f"{source.project_id}-existing-v1"
        assert (generated_blueprints / name / "blueprint.json").read_bytes() == (
            PACKAGED_BLUEPRINTS / name / "blueprint.json"
        ).read_bytes()
    assert _admitted_hashes(source_root, spec) == before
