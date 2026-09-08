from __future__ import annotations

import json
from pathlib import Path

from pscad_mcp.core.master_bindings import parse_master_binding_registry
from pscad_mcp.hvdc.builders.lcc.assets import load_packaged_asset_set
from pscad_mcp.hvdc.builders.lcc.catalog import parse_catalog


ROOT = Path(__file__).parents[1]
ASSET_ROOT = ROOT / "pscad_mcp" / "assets" / "lcc" / "cigre_lcc_monopole_v1"


def test_fault_shunts_invert_breaker_command_without_inverting_event_signal():
    blueprint = json.loads((ASSET_ROOT / "blueprint.json").read_text(encoding="utf-8"))
    dynamic = json.loads((ASSET_ROOT / "dynamic.json").read_text(encoding="utf-8"))
    components = {item["logical_id"]: item for item in blueprint["components"]}
    nets = {item["logical_id"]: item for item in blueprint["nets"]}
    event = blueprint["dynamic_events"][0]

    assert event["control_signal"] == "LCC_FAULT_OPEN"
    assert event["event_signal"] == "LCC_FAULT_ACTIVE"
    assert (event["apply_value"], event["clear_value"]) == (0, 1)
    assert dynamic["event"]["control_signal"] == event["control_signal"]
    assert dynamic["event"]["event_signal"] == event["event_signal"]
    assert components["fault_open_adapter"]["definition"] == "master:fault_control_not"
    assert components["fault_open_signal"]["definition"] == "master:main_signal_import"
    assert components["fault_open_signal"]["parameters"] == {"Name": "LCC_FAULT_OPEN"}
    assert nets["inverter_fault_active_integer"]["label"] == event["event_signal"]
    assert nets["inverter_fault_active_integer"]["endpoints"] == [
        {"component": "inverter_fault_timer", "port": "Y"},
        {"component": "fault_active_adapter", "port": "IN"},
        {"component": "fault_open_adapter", "port": "IN"},
    ]
    assert nets["inverter_fault_open_integer"]["label"] == event["control_signal"]
    assert nets["inverter_fault_open_integer"]["endpoints"] == [
        {"component": "fault_open_adapter", "port": "OUT"},
        {"component": "fault_open_signal", "port": "OUT"},
    ]
    assert {components[name]["parameters"]["NAME"] for name in event["control_components"]} == {
        "LCC_FAULT_OPEN"
    }


def test_fault_control_routes_preserve_three_separate_signal_nets():
    from pscad_mcp.hvdc.builders.lcc.routing import absolute_port, route_intersects_rectangles
    from pscad_mcp.topology.connectivity import build_connectivity
    from pscad_mcp.topology.models import ProjectTopology, TopologyConductor

    blueprint = json.loads((ASSET_ROOT / "blueprint.json").read_text(encoding="utf-8"))
    catalog = parse_catalog(json.loads((ASSET_ROOT / "catalog-pscad-4.6.2.json").read_text(encoding="utf-8")))
    components = {item["logical_id"]: item for item in blueprint["components"]}
    names = {"inverter_fault_active_integer", "inverter_fault_open_integer", "inverter_fault_active_signal"}
    conductors = []
    for net in blueprint["nets"]:
        if net["logical_id"] not in names:
            continue
        endpoints = []
        for endpoint in net["endpoints"]:
            component = components[endpoint["component"]]
            port = next(port for port in catalog.definitions[component["definition"]].ports if port.name == endpoint["port"])
            endpoints.append(absolute_port((component["location"]["x"], component["location"]["y"]), port.offset, component["orientation"]))
        vertices = tuple(tuple(point) for point in net.get("route", {}).get("vertices", endpoints))
        assert all(point in vertices for point in endpoints)
        excluded = {endpoint["component"] for endpoint in net["endpoints"]}
        rectangles = []
        for name, component in components.items():
            if name in excluded:
                continue
            box = catalog.definitions[component["definition"]].bounding_box
            corners = [absolute_port((component["location"]["x"], component["location"]["y"]), corner, component["orientation"]) for corner in (box[:2], box[2:])]
            rectangles.append((min(point[0] for point in corners), min(point[1] for point in corners), max(point[0] for point in corners), max(point[1] for point in corners)))
        route_intersects_rectangles(vertices, rectangles)
        conductors.append(TopologyConductor(key=net["logical_id"], object_id=net["logical_id"], canvas_key="Main", kind="wire", namespace="data", vertices=vertices))
    topology = build_connectivity(ProjectTopology("fault_control", "4.6.2", conductors=tuple(conductors))).topology
    assert {frozenset(net.conductor_keys) for net in topology.nets} == {frozenset({name}) for name in names}


