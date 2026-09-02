from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.fault_event import (
    FixedLccFaultEvent,
    inspect_fixed_lcc_fault_capability,
    validate_fixed_lcc_fault_event,
)
from pscad_mcp.hvdc.builders.lcc.schema import parse_blueprint


def _asset(name: str) -> dict[str, object]:
    return json.loads(
        (
            Path(__file__).parents[1]
            / "pscad_mcp"
            / "assets"
            / "lcc"
            / "cigre_lcc_monopole_v1"
            / name
        ).read_text(encoding="utf-8")
    )


def _complete_event() -> dict[str, object]:
    return {
        "kind": "inverter_ac_disturbance",
        "target_bus": "inverter_ac_bus",
        "time_s": 0.8,
        "duration_s": 0.1,
        "phase_mask": [1, 1, 1],
    }


def _complete_blueprint() -> dict[str, object]:
    blueprint = _asset("blueprint.json")
    blueprint["components"] = [
        item
        for item in blueprint["components"]
        if not str(item.get("logical_id", "")).startswith("inverter_fault_")
    ]
    cleaned_nets = []
    for item in blueprint["nets"]:
        endpoints = [
            endpoint
            for endpoint in item.get("endpoints", [])
            if not str(endpoint.get("component", "")).startswith("inverter_fault_")
        ]
        if len(endpoints) >= 2:
            cleaned_nets.append({**item, "endpoints": endpoints})
    blueprint["nets"] = cleaned_nets
    blueprint["outputs"] = [
        item for item in blueprint["outputs"] if item.get("role") != "fault_active"
    ]
    blueprint["dynamic_events"] = []
    blueprint["dynamic_events"] = [
        {
            **_complete_event(),
            "timer_component": "inverter_fault_timer",
            "shunt_component": "inverter_fault_shunt",
            "channel": "fault_active",
            "control_mode": "embedded_emtdc",
            "control_signal": "FAULT_ACTIVE",
            "recovery_window_s": 0.5,
            "control_components": ["inverter_fault_shunt"],
            "control_parameter": "IS",
            "apply_value": 1,
            "clear_value": 0,
        }
    ]
    blueprint["components"].extend(
        [
            {
                "logical_id": "inverter_fault_timer",
                "definition": "master:tfault",
                "location": {"x": 900, "y": 800},
                "parameters": {"TF": "0.8 [s]", "DF": "0.1 [s]", "REP": 0},
                "ports": [{"name": "Y", "kind": "data", "dimension": 1}],
                "role": "fault_timer",
            },
            {
                "logical_id": "inverter_fault_shunt",
                "definition": "master:tpflt",
                "location": {"x": 840, "y": 800},
                "parameters": {"Ctype": 0, "A": 1, "B": 1, "C": 1, "G": 1},
                "ports": [
                    {"name": "N", "kind": "electrical", "dimension": 3},
                    {"name": "IS", "kind": "data", "dimension": 1},
                ],
                "role": "fault_shunt",
            },
        ]
    )
    blueprint["nets"].extend(
        [
            {
                "logical_id": "inverter_ac_bus",
                "kind": "electrical",
                "endpoints": [
                    {"component": "inverter_source", "port": "A"},
                    {"component": "inverter_fault_shunt", "port": "N"},
                ],
            },
            {
                "logical_id": "inverter_fault_trigger",
                "kind": "data",
                "endpoints": [
                    {"component": "inverter_fault_timer", "port": "Y"},
                    {"component": "inverter_fault_shunt", "port": "IS"},
                ],
            },
        ]
    )
    blueprint["outputs"].append(
        {
            "logical_id": "fault_active",
            "path": "Fault/LCC Fault Active",
            "units": "state",
            "role": "fault_active",
        }
    )
    return blueprint


def _complete_inventory() -> dict[str, object]:
    return {
        "definitions": [
            {
                "scoped_name": "master:tfault",
                "ports": [{"name": "Y", "kind": "data", "direction": "output"}],
            },
            {
                "scoped_name": "master:tpflt",
                "ports": [
                    {"name": "N", "kind": "electrical", "dimension": 3},
                    {"name": "IS", "kind": "data", "direction": "input"},
                ],
            },
        ]
    }


def _production_inventory() -> dict[str, object]:
    return {"definitions": _asset("catalog-pscad-4.6.2.json")["definitions"]}


