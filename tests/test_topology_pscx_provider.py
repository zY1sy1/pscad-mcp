from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.topology.providers.pscx import PscxSnapshotProvider


FIXTURES = Path(__file__).parent / "fixtures" / "topology"


def test_pscx_provider_extracts_components_ports_wires_labels_and_hierarchy():
    snapshot = PscxSnapshotProvider().read(FIXTURES / "ordinary.pscx", "Main")
    assert snapshot.source == "pscx"
    assert snapshot.project_name == "ordinary"
    assert snapshot.source_fingerprint and len(snapshot.source_fingerprint) == 64
    assert [component.key for component in snapshot.components] == [
        "Main:101",
        "Main:102",
    ]
    assert snapshot.components[0].ports[0].absolute == (18, 0)
    assert snapshot.conductors[0].vertices == ((18, 0), (54, 0), (54, 36))
    assert snapshot.labels[0].scope == "Main"


def test_pscx_provider_keeps_electrical_and_data_namespaces_separate():
    snapshot = PscxSnapshotProvider().read(
        FIXTURES / "mixed_signal.pscx", "Main"
    )
    assert {label.namespace for label in snapshot.labels} == {
        "electrical",
        "data",
    }


def test_pscx_provider_reads_in_file_custom_definition_ports():
    snapshot = PscxSnapshotProvider().read(
        FIXTURES / "custom_library.pscx", "Main"
    )
    component = snapshot.components[0]
    assert component.definition == "custom_library:meter"
    assert [
        (port.name, port.relative, port.absolute) for port in component.ports
    ] == [
        ("IN", (-18, 0), (18, 36)),
        ("OUT", (18, 0), (54, 36)),
    ]


def test_definition_cache_invalidates_on_source_hash_change(tmp_path):
    source = (FIXTURES / "custom_library.pscx").read_text(encoding="utf-8")
    project = tmp_path / "custom_library.pscx"
    project.write_text(source, encoding="utf-8")
    provider = PscxSnapshotProvider()
    first = provider.read(project, "Main")
    project.write_text(
        source.replace('name="OUT"', 'name="OUT2"'),
        encoding="utf-8",
    )
    second = provider.read(project, "Main")
    assert [port.name for port in first.components[0].ports] == ["IN", "OUT"]
    assert [port.name for port in second.components[0].ports] == ["IN", "OUT2"]


def test_pscx_provider_reports_reachable_nested_definition_and_page_port():
    snapshot = PscxSnapshotProvider().read(
        FIXTURES / "hierarchy.pscx", "Main"
    )
    assert {canvas.key for canvas in snapshot.canvases} == {
        "Main",
        "Main/101:SubSystem",
    }
    nested = next(canvas for canvas in snapshot.canvases if canvas.key != "Main")
    assert nested.parent_key == "Main"
    assert nested.page_ports == (
        "Main/101:SubSystem:IN",
        "Main/101:SubSystem:OUT",
    )
    assert [link.key for link in snapshot.boundary_links] == [
        "Main:101:IN->Main/101:SubSystem:IN",
        "Main:101:OUT->Main/101:SubSystem:OUT",
    ]


def test_pscx_provider_rejects_invalid_source_with_bounded_details(tmp_path):
    source = tmp_path / "broken.pscx"
    source.write_text("<project>", encoding="utf-8")
    with pytest.raises(BackendError) as raised:
        PscxSnapshotProvider().read(source, "Main")
    assert raised.value.code == "TOPOLOGY_SOURCE_INVALID"
    assert raised.value.details == {
        "file": "broken.pscx",
        "canvas": "Main",
        "reason": "xml_parse_error",
    }


def test_invalid_explicit_orientation_leaves_port_geometry_unresolved(tmp_path):
    source = tmp_path / "invalid_orientation.pscx"
    source.write_text(
        """<project name="case" version="4.6.2">
<Definition name="Main"><schematic>
<User classid="UserCmp" id="1" defn="master:resistor"
      x="10" y="20" orientation="invalid">
  <Port name="P" kind="electrical" dimension="1" x="18" y="0" />
</User>
</schematic></Definition></project>""",
        encoding="utf-8",
    )
    snapshot = PscxSnapshotProvider().read(source, "Main")
    assert snapshot.components[0].orientation is None
    assert snapshot.components[0].ports[0].absolute is None
    assert snapshot.unresolved == ("port_geometry_unresolved:Main:1:P",)


def test_pscx_provider_classifies_licensed_user_label_definitions(tmp_path):
    source = tmp_path / "licensed_labels.pscx"
    source.write_text(
        """<project name="case" version="4.6.2">
<Definition name="Main"><schematic>
  <User classid="UserCmp" id="7" defn="master:resistor"
        x="0" y="0" orient="0">
    <Port name="A" kind="electrical" dimension="1" x="0" y="0" />
  </User>
  <User classid="UserCmp" id="110" name="master:nodelabel"
        defn="master:nodelabel" x="10" y="20" orient="0"
        namespace="electrical">
    <paramlist><param name="Name" value="N_CONFLICT" /></paramlist>
  </User>
  <User classid="UserCmp" id="111" name="master:datalabel"
        defn="master:datalabel" x="30" y="40" orient="0"
        namespace="data">
    <paramlist><param name="Name" value="D_CONFLICT" /></paramlist>
  </User>
</schematic></Definition></project>""",
        encoding="utf-8",
    )

    snapshot = PscxSnapshotProvider().read(source, "Main")

    assert [component.object_id for component in snapshot.components] == ["7"]
    assert [
        (label.object_id, label.name, label.namespace)
        for label in snapshot.labels
    ] == [
        ("110", "N_CONFLICT", "electrical"),
        ("111", "D_CONFLICT", "data"),
    ]
