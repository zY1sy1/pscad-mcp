from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from pscad_mcp.builders.blueprint.corpus_extractor import ExtractionLimits, extract_project
from pscad_mcp.builders.blueprint.corpus_models import CorpusDependency, CorpusSource
from pscad_mcp.core.backend.base import BackendError


FIXTURES = Path(__file__).parent / "fixtures" / "blueprint_corpus"


def copy_fixture(tmp_path: Path, name: str) -> Path:
    destination = tmp_path / name
    shutil.copyfile(FIXTURES / name, destination)
    return destination


def source_contract(path: Path, *, project_id: str = "minimal") -> CorpusSource:
    content = path.read_bytes()
    return CorpusSource(
        project_id=project_id,
        basename=path.name,
        byte_length=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        pscad_versions=("4.6.2",),
        dependencies=(),
    )


def extract_fixture(tmp_path: Path, name: str):
    source = copy_fixture(tmp_path, name)
    return extract_project(tmp_path, source_contract(source, project_id=source.stem.lower()))


def assert_extraction_error(source_root: Path, source: CorpusSource, code: str, limits: ExtractionLimits | None = None):
    with pytest.raises(BackendError) as raised:
        extract_project(source_root, source, limits)
    assert raised.value.code == code
    assert str(source_root) not in json.dumps(dict(raised.value.details), default=str)
    return raised.value


def test_extract_project_verifies_hash_size_and_preserves_source_bytes(tmp_path):
    source = copy_fixture(tmp_path, "minimal.pscx")
    before = source.read_bytes()
    admitted = source_contract(source)

    graph = extract_project(tmp_path, admitted)

    assert graph.project_id == "minimal"
    assert graph.source_sha256 == hashlib.sha256(before).hexdigest()
    assert graph.name == "Minimal"
    assert graph.pscad_version == "4.6.2"
    assert graph.target == "EMTDC"
    assert source.read_bytes() == before


def test_extract_project_rejects_hash_and_size_drift_without_leaking_path(tmp_path):
    source = copy_fixture(tmp_path, "minimal.pscx")
    admitted = source_contract(source)

    assert_extraction_error(tmp_path, replace(admitted, sha256="0" * 64), "CORPUS_SOURCE_HASH_MISMATCH")
    assert_extraction_error(tmp_path, replace(admitted, byte_length=admitted.byte_length + 1), "CORPUS_SOURCE_SIZE_MISMATCH")


def test_extract_project_rejects_missing_and_non_regular_sources(tmp_path):
    source = copy_fixture(tmp_path, "minimal.pscx")
    admitted = source_contract(source)
    source.unlink()
    assert_extraction_error(tmp_path, admitted, "CORPUS_SOURCE_MISSING")

    source.mkdir()
    assert_extraction_error(tmp_path, admitted, "CORPUS_SOURCE_INVALID")


def test_extract_project_rejects_symbolic_link_source(tmp_path):
    outside = copy_fixture(tmp_path, "minimal.pscx")
    link_root = tmp_path / "links"
    link_root.mkdir()
    linked = link_root / outside.name
    try:
        linked.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"file symlinks are unavailable: {error}")

    assert_extraction_error(link_root, source_contract(outside), "CORPUS_SOURCE_INVALID")


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"<project>", "CORPUS_XML_MALFORMED"),
        (b"<library name='wrong'/>", "CORPUS_XML_UNSUPPORTED_ROOT"),
        (b"<!DOCTYPE project><project name='x' version='4.6.2' Target='EMTDC'/>", "CORPUS_XML_UNSAFE"),
        (b"<!ENTITY x 'value'><project name='x' version='4.6.2' Target='EMTDC'/>", "CORPUS_XML_UNSAFE"),
    ],
)
def test_extract_project_rejects_malformed_unsupported_or_unsafe_xml(tmp_path, content, code):
    source = tmp_path / "unsafe.pscx"
    source.write_bytes(content)

    assert_extraction_error(tmp_path, source_contract(source), code)


def test_extract_project_enforces_file_element_and_text_bounds(tmp_path):
    source = copy_fixture(tmp_path, "minimal.pscx")
    admitted = source_contract(source)
    assert_extraction_error(
        tmp_path,
        admitted,
        "CORPUS_SOURCE_TOO_LARGE",
        ExtractionLimits(max_file_bytes=len(source.read_bytes()) - 1),
    )
    assert_extraction_error(
        tmp_path,
        admitted,
        "CORPUS_XML_TOO_COMPLEX",
        ExtractionLimits(max_elements=2),
    )
    assert_extraction_error(
        tmp_path,
        admitted,
        "CORPUS_XML_TOO_COMPLEX",
        ExtractionLimits(max_text_chars=1),
    )


def test_extract_project_rejects_pscad_version_outside_admitted_contract(tmp_path):
    source = copy_fixture(tmp_path, "minimal.pscx")
    admitted = replace(source_contract(source), pscad_versions=("5.0.2",))

    assert_extraction_error(tmp_path, admitted, "CORPUS_SOURCE_VERSION_MISMATCH")


def test_extract_project_verifies_declared_dependency_bytes(tmp_path):
    source = copy_fixture(tmp_path, "minimal.pscx")
    dependency_path = tmp_path / "companion.pslx"
    dependency_path.write_bytes(b"<library name='companion'/>")
    dependency = CorpusDependency(
        basename=dependency_path.name,
        byte_length=dependency_path.stat().st_size,
        sha256=hashlib.sha256(dependency_path.read_bytes()).hexdigest(),
        kind="file",
    )
    admitted = replace(source_contract(source), dependencies=(dependency,))

    graph = extract_project(tmp_path, admitted)
    assert graph.dependency_hashes == {"companion.pslx": dependency.sha256}

    dependency_path.write_bytes(b"changed")
    assert_extraction_error(tmp_path, admitted, "CORPUS_SOURCE_SIZE_MISMATCH")


def test_extract_project_detects_source_change_during_extraction(tmp_path, monkeypatch):
    source = copy_fixture(tmp_path, "minimal.pscx")
    admitted = source_contract(source)
    from pscad_mcp.builders.blueprint import corpus_extractor

    observed = iter((admitted.sha256, "f" * 64))
    monkeypatch.setattr(corpus_extractor, "sha256_file", lambda path: next(observed))

    assert_extraction_error(tmp_path, admitted, "CORPUS_SOURCE_CHANGED")


def test_project_settings_drop_identity_paths_and_volatile_fields(tmp_path):
    graph = extract_fixture(tmp_path, "privacy.pscx")
    serialized = json.dumps(graph.to_dict(), sort_keys=True, ensure_ascii=True)

    assert graph.settings == {"sample_step": "50", "time_duration": "5", "time_step": "50"}
    for denied in (
        "creator",
        "revisor",
        "private-user",
        "recent_file",
        "build_time",
        "output_filename",
        "snapshot_filename",
        "startup_filename",
        "C:\\\\Users",
        "D:\\\\private",
    ):
        assert denied not in serialized
