from pathlib import Path

import pytest

from pscad_mcp.hvdc.builders.lcc.catalog import parse_catalog
from pscad_mcp.hvdc.builders.lcc.project_graph import read_project_graph


FIXTURE = Path(__file__).parent / "fixtures" / "lcc" / "graph_case.pscx"
CATALOG = {
    "schema_version": 1,
    "name": "cigre_lcc_monopole_v1",
    "pscad_version": "4.6.2",
    "identity": "graph-test",
    "definitions": [
        {
            "scoped_name": "master:source3",
            "ports": [{"name": "ac", "kind": "electrical", "dimension": 3, "offset": [10, 0]}],
            "parameters": {},
        },
        {
            "scoped_name": "cigre_lcc_v1:LCC12PulseBridge",
            "ports": [{"name": "ac", "kind": "electrical", "dimension": 3, "offset": [-10, 0]}],
            "parameters": {},
        },
        {
            "scoped_name": "master:line",
            "ports": [{"name": "p", "kind": "electrical", "dimension": 1, "offset": [-10, 0]}],
            "parameters": {},
        },
    ],
}


def test_read_project_graph_normalizes_components_ports_wires_labels_and_nets():
    graph = read_project_graph(FIXTURE, parse_catalog(CATALOG))

    assert [component.logical_id for component in graph.components] == ["bridge", "load", "source"]
    source = next(component for component in graph.components if component.logical_id == "source")
    bridge = next(component for component in graph.components if component.logical_id == "bridge")
    assert source.parameters == {"Amplitude": "230", "Mode": "balanced"}
    assert source.ports[0].absolute == (10, 0)
    assert bridge.ports[0].absolute == (110, 0)
    assert graph.wires[0].vertices == ((10, 0), (50, 0), (50, 20), (90, 20))
    assert len(graph.labels) == 2
    assert len(graph.nets) == 2
    assert any(net.kind == "electrical" for net in graph.nets)
    data_net = next(net for net in graph.nets if net.kind == "data")
    assert data_net.labels == ("ENABLE",)
    assert data_net.points == ((20, 40), (120, 40))


def test_generated_metadata_and_hierarchy_order_do_not_change_normalized_graph(tmp_path):
    original = FIXTURE.read_text(encoding="utf-8")
    mutated = (
        original.replace('id="generated-project"', 'id="different-project"')
        .replace('crc="deadbeef"', 'crc="other-crc"')
        .replace('link="old-link"', 'link="new-link"')
        .replace('date="2026-08-19"', 'date="2030-01-01"')
        .replace('call_order="9"', 'call_order="1"')
    )
    changed = tmp_path / "changed.pscx"
    changed.write_text(mutated, encoding="utf-8")

    original_graph = read_project_graph(FIXTURE, parse_catalog(CATALOG))
    changed_graph = read_project_graph(changed, parse_catalog(CATALOG))
    assert original_graph == changed_graph
    assert original_graph.to_dict() == changed_graph.to_dict()


def test_real_pscx_shape_uses_catalog_ports_orientation_and_wire_origin(tmp_path):
    path = tmp_path / "real_shape.pscx"
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<project name="real_shape" version="4.6.2">
  <definitions>
    <Definition name="Main" classid="UserCmpDefn">
      <schematic classid="UserCanvas">
        <User classid="UserCmp" id="201" name="source" defn="master:source3" x="0" y="0" orient="0" />
        <User classid="UserCmp" id="202" name="bridge" defn="cigre_lcc_v1:LCC12PulseBridge" x="100" y="50" orient="1" />
        <Wire classid="WireBranch" id="203" x="10" y="20" orient="0">
          <vertex x="0" y="0" />
          <vertex x="10" y="0" />
        </Wire>
      </schematic>
    </Definition>
  </definitions>
</project>
""",
        encoding="utf-8",
    )

    graph = read_project_graph(path, parse_catalog(CATALOG))
    bridge = next(component for component in graph.components if component.logical_id == "bridge")

    assert bridge.ports[0].absolute == (100, 40)
    assert graph.wires[0].vertices == ((10, 20), (20, 20))
    source = next(component for component in graph.components if component.logical_id == "source")
    with pytest.raises(TypeError):
        source.parameters["new"] = "value"
