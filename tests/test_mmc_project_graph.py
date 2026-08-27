from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.project_graph import read_project_graph


NS = "urn:pscad"
ET.register_namespace("", NS)


def _tag(name: str) -> str:
    return f"{{{NS}}}{name}"


def _write_namespaced_fixture(path: Path) -> None:
    root = ET.Element(_tag("pscx"))
    project = ET.SubElement(root, _tag("project"), {"name": "fixture"})
    canvas = ET.SubElement(project, _tag("canvas"), {"name": "Main"})
    component = ET.SubElement(canvas, _tag("component"), {"id": "arm", "definition": "cigre_mmc_avm_v1:MMCAverageArm", "x": "10", "y": "20", "orientation": "1"})
    ET.SubElement(component, _tag("port"), {"name": "AC", "kind": "electrical", "dimension": "1"})
    net = ET.SubElement(canvas, _tag("net"), {"id": "ac", "kind": "electrical", "label": "AC"})
    ET.SubElement(net, _tag("endpoint"), {"component": "arm", "port": "AC"})
    output = ET.SubElement(canvas, _tag("output"), {"id": "p", "path": "Main/P", "units": "MW", "role": "station_ac_active_power"})
    output.set("measurement", "arm:AC")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def test_graph_reader_is_namespace_aware_and_retains_source_evidence(tmp_path):
    path = tmp_path / "fixture.pscx"
    _write_namespaced_fixture(path)
    graph = read_project_graph(path)
    assert graph.project_name == "fixture"
    assert graph.components[0].definition == "cigre_mmc_avm_v1:MMCAverageArm"
    assert graph.components[0].ports[0].dimension == 1
    assert graph.components[0].orientation == 1
    assert graph.nets[0].kind == "electrical"
    assert graph.outputs[0].path == "Main/P"
    assert graph.components[0].source["element"] == "component"
    assert graph.nets[0].source["element"] == "net"


def test_graph_reader_rejects_duplicate_component_and_invalid_xml(tmp_path):
    path = tmp_path / "duplicate.pscx"
    _write_namespaced_fixture(path)
    tree = ET.parse(path)
    canvas = tree.getroot().find(f".//{_tag('canvas')}")
    assert canvas is not None
    duplicate = list(canvas)[0]
    canvas.append(ET.fromstring(ET.tostring(duplicate)))
    tree.write(path, encoding="utf-8", xml_declaration=True)
    with pytest.raises(BackendError) as raised:
        read_project_graph(path)
    assert raised.value.code == "MMC_STRUCTURE_INVALID"

    invalid = tmp_path / "invalid.pscx"
    invalid.write_text("<pscx", encoding="utf-8")
    with pytest.raises(BackendError) as raised:
        read_project_graph(invalid)
    assert raised.value.code == "MMC_STRUCTURE_INVALID"