def test_valid_fault_event_normalizes_to_immutable_contract():
    result = validate_fixed_lcc_fault_event(_complete_event())
    assert result == FixedLccFaultEvent(
        "inverter_ac_disturbance", "inverter_ac_bus", 0.8, 0.1, (1, 1, 1)
    ).to_dict()


@pytest.mark.parametrize(
    "field,value",
    [("duration_s", 0.0), ("time_s", -0.1), ("phase_mask", [1, 0]), ("target_bus", "rectifier_ac_bus")],
)
def test_fault_event_rejects_invalid_timing_mask_or_target(field: str, value: object):
    event = _complete_event()
    event[field] = value
    with pytest.raises(BackendError):
        validate_fixed_lcc_fault_event(event)


def test_current_fixed_blueprint_reports_explicit_missing_fault_bindings():
    result = inspect_fixed_lcc_fault_capability(
        _asset("blueprint.json"), _asset("catalog-pscad-4.6.2.json"), {}
    )
    assert result["status"] == "INCOMPLETE_ANALYSIS"
    assert result["reasons"] == [
        "fault_timer_port_missing",
        "fault_shunt_phase_port_missing",
        "fault_state_adapter_port_missing",
    ]


def test_complete_fault_binding_passes_without_side_effects():
    blueprint = _complete_blueprint()
    before = copy.deepcopy(blueprint)
    result = inspect_fixed_lcc_fault_capability(
        blueprint, _asset("catalog-pscad-4.6.2.json"), _complete_inventory()
    )
    assert result["status"] == "PASS"
    assert result["reasons"] == []
    assert blueprint == before


def test_packaged_breaker_group_requires_exact_event_references_and_state_signal():
    blueprint = _asset("blueprint.json")
    assert inspect_fixed_lcc_fault_capability(
        blueprint, _asset("catalog-pscad-4.6.2.json"), _production_inventory()
    )["status"] == "PASS"

    mutations = [
        ("timer_component", "missing_timer", "fault_timer_reference_mismatch"),
        ("shunt_component", "missing_group", "fault_shunt_reference_mismatch"),
        ("channel", "Fault/Wrong", "fault_channel_reference_mismatch"),
    ]
    for field, value, reason in mutations:
        candidate = copy.deepcopy(blueprint)
        candidate["dynamic_events"][0][field] = value
        result = inspect_fixed_lcc_fault_capability(
            candidate, _asset("catalog-pscad-4.6.2.json"), _production_inventory()
        )
        assert reason in result["reasons"]

    disconnected = copy.deepcopy(blueprint)
    disconnected["nets"] = [
        net
        for net in disconnected["nets"]
        if net["logical_id"] != "inverter_fault_active_signal"
    ]
    result = inspect_fixed_lcc_fault_capability(
        disconnected, _asset("catalog-pscad-4.6.2.json"), _production_inventory()
    )
    assert "fault_state_signal_unconnected" in result["reasons"]


def test_packaged_breaker_group_requires_one_resistor_branch_per_breaker():
    blueprint = _asset("blueprint.json")
    branch = next(
        net for net in blueprint["nets"] if net["logical_id"] == "inverter_fault_branch_b"
    )
    branch["endpoints"][1]["component"] = "inverter_fault_resistor_a"
    result = inspect_fixed_lcc_fault_capability(
        blueprint, _asset("catalog-pscad-4.6.2.json"), _production_inventory()
    )
    assert "fault_resistor_branch_unconnected" in result["reasons"]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("control_mode", "wall_clock", "fault_control_mode_invalid"),
        ("control_signal", "bad signal", "fault_control_signal_invalid"),
        ("recovery_window_s", 0.0, "fault_recovery_window_invalid"),
    ],
)
def test_packaged_dynamic_event_rejects_invalid_control_contract(field, value, reason):
    blueprint = _asset("blueprint.json")
    blueprint["dynamic_events"][0][field] = value
    result = inspect_fixed_lcc_fault_capability(
        blueprint, _asset("catalog-pscad-4.6.2.json"), _production_inventory()
    )
    assert result["status"] == "INCOMPLETE_ANALYSIS"
    assert reason in result["reasons"]