def test_packaged_asset_declares_three_phase_fault_shunt_branches():
    blueprint = json.loads((ASSET_ROOT / "blueprint.json").read_text(encoding="utf-8"))
    components = {item["logical_id"]: item for item in blueprint["components"]}
    nets = {item["logical_id"]: item for item in blueprint["nets"]}
    for phase in "abc":
        assert components[f"inverter_fault_breaker_{phase}"]["definition"] == "master:breaker1"
        assert components[f"inverter_fault_breaker_{phase}"]["orientation"] == 2
        assert components[f"inverter_fault_resistor_{phase}"]["definition"] == "master:fault_resistor"
        assert components[f"inverter_fault_ground_{phase}"]["definition"] == "master:ground"
        assert nets[f"inverter_fault_ground_{phase}"]["endpoints"] == [
            {"component": f"inverter_fault_resistor_{phase}", "port": "OUT"},
            {"component": f"inverter_fault_ground_{phase}", "port": "GND"},
        ]
    assert [2485, 137] in nets["inverter_source_a_meter"]["route"]["vertices"]
    assert [2358, 288] in nets["inverter_source_filter_b"]["route"]["vertices"]
    assert [2358, 432] in nets["inverter_source_filter_c"]["route"]["vertices"]
    assert components["fault_active_adapter"]["definition"] == "master:fault_state_integer_to_real"
    assert nets["inverter_fault_active_integer"]["endpoints"] == [
        {"component": "inverter_fault_timer", "port": "Y"},
        {"component": "fault_active_adapter", "port": "IN"},
        {"component": "fault_open_adapter", "port": "IN"},
    ]
    assert nets["inverter_fault_active_signal"]["endpoints"] == [
        {"component": "fault_active_adapter", "port": "OUT"},
        {"component": "fault_active_output", "port": "INPUT"},
    ]
    event = blueprint["dynamic_events"][0]
    assert event["control_components"] == [
        "inverter_fault_breaker_a",
        "inverter_fault_breaker_b",
        "inverter_fault_breaker_c",
    ]
    assert event["control_parameter"] == "NAME"
    assert event["apply_value"] == 0
    assert event["clear_value"] == 1
    assert any(output["path"] == "Fault/LCC Fault Active" for output in blueprint["outputs"])
    assert components["fault_active_output"]["definition"] == "master:dynamic_output_channel"
    assert components["fault_active_output"]["parameters"] == {
        "Group": "Fault",
        "Name": "LCC Fault Active",
        "Units": "state",
    }
    measurement = next(item for item in blueprint["measurements"] if item["logical_id"] == "fault_active_measurement")
    assert measurement["component"] == "fault_active_output"
    assert measurement["port"] == "INPUT"
    assert measurement["channels"] == ["Fault/LCC Fault Active"]


def test_packaged_catalog_and_registry_bind_fault_master_definitions():
    catalog = parse_catalog(json.loads((ASSET_ROOT / "catalog-pscad-4.6.2.json").read_text(encoding="utf-8")))
    registry = parse_master_binding_registry(json.loads((ASSET_ROOT / "master-bindings-pscad-4.6.2.json").read_text(encoding="utf-8")))
    breaker = next(item for item in catalog.definitions.values() if item.scoped_name == "master:breaker1")
    assert {port.name for port in breaker.ports} == {"A", "B"}
    assert {port.name: port.offset for port in breaker.ports} == {
        "A": (36, 0),
        "B": (-36, 0),
    }
    assert "NAME" in breaker.parameters
    resistor = next(item for item in catalog.definitions.values() if item.scoped_name == "master:fault_resistor")
    assert {port.name: port.offset for port in resistor.ports} == {
        "IN": (0, 0),
        "OUT": (36, 0),
    }
    assert any(item.logical_name == "master:breaker1" for item in registry.bindings)
    assert any(item.logical_name == "master:fault_resistor" for item in registry.bindings)
    assert any(item.logical_name == "master:fault_state_integer_to_real" for item in registry.bindings)
    assert registry.by_logical_name["master:fault_control_not"].physical_definition == "inv"
    assert {port.name: port.offset for port in catalog.definitions["master:fault_control_not"].ports} == {
        "IN": (0, 0), "OUT": (36, 0),
    }
    assert any(item.logical_name == "master:dynamic_output_channel" for item in registry.bindings)
    assert all(item.logical_name != "master:dynamic_signal_export" for item in registry.bindings)
    assert load_packaged_asset_set().blueprint.dynamic_events[0]["control_components"]
