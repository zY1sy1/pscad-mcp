from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from pscad_mcp.builders.blueprint.corpus_models import CorpusDefinitionSource
from pscad_mcp.builders.blueprint.definition_catalog import load_definition_catalog
from pscad_mcp.core.backend.base import BackendError

FIXTURES = Path(__file__).parent / "fixtures" / "blueprint_corpus"


def _source(path: Path, version: str, *, digest: str | None = None) -> CorpusDefinitionSource:
    payload = path.read_bytes()
    return CorpusDefinitionSource(
        namespace="master",
        basename=path.name,
        byte_length=len(payload),
        sha256=digest or hashlib.sha256(payload).hexdigest(),
        pscad_versions=(version,),
        policy="ports-and-classification-v1",
    )


def _copy_fixture(tmp_path: Path, name: str = "master-462.pslx") -> Path:
    destination = tmp_path / "master.pslx"
    destination.write_bytes((FIXTURES / name).read_bytes())
    return destination


def test_catalog_selects_exact_namespace_and_version(tmp_path):
    path = _copy_fixture(tmp_path)
    source = _source(path, "4.6.2")

    catalog = load_definition_catalog((source,), {source.keys[0]: path})

    definition = catalog.require("master", "4.6.2", "gain")
    assert definition.source_sha256 == source.sha256
    assert [port.name for port in definition.metadata.ports] == ["IN", "OUT"]
    assert catalog.source_read_counts == (("master", "4.6.2", 1),)
    assert len(catalog.catalog_signature) == 64


def test_catalog_selects_a_different_version_without_fallback(tmp_path):
    path = _copy_fixture(tmp_path, "master-463.pslx")
    source = _source(path, "4.6.3")

    catalog = load_definition_catalog((source,), {source.keys[0]: path})

    assert catalog.require("master", "4.6.3", "gain463").physical_name == "gain463"
    with pytest.raises(BackendError) as raised:
        catalog.require("master", "4.6.2", "gain463")
    assert raised.value.code == "CORPUS_DEFINITION_UNRESOLVED"


@pytest.mark.parametrize(
    "damage",
    ["wrong_hash", "wrong_version", "wrong_basename", "missing_binding"],
)
def test_catalog_fails_closed_without_leaking_absolute_paths(tmp_path, damage):
    path = _copy_fixture(tmp_path)
    source = _source(
        path,
        "4.6.3" if damage == "wrong_version" else "4.6.2",
        digest="f" * 64 if damage == "wrong_hash" else None,
    )
    if damage == "wrong_basename":
        source = replace(source, basename="other.pslx")
    bindings = {} if damage == "missing_binding" else {source.keys[0]: path}

    with pytest.raises(BackendError) as raised:
        load_definition_catalog((source,), bindings)

    assert raised.value.code == "CORPUS_DEFINITION_SOURCE_MISMATCH"
    assert str(tmp_path) not in str(raised.value.details)


def test_catalog_rejects_a_linked_binding(tmp_path):
    path = _copy_fixture(tmp_path)
    source = _source(path, "4.6.2")
    link_root = tmp_path / "linked"
    link_root.mkdir()
    linked = link_root / "master.pslx"
    try:
        linked.symlink_to(path)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(BackendError) as raised:
        load_definition_catalog((source,), {source.keys[0]: linked})

    assert raised.value.code == "CORPUS_DEFINITION_SOURCE_MISMATCH"


def test_catalog_preserves_duplicates_until_exact_lookup(tmp_path):
    path = _copy_fixture(tmp_path)
    text = path.read_text(encoding="utf-8")
    duplicate = "<Definition name=\"gain\" classid=\"UserCmpDefn\"><svg /></Definition>"
    path.write_text(text.replace("</definitions>", f"{duplicate}</definitions>"), encoding="utf-8")
    source = _source(path, "4.6.2")
    catalog = load_definition_catalog((source,), {source.keys[0]: path})

    with pytest.raises(BackendError) as raised:
        catalog.require("master", "4.6.2", "gain")

    assert raised.value.code == "CORPUS_DEFINITION_AMBIGUOUS"
    assert str(tmp_path) not in str(raised.value.details)


def test_catalog_post_generation_integrity_detects_source_change(tmp_path):
    path = _copy_fixture(tmp_path)
    source = _source(path, "4.6.2")
    catalog = load_definition_catalog((source,), {source.keys[0]: path})
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(BackendError) as raised:
        catalog.verify_unchanged()

    assert raised.value.code == "CORPUS_DEFINITION_SOURCE_MISMATCH"
    assert str(tmp_path) not in str(raised.value.details)
