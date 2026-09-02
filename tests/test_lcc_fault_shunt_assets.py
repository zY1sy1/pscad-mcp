from __future__ import annotations

import json
from pathlib import Path

from pscad_mcp.core.master_bindings import parse_master_binding_registry
from pscad_mcp.hvdc.builders.lcc.assets import load_packaged_asset_set
from pscad_mcp.hvdc.builders.lcc.catalog import parse_catalog


ROOT = Path(__file__).parents[1]
ASSET_ROOT = ROOT / "pscad_mcp" / "assets" / "lcc" / "cigre_lcc_monopole_v1"


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
    assert event["apply_value"] == 1
    assert event["clear_value"] == 0
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
    assert any(item.logical_name == "master:dynamic_output_channel" for item in registry.bindings)
    assert all(item.logical_name != "master:dynamic_signal_export" for item in registry.bindings)
    assert load_packaged_asset_set().blueprint.dynamic_events[0]["control_components"]
