from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.project_graph import read_project_graph
from pscad_mcp.topology.models import DefinitionPortContract


def fixture(tmp_path, right_kind="data"):
    path = tmp_path / "native.pscx"
    label = "datalabel" if right_kind == "data" else "nodelabel"
    path.write_text(
        f"""<project name="native" version="4.6.2" Target="EMTDC"><definitions>
<Definition name="Main"><schematic>
<User classid="UserCmp" id="1" defn="master:driver" x="0" y="0" orient="0"><paramlist/></User>
<User classid="UserCmp" id="2" defn="master:{label}" x="36" y="0" orient="0"><paramlist><param name="Name" value="CONTROL"/></paramlist></User>
<User classid="UserCmp" id="3" defn="master:receiver" x="72" y="0" orient="0"><paramlist/></User>
<User classid="UserCmp" id="4" defn="master:datalabel" x="108" y="0" orient="0"><paramlist><param name="Name" value="CONTROL"/></paramlist></User>
<Wire classid="WireOrthogonal" id="5" x="0" y="0"><vertex x="0" y="0"/><vertex x="36" y="0"/></Wire>
<Wire classid="WireOrthogonal" id="6" x="72" y="0"><vertex x="0" y="0"/><vertex x="36" y="0"/></Wire>
</schematic></Definition></definitions></project>""",
        encoding="ascii",
    )
    return path


CONTRACTS = {
    name: (DefinitionPortContract("X", "data", 1, (0, 0)),)
    for name in ("master:driver", "master:receiver")
}


def test_native_reader_recovers_real_wires_and_data_label_aliases(tmp_path):
    graph = read_project_graph(fixture(tmp_path), definition_ports=CONTRACTS)
    assert graph.source["native_component_count"] == 2
    assert graph.source["native_wire_count"] == 2
    assert graph.source["native_label_count"] == 2
    assert len(graph.nets) == 1
    assert graph.nets[0].kind == "data"
    assert len(graph.nets[0].endpoints) == 2
    assert graph.source["unresolved"] == ()


def test_native_reader_rejects_data_wire_into_electrical_label(tmp_path):
    with pytest.raises(BackendError, match="electrical and data"):
        read_project_graph(fixture(tmp_path, "electrical"), definition_ports=CONTRACTS)


def test_native_reader_reports_missing_external_port_evidence(tmp_path):
    graph = read_project_graph(fixture(tmp_path))
    assert len(graph.components) == 2
    assert graph.source["unresolved"]


def test_native_reader_detects_deleted_wire(tmp_path):
    from xml.etree import ElementTree as ET

    path = fixture(tmp_path)
    tree = ET.parse(path)
    canvas = tree.find(".//schematic")
    canvas.remove(canvas.find("Wire[@id='6']"))
    tree.write(path)
    graph = read_project_graph(path, definition_ports=CONTRACTS)
    assert graph.source["native_wire_count"] == 1
    assert not any(len(net.endpoints) == 2 for net in graph.nets)


def test_native_control_script_is_not_a_conductor_and_ports_keep_native_types(tmp_path):
    path = tmp_path / "control.pscx"
    path.write_text(
        """<project name="control" version="4.6.2"><definitions>
<Definition name="Main"><schematic><User classid="UserCmp" id="1" defn="control:Drive" x="0" y="0" orient="0"/></schematic></Definition>
<Definition classid="UserCmpDefn" name="Drive"><svg>
<port name="IN" model="Natural" type="NonRemovable" dim="1" x="-18" y="0">true</port>
<port name="OUT" model="Transfer" type="Real" dim="1" x="18" y="0">true</port>
</svg><script><segment name="Fortran">$OUT = 1.0</segment></script></Definition>
</definitions></project>""",
        encoding="ascii",
    )
    graph = read_project_graph(path)
    assert {port.name: port.kind for port in graph.components[0].ports} == {
        "IN": "electrical",
        "OUT": "signal",
    }
    assert graph.source["native_wire_count"] == 0
    assert not any(
        "conductor_geometry" in issue for issue in graph.source["unresolved"]
    )


def test_cable_geometry_wrapper_does_not_short_remote_ports(tmp_path):
    path = tmp_path / "cable.pscx"
    path.write_text(
        """<project name="cable"><definitions><Definition name="Main"><schematic>
<Wire classid="Cable" id="1" x="0" y="0"><vertex x="0" y="0"/><vertex x="100" y="0"/>
<User classid="UserCmp" id="2" defn="cable:Cable2" x="0" y="0"/></Wire>
</schematic></Definition><Definition classid="RowDefn" name="Cable2"/></definitions></project>""",
        encoding="ascii",
    )
    graph = read_project_graph(path)
    assert graph.source["native_wire_count"] == 0
    assert graph.components == ()
    assert graph.nets == ()
