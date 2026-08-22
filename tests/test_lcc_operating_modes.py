import asyncio
import json

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.modes import (
    derive_mode_copies,
    execute_lcc_schedule,
    mode_acceptance_contract,
    preflight_lcc_switching,
    validate_lcc_schedule,
)
from pscad_mcp.hvdc.metrics import calculate_metrics
from pscad_mcp.hvdc.models import HvdcComponentRecord, HvdcProjectEvidence, HvdcSourceRef


MODE_BINDINGS = {
    "bipolar_run": {
        "topology_overrides": {"return_path": "balanced", "active_poles": ["positive", "negative"]},
        "control_overrides": [{
            "canonical": "return_selector_command",
            "component_id": "17",
            "parameter_name": "Value",
            "value": 0,
        }],
    },
    "metallic_return": {
        "topology_overrides": {"return_path": "metallic", "active_poles": ["positive"]},
        "control_overrides": [{
            "canonical": "return_selector_command",
            "component_id": "17",
            "parameter_name": "Value",
            "value": 1,
        }],
    },
}

COMMAND_BINDINGS = [{
    "canonical": "return_selector_command",
    "component": {
        "canvas": "Main",
        "definition": "master:const",
        "component_id": "17",
    },
    "parameter_name": "Value",
    "allowed_values": [0, 1],
    "semantics": "active_high",
    "read_back": True,
}]


def _base_plan():
    return {
        "plan_hash": "x",
        "topology": {"return_path": "earth", "active_poles": ["positive", "negative"]},
        "control_commands": [],
        "mode_bindings": MODE_BINDINGS,
    }


def _event(**overrides):
    event = {
        "event_id": "e1",
        "time_s": 1.0,
        "target": "return_selector_command",
        "value": 1,
    }
    event.update(overrides)
    return event


def _evidence():
    source = HvdcSourceRef(
        project_path="case.pscx",
        canvas_name="Main",
        component_id="17",
        definition="master:const",
    )
    return HvdcProjectEvidence(
        project_path="case.pscx",
        project_name="case",
        pscad_version="4.6.2",
        definitions=("master:const",),
        components=(HvdcComponentRecord(
            component_id="17",
            name="return selector",
            definition="master:const",
            parameters={"Value": 0},
            source=source,
        ),),
    )


def _profile():
    return {
        "profile_version": 2,
        "project_fingerprints": [{
            "project_stem": "case",
            "pscad_version": "4.6.2",
            "definitions": ["master:const"],
        }],
        "command_bindings": COMMAND_BINDINGS,
        "result_channels": [
            {"canonical": "mode_status", "path": "Main/mode_status", "call_id": 1, "units": "state"},
            {"canonical": "return_current", "path": "Main/Ireturn", "call_id": 2, "units": "kA"},
        ],
    }


class StrictBackend:
    def __init__(self, *, native=True, clock=True, channels=None):
        self.native = native
        self.clock = clock
        self.channels = channels if channels is not None else [
            {"path": "Main/mode_status", "call_id": 1, "units": "state"},
            {"path": "Main/Ireturn", "call_id": 2, "units": "kA"},
        ]
        self.scheduled = []

    async def get_timed_control_capabilities(self, project_name):
        return {"native_schedule": self.native, "simulation_clock": self.clock}

    async def get_output_channels(self, project_name):
        return list(self.channels)

    async def get_simulation_time(self, project_name):
        return 0.0

    async def schedule_timed_controls(self, project_name, events):
        self.scheduled.extend(dict(event) for event in events)
        return [{"status": "registered", "observed_time_s": event["time_s"]} for event in events]


def test_mode_copies_apply_explicit_overrides_and_are_deeply_isolated():
    base = _base_plan()

    copies = derive_mode_copies(base, ("bipolar_run", "metallic_return"))

    assert [item.mode for item in copies] == ["bipolar_run", "metallic_return"]
    assert copies[0].plan["topology"]["return_path"] == "balanced"
    assert copies[1].plan["topology"]["return_path"] == "metallic"
    assert copies[1].plan["control_commands"][0]["value"] == 1
    assert base["topology"]["return_path"] == "earth"
    with pytest.raises(TypeError):
        copies[0].plan["topology"]["return_path"] = "mutated"
    with pytest.raises(TypeError):
        copies[0].plan["control_commands"][0]["value"] = 99
    assert copies[1].plan["control_commands"][0]["value"] == 1


def test_mode_copy_fails_closed_without_exact_mode_override_contract():
    base = _base_plan()
    base["mode_bindings"] = {}

    with pytest.raises(BackendError) as raised:
        derive_mode_copies(base, ("metallic_return",))

    assert raised.value.code == "LCC_OPERATING_MODE_INVALID"


def test_mode_acceptance_contract_declares_exact_channels_and_metrics():
    contract = mode_acceptance_contract("metallic_return")

    assert "metallic_return_current" in contract["required_output_channels"]
    assert contract["required_metrics"] == [
        "return_current_closure_error",
        "pole_current_imbalance",
        "mode_transition_recovery_time_s",
        "mode_mismatch",
    ]


def test_schedule_requires_exact_writable_command_binding():
    schedule = validate_lcc_schedule([_event()], command_bindings=COMMAND_BINDINGS)
    assert schedule[0].event_id == "e1"

    with pytest.raises(BackendError) as raised:
        validate_lcc_schedule([_event()], command_bindings=[])
    assert raised.value.code == "LCC_OPERATING_MODE_INVALID"


def test_schedule_errors_are_bounded_and_json_safe():
    with pytest.raises(BackendError) as raised:
        validate_lcc_schedule([_event(target="x" * 2_000)], command_bindings=COMMAND_BINDINGS)

    json.dumps(raised.value.to_dict())
    assert len(raised.value.details["target"]) <= 256


