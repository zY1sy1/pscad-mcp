from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from pscad_mcp.builders.blueprint.corpus_extractor import ExtractionLimits, extract_project, graph_signature
from pscad_mcp.builders.blueprint.corpus_models import CorpusDependency, CorpusSource, CorpusWarning
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


def test_extract_project_normalizes_definitions_components_ports_connections_and_outputs(tmp_path):
    graph = extract_fixture(tmp_path, "minimal.pscx")

    controller = next(definition for definition in graph.definitions if definition.name == "Controller")
    assert controller.key == "definition:user:controller"
    assert controller.parameters[0].to_dict() == {
        "name": "Kp",
        "type": "real",
        "dimension": "1",
        "units": "pu",
        "minimum": "0",
        "maximum": "10",
        "intent": "input",
        "default": "1.0",
    }
    assert controller.ports[0].key == "definition:user:controller/port:in#1"
    assert controller.ports[0].offset == (-36, 0)
    assert {canvas.key for canvas in graph.canvases} == {"canvas:controller", "canvas:main"}
    assert graph.components[0].key == "canvas:main/component:controller@198,270#1"
    assert graph.components[0].definition_key == "definition:user:controller"
    assert graph.components[0].parameters == {"Kp": "2.0"}
    assert any(connection.kind == "wireorthogonal" for connection in graph.connections)
    assert any(connection.kind == "hierarchy" for connection in graph.connections)
    assert graph.output_channels[0].key == "output:0:ctrl-out"
    assert graph.output_channels[0].source_component == graph.components[0].key
    assert graph.output_channels[0].units == "pu"
    assert graph.output_channels[0].resolved is True


def test_logical_graph_signature_is_stable_when_runtime_ids_change(tmp_path):
    source = copy_fixture(tmp_path, "minimal.pscx")
    first = extract_project(tmp_path, source_contract(source))
    changed = source.read_text(encoding="utf-8")
    changed = changed.replace('id="101"', 'id="901"').replace('link="101"', 'link="901"').replace('id="101:0"', 'id="901:0"')
    changed = changed.replace('id="201"', 'id="902"').replace('id="8001"', 'id="9801"').replace('id="8002"', 'id="9802"')
    source.write_text(changed, encoding="utf-8")
    second = extract_project(tmp_path, source_contract(source))

    assert graph_signature(first) == graph_signature(second)
    assert first.components[0].key == second.components[0].key
    assert first.connections[0].key == second.connections[0].key
    assert first.output_channels[0].key == second.output_channels[0].key


def test_graph_output_contains_no_runtime_ids_or_denied_output_metadata(tmp_path):
    graph = extract_fixture(tmp_path, "minimal.pscx")
    serialized = json.dumps(graph.to_dict(), sort_keys=True, ensure_ascii=True)

    assert '"runtime_id"' not in serialized
    assert '"link"' not in serialized
    assert '"date"' not in serialized
    assert '"time"' not in serialized
    assert "2026/08/27" not in serialized
    assert "21:00:00" not in serialized


def test_dangling_local_definition_reference_fails_closed(tmp_path):
    source = copy_fixture(tmp_path, "dangling.pscx")

    assert_extraction_error(tmp_path, source_contract(source), "CORPUS_REFERENCE_UNRESOLVED")


def test_unknown_elements_are_bounded_path_only_warnings(tmp_path):
    graph = extract_fixture(tmp_path, "unknown-editor-state.pscx")

    assert graph.warnings == (
        CorpusWarning("unknown_element", "project/editorState", 1, False),
        CorpusWarning("unknown_element", "project/definitions/Definition/schematic/TopologyMystery", 1, True),
    )
    serialized = json.dumps(graph.to_dict(), sort_keys=True, ensure_ascii=True)
    assert "privatePath" not in serialized
    assert "never copy this" not in serialized
    assert "secret" not in serialized


def test_duplicate_definition_logical_key_fails_closed(tmp_path):
    content = b"""<project name='Duplicate' version='4.6.2' Target='EMTDC'><definitions>
    <Definition classid='UserCmpDefn' name='Same'><schematic /></Definition>
    <Definition classid='UserCmpDefn' name='same'><schematic /></Definition>
    </definitions></project>"""
    source = tmp_path / "duplicate.pscx"
    source.write_bytes(content)

    assert_extraction_error(tmp_path, source_contract(source), "CORPUS_LOGICAL_KEY_COLLISION")


def test_dangling_output_binding_is_explicit_without_retaining_runtime_id(tmp_path):
    source = copy_fixture(tmp_path, "minimal.pscx")
    content = source.read_text(encoding="utf-8").replace('id="101:0"', 'id="999:0"')
    source.write_text(content, encoding="utf-8")

    graph = extract_project(tmp_path, source_contract(source))

    assert graph.output_channels[0].resolved is False
    assert graph.output_channels[0].source_component is None
    assert graph.output_channels[0].source_port == "0"
    assert CorpusWarning("unresolved_output_binding", "project/output/analog/channel", 1, False) in graph.warnings
    assert "999" not in json.dumps(graph.to_dict(), sort_keys=True)


def test_duplicate_parameter_names_preserve_paramlist_scope(tmp_path):
    graph = extract_fixture(tmp_path, "duplicate-param-groups.pscx")

    assert graph.components[0].parameters == {
        "group-1:ymin": "-1",
        "group-2:ymin": "-2",
        "title": "A",
    }


def test_virtual_station_hierarchy_root_is_normalized_without_runtime_link(tmp_path):
    graph = extract_fixture(tmp_path, "minimal.pscx")
    hierarchy = [connection for connection in graph.connections if connection.kind == "hierarchy"]

    assert hierarchy[0].endpoints == ("hierarchy-root:station", graph.components[0].key)
    assert hierarchy[1].endpoints == ("project:minimal", "hierarchy-root:station")


def test_missing_nested_hierarchy_target_still_fails_closed(tmp_path):
    source = copy_fixture(tmp_path, "minimal.pscx")
    content = source.read_text(encoding="utf-8").replace('link="101" name="Minimal:Controller"', 'link="7777" name="Minimal:Controller"')
    source.write_text(content, encoding="utf-8")

    assert_extraction_error(tmp_path, source_contract(source), "CORPUS_REFERENCE_UNRESOLVED")


def test_pscad_wire_branch_stub_is_a_bounded_builtin_definition(tmp_path):
    graph = extract_fixture(tmp_path, "wire-branch-stub.pscx")
    branch = next(connection for connection in graph.connections if connection.kind == "wirebranch")
    nested = next(component for component in graph.components if component.canvas_key == "canvas:station")

    assert branch.source_definition == "definition:builtin:stub"
    assert nested.definition_key == "definition:user:main"
