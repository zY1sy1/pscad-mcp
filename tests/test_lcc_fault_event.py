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
    blueprint["dynamic_events"] = [
        {
            **_complete_event(),
            "timer_component": "inverter_fault_timer",
            "shunt_component": "inverter_fault_shunt",
            "channel": "fault_active",
            "control_component": "inverter_fault_shunt",
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
        "fault_timer_missing",
        "fault_shunt_missing",
        "fault_event_missing",
        "fault_channel_missing",
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


def test_blueprint_parser_preserves_dynamic_event_declarations():
    blueprint = _complete_blueprint()
    parsed = parse_blueprint(blueprint)
    assert parsed.to_dict()["dynamic_events"] == blueprint["dynamic_events"]