def test_packaged_dynamic_event_requires_native_scheduler_capabilities():
    blueprint = _asset("blueprint.json")
    event = blueprint["dynamic_events"][0]
    event["control_mode"] = "native_scheduler"
    result = inspect_fixed_lcc_fault_capability(
        blueprint,
        _asset("catalog-pscad-4.6.2.json"),
        {**_production_inventory(), "timed_control_capabilities": {
            "native_schedule": False,
            "simulation_clock": False,
            "time_basis": "EMTDC",
        }},
    )
    assert result["status"] == "INCOMPLETE_ANALYSIS"
    assert "native_scheduler_unavailable" in result["reasons"]


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (
            lambda blueprint: blueprint["components"]
            .__getitem__(next(i for i, c in enumerate(blueprint["components"]) if c["logical_id"] == "inverter_fault_timer"))
            ["parameters"].__setitem__("FaultTime_s", 0.9),
            "fault_timer_event_mismatch",
        ),
        (
            lambda blueprint: blueprint["nets"].append(copy.deepcopy(next(net for net in blueprint["nets"] if net.get("label") == "LCC_FAULT_ACTIVE"))),
            "fault_control_producer_mismatch",
        ),
    ],
)
def test_packaged_dynamic_event_rejects_inconsistent_timer_or_control_producer(mutator, reason):
    blueprint = _asset("blueprint.json")
    mutator(blueprint)
    result = inspect_fixed_lcc_fault_capability(
        blueprint, _asset("catalog-pscad-4.6.2.json"), _production_inventory()
    )
    assert result["status"] == "INCOMPLETE_ANALYSIS"
    assert reason in result["reasons"]


def test_packaged_dynamic_event_rejects_duplicate_phase_branch():
    blueprint = _asset("blueprint.json")
    branch = copy.deepcopy(next(net for net in blueprint["nets"] if net["logical_id"] == "inverter_fault_branch_a"))
    branch["logical_id"] = "inverter_fault_branch_a_duplicate"
    blueprint["nets"].append(branch)
    result = inspect_fixed_lcc_fault_capability(
        blueprint, _asset("catalog-pscad-4.6.2.json"), _production_inventory()
    )
    assert result["status"] == "INCOMPLETE_ANALYSIS"
    assert "fault_resistor_branch_duplicate" in result["reasons"]


def test_packaged_dynamic_event_rejects_unrelated_second_control_label_net():
    blueprint = _asset("blueprint.json")
    blueprint["nets"].append(
        {
            "logical_id": "unrelated_fault_label",
            "kind": "data",
            "label": "LCC_FAULT_ACTIVE",
            "endpoints": [
                {"component": "fault_active_adapter", "port": "OUT"},
                {"component": "fault_active_output", "port": "INPUT"},
            ],
        }
    )
    result = inspect_fixed_lcc_fault_capability(
        blueprint, _asset("catalog-pscad-4.6.2.json"), _production_inventory()
    )
    assert "fault_control_producer_mismatch" in result["reasons"]


def test_live_inventory_port_records_may_omit_direction_metadata():
    inventory = _complete_inventory()
    for definition in inventory["definitions"]:
        for port in definition["ports"]:
            port.pop("direction", None)
    result = inspect_fixed_lcc_fault_capability(
        _complete_blueprint(), _asset("catalog-pscad-4.6.2.json"), inventory
    )
    assert result["status"] == "PASS"


def test_live_inventory_definitions_may_be_keyed_by_logical_name():
    inventory = _complete_inventory()
    inventory["definitions"] = {
        definition["scoped_name"]: {
            key: value for key, value in definition.items() if key != "scoped_name"
        }
        for definition in inventory["definitions"]
    }
    result = inspect_fixed_lcc_fault_capability(
        _complete_blueprint(), _asset("catalog-pscad-4.6.2.json"), inventory
    )
    assert result["status"] == "PASS"


def test_blueprint_parser_preserves_dynamic_event_declarations():
    blueprint = _complete_blueprint()
    parsed = parse_blueprint(blueprint)
    assert parsed.to_dict()["dynamic_events"] == blueprint["dynamic_events"]


def test_legacy_single_control_component_is_normalized_without_losing_capability():
    blueprint = _complete_blueprint()
    event = blueprint["dynamic_events"][0]
    event["control_component"] = event.pop("control_components")[0]
    parsed = parse_blueprint(blueprint)
    normalized = parsed.to_dict()["dynamic_events"][0]
    assert normalized["control_components"] == ["inverter_fault_shunt"]
    assert "control_component" not in normalized
    result = inspect_fixed_lcc_fault_capability(
        blueprint, _asset("catalog-pscad-4.6.2.json"), _complete_inventory()
    )
    assert result["status"] == "PASS"