@pytest.mark.parametrize("events", [
    [_event(), _event(time_s=2.0)],
    [_event(time_s=2.0), _event(event_id="e2", time_s=1.0)],
    [_event(target="unknown_command")],
    [_event(target="metallic_return")],
    [{**_event(), "timestamp": "2026-08-22T10:00:00Z"}],
    [{**_event(), "wall_clock_s": 1_775_000_000.0}],
])
def test_schedule_rejects_duplicate_nonmonotonic_unknown_mode_and_wall_clock(events):
    with pytest.raises(BackendError) as raised:
        validate_lcc_schedule(events, command_bindings=COMMAND_BINDINGS)
    assert raised.value.code == "LCC_OPERATING_MODE_INVALID"


def test_preflight_resolves_exact_bindings_timing_and_output_before_execute():
    backend = StrictBackend()

    result = asyncio.run(preflight_lcc_switching(
        backend,
        "case",
        [_event()],
        evidence=_evidence(),
        profile=_profile(),
        required_output_channels=("mode_status", "return_current"),
    ))

    assert result["timing_mode"] == "native"
    assert result["events"][0]["component_id"] == "17"
    assert result["events"][0]["parameter_name"] == "Value"
    assert result["output_channels_verified"] == ("mode_status", "return_current")
    assert backend.scheduled == []


@pytest.mark.parametrize("native,clock,channels", [
    (False, False, None),  # current PSCAD 4.6.2 legacy boundary
    (True, False, None),
    (False, True, None),
    (True, True, []),
])
def test_preflight_fails_closed_when_strict_switching_evidence_is_incomplete(native, clock, channels):
    backend = StrictBackend(native=native, clock=clock, channels=channels)

    with pytest.raises(BackendError) as raised:
        asyncio.run(preflight_lcc_switching(
            backend,
            "case",
            [_event()],
            evidence=_evidence(),
            profile=_profile(),
            required_output_channels=("mode_status", "return_current"),
        ))

    assert raised.value.code == "LCC_SWITCHING_UNAVAILABLE"
    assert backend.scheduled == []


@pytest.mark.parametrize("missing_provider", ["schedule_timed_controls", "get_simulation_time"])
def test_preflight_rejects_capabilities_that_have_no_callable_provider(missing_provider):
    backend = StrictBackend()
    setattr(backend, missing_provider, None)

    with pytest.raises(BackendError) as raised:
        asyncio.run(preflight_lcc_switching(
            backend,
            "case",
            [_event()],
            evidence=_evidence(),
            profile=_profile(),
            required_output_channels=("mode_status", "return_current"),
        ))

    assert raised.value.code == "LCC_SWITCHING_UNAVAILABLE"
    assert backend.scheduled == []


def test_execute_requires_confirmation_and_only_registers_native_emtdc_schedule_after_preflight():
    backend = StrictBackend()
    kwargs = {
        "evidence": _evidence(),
        "profile": _profile(),
        "required_output_channels": ("mode_status", "return_current"),
    }

    with pytest.raises(BackendError) as raised:
        asyncio.run(execute_lcc_schedule(backend, "case", [_event()], confirm=False, **kwargs))
    assert raised.value.code == "LCC_CONFIRMATION_REQUIRED"
    assert backend.scheduled == []

    result = asyncio.run(execute_lcc_schedule(backend, "case", [_event()], confirm=True, **kwargs))
    assert result[0]["mode"] == "native"
    assert result[0]["requested_time_s"] == 1.0
    assert backend.scheduled[0]["time_s"] == 1.0


def _sampled_channels(*channels):
    return {"channels": [
        {"path": name, "units": units, "domain": [0.0, 1.0, 2.0, 3.0], "values": values}
        for name, units, values in channels
    ], "recovery_baselines": {"dc_voltage": 500.0}}


def test_lcc_mode_metrics_cover_closure_imbalance_recovery_and_mismatch():
    samples = _sampled_channels(
        ("positive_pole_current", "kA", [1.0, 1.1, 1.0, 1.0]),
        ("negative_pole_current", "kA", [1.0, 0.9, 1.0, 1.0]),
        ("earth_return_current", "kA", [0.0, 0.2, 0.0, 0.0]),
        ("mode_command", "state", [0, 1, 1, 1]),
        ("mode_status", "state", [0, 0, 1, 1]),
        ("dc_voltage", "kV", [500.0, 450.0, 490.0, 500.0]),
    )

    result = calculate_metrics(samples, [
        "return_current_closure_error",
        "pole_current_imbalance",
        "mode_transition_recovery_time_s",
        "mode_mismatch",
    ])

    assert result["verdict"] == "PASS"
    metrics = {item["name"]: item for item in result["metrics"]}
    assert metrics["return_current_closure_error"]["value"] == pytest.approx(0.0)
    assert metrics["pole_current_imbalance"]["value"] == pytest.approx(0.2)
    assert metrics["mode_transition_recovery_time_s"]["value"] == pytest.approx(2.0)
    assert metrics["mode_mismatch"]["value"] == pytest.approx(0.25)


@pytest.mark.parametrize("channels", [
    [("positive_pole_current", "", [1, 1, 1, 1]), ("negative_pole_current", "kA", [1, 1, 1, 1])],
    [("mode_command", "state", [0, 1, 1, 1])],
])
def test_lcc_mode_metrics_are_incomplete_for_missing_units_or_samples(channels):
    result = calculate_metrics(_sampled_channels(*channels), ["pole_current_imbalance", "mode_mismatch"])

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert any(item["status"] in {"missing", "invalid"} for item in result["metrics"])
