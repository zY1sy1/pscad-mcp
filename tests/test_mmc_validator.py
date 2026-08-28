from __future__ import annotations

import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pscad_mcp.hvdc.builders.mmc.project_graph import read_project_graph
from pscad_mcp.hvdc.builders.mmc.schema import parse_blueprint
from pscad_mcp.hvdc.builders.mmc.validator import validate_project_graph


ASSET_ROOT = Path(__file__).parents[1] / "pscad_mcp" / "assets" / "mmc" / "cigre_b4_p2p_avm_v1"
BLUEPRINT = parse_blueprint(json.loads((ASSET_ROOT / "blueprint.json").read_text(encoding="utf-8")))
NS = "urn:pscad"
ET.register_namespace("", NS)


def tag(name: str) -> str:
    return f"{{{NS}}}{name}"


def _component(canvas, logical_id, definition, x, y, ports, *, role=None):
    attrs = {"id": logical_id, "definition": definition, "x": str(x), "y": str(y), "orientation": "0"}
    if role:
        attrs["role"] = role
    component = ET.SubElement(canvas, tag("component"), attrs)
    for name, kind, dimension in ports:
        ET.SubElement(component, tag("port"), {"name": name, "kind": kind, "dimension": str(dimension)})
    return component


ARM_PORTS = [(name, "electrical" if name in {"AC", "DC_POS", "DC_NEG"} else "signal", 1) for name in ("AC", "DC_POS", "DC_NEG", "V_INSERTED", "I_ARM", "ENERGY")]


def _valid_tree():
    root = ET.Element(tag("pscx"))
    canvas = ET.SubElement(ET.SubElement(root, tag("project"), {"name": "fixture"}), tag("canvas"), {"name": "Main"})
    for station_index, station in enumerate(("STATION_P", "STATION_VDC")):
        x_offset = station_index * 500
        for phase_index, phase in enumerate(("A", "B", "C")):
            for arm_index, arm in enumerate(("upper", "lower")):
                _component(canvas, f"{station}.{phase}.{arm}", "cigre_mmc_avm_v1:MMCAverageArm", x_offset + phase_index * 80, arm_index * 60, ARM_PORTS, role=arm)
        _component(canvas, f"{station}.control", "cigre_mmc_avm_v1:MMCStationControl", x_offset, 250, [("P_ORDER", "signal", 1), ("Q_ORDER", "signal", 1), ("VDC_ORDER", "signal", 1), ("GATES", "signal", 6)], role="control")
        _component(canvas, f"{station}.positive_bus", "master:dc_bus", x_offset + 220, 0, [("DC", "electrical", 1)])
        _component(canvas, f"{station}.negative_bus", "master:dc_bus", x_offset + 220, 300, [("DC", "electrical", 1)])
        for phase_index, phase in enumerate(("A", "B", "C")):
            _component(canvas, f"{station}.{phase}.midpoint", "master:midpoint", x_offset + phase_index * 80, 120, [("PHASE", "electrical", 1)])
    _component(canvas, "dc_positive_line", "master:dc_cable", 500, 0, [("IN", "electrical", 1), ("OUT", "electrical", 1)])
    _component(canvas, "dc_negative_line", "master:dc_cable", 500, 300, [("IN", "electrical", 1), ("OUT", "electrical", 1)])
    _component(canvas, "STATION_P.ac", "master:source3", 0, 400, [("AC", "electrical", 1)])
    _component(canvas, "STATION_VDC.ac", "master:source3", 500, 400, [("AC", "electrical", 1)])

    def net(net_id, kind, endpoints):
        node = ET.SubElement(canvas, tag("net"), {"id": net_id, "kind": kind})
        for component, port in endpoints:
            ET.SubElement(node, tag("endpoint"), {"component": component, "port": port})
        return node

    positive = [("STATION_P.positive_bus", "DC"), ("dc_positive_line", "IN"), ("dc_positive_line", "OUT"), ("STATION_VDC.positive_bus", "DC")]
    negative = [("STATION_P.negative_bus", "DC"), ("dc_negative_line", "IN"), ("dc_negative_line", "OUT"), ("STATION_VDC.negative_bus", "DC")]
    for station in ("STATION_P", "STATION_VDC"):
        positive += [(f"{station}.{phase}.{arm}", "DC_POS") for phase in ("A", "B", "C") for arm in ("upper", "lower")]
        negative += [(f"{station}.{phase}.{arm}", "DC_NEG") for phase in ("A", "B", "C") for arm in ("upper", "lower")]
    net("dc_positive_conductor", "electrical", positive)
    net("dc_negative_conductor", "electrical", negative)
    for station in ("STATION_P", "STATION_VDC"):
        for phase in ("A", "B", "C"):
            for arm in ("upper", "lower"):
                net(f"{station}.{phase}.{arm}.ac", "electrical", [(f"{station}.{phase}.{arm}", "AC"), (f"{station}.{phase}.midpoint", "PHASE")])
    data_endpoints = []
    for station in ("STATION_P", "STATION_VDC"):
        data_endpoints.extend([(f"{station}.control", "P_ORDER"), (f"{station}.control", "Q_ORDER"), (f"{station}.control", "VDC_ORDER")])
        data_endpoints.extend([(f"{station}.{phase}.{arm}", port) for phase in ("A", "B", "C") for arm in ("upper", "lower") for port in ("V_INSERTED", "I_ARM", "ENERGY")])
    net("control_signals", "data", data_endpoints)
    for output in BLUEPRINT.outputs:
        ET.SubElement(canvas, tag("output"), {"id": output.logical_id, "path": output.path, "role": output.role, "units": output.units, "measurement": "STATION_P.A.upper:AC"})
    return root


def _write_graph(tmp_path: Path, root=None) -> Path:
    path = tmp_path / "case.pscx"
    ET.ElementTree(_valid_tree() if root is None else root).write(path, encoding="utf-8", xml_declaration=True)
    return path


def test_validator_accepts_valid_graph_and_rejects_duplicate_output_selector(tmp_path):
    root = _valid_tree()
    path = _write_graph(tmp_path, root)
    graph = read_project_graph(path)
    report = validate_project_graph(graph, BLUEPRINT)
    assert report["valid"] is True
    assert report["observed"]["arm_count"] == 12
    assert report["observed"]["phase_midpoint_count"] == 6
    assert report["observed"]["positive_dc_terminal_count"] == 2
    assert report["observed"]["negative_dc_terminal_count"] == 2
    assert report["observed"]["output_count"] == len(BLUEPRINT.outputs)

    outputs = root.find(f".//{tag('canvas')}")
    assert outputs is not None
    output_nodes = outputs.findall(tag("output"))
    output_nodes[1].set("path", "Main/STATION_P/Q_AC")
    output_nodes[1].set("id", "q")
    path = _write_graph(tmp_path, root)
    report = validate_project_graph(read_project_graph(path), BLUEPRINT)
    assert report["valid"] is False
    assert any(finding["code"] == "MMC_OUTPUT_INCOMPLETE" for finding in report["findings"])


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("missing_arm", "MMC_STRUCTURE_INVALID"),
        ("unconnected_arm", "MMC_STRUCTURE_INVALID"),
        ("wrong_dimension", "MMC_PORT_MISMATCH"),
        ("crossed_pole", "MMC_STRUCTURE_INVALID"),
        ("ac_dc_short", "MMC_STRUCTURE_INVALID"),
        ("mixed_net", "MMC_PORT_MISMATCH"),
        ("missing_controller_signal", "MMC_CONTROL_INFEASIBLE"),
        ("missing_midpoint", "MMC_STRUCTURE_INVALID"),
    ],
)
def test_validator_reports_required_structural_mutations(tmp_path, mutation, code):
    root = _valid_tree()
    canvas = root.find(f".//{tag('canvas')}")
    assert canvas is not None
    if mutation == "missing_arm":
        node = canvas.find(f"{tag('component')}[@id='STATION_P.A.upper']")
        canvas.remove(node)
    elif mutation == "unconnected_arm":
        for net in canvas.findall(tag("net")):
            for endpoint in list(net.findall(tag("endpoint"))):
                if endpoint.get("component") == "STATION_P.A.upper" and endpoint.get("port") == "DC_POS":
                    net.remove(endpoint)
    elif mutation == "wrong_dimension":
        port = canvas.find(f"{tag('component')}[@id='STATION_P.A.upper']/{tag('port')}[@name='AC']")
        port.set("dimension", "3")
    elif mutation == "crossed_pole":
        net = canvas.find(f"{tag('net')}[@id='dc_positive_conductor']")
        ET.SubElement(net, tag("endpoint"), {"component": "STATION_P.negative_bus", "port": "DC"})
    elif mutation == "ac_dc_short":
        net = ET.SubElement(canvas, tag("net"), {"id": "short", "kind": "electrical"})
        ET.SubElement(net, tag("endpoint"), {"component": "STATION_P.ac", "port": "AC"})
        ET.SubElement(net, tag("endpoint"), {"component": "STATION_P.positive_bus", "port": "DC"})
    elif mutation == "mixed_net":
        net = canvas.find(f"{tag('net')}[@id='control_signals']")
        net.set("kind", "electrical")
    elif mutation == "missing_controller_signal":
        net = canvas.find(f"{tag('net')}[@id='control_signals']")
        for endpoint in list(net.findall(tag("endpoint"))):
            if endpoint.get("component") == "STATION_P.control":
                net.remove(endpoint)
    elif mutation == "missing_midpoint":
        node = canvas.find(f"{tag('component')}[@id='STATION_P.A.midpoint']")
        canvas.remove(node)
    path = _write_graph(tmp_path, root)
    report = validate_project_graph(read_project_graph(path), BLUEPRINT)
    assert report["valid"] is False
    assert any(finding["code"] == code for finding in report["findings"])
