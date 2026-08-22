import asyncio
import json

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.hvdc.builders.lcc.modes import (
    LccSwitchingToken,
    derive_mode_copies,
    execute_lcc_schedule,
    mode_acceptance_contract,
    preflight_lcc_switching,
    validate_lcc_schedule,
)
from pscad_mcp.hvdc.metrics import calculate_metrics
from pscad_mcp.hvdc.models import HvdcComponentRecord, HvdcProjectEvidence, HvdcSourceRef
from pscad_mcp.hvdc.service import HvdcDomainService


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

MODE_COMMAND_BINDING = [{
    **COMMAND_BINDINGS[0],
    "canonical": "metallic_return",
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
    def __init__(self, *, native=True, clock=True, channels=None, now=0.0, time_basis="EMTDC"):
        self.native = native
        self.clock = clock
        self.now = now
        self.time_basis = time_basis
        self.channels = channels if channels is not None else [
            {"path": "Main/mode_status", "call_id": 1, "units": "state"},
            {"path": "Main/Ireturn", "call_id": 2, "units": "kA"},
        ]
        self.scheduled = []

    async def get_timed_control_capabilities(self, project_name):
        return {
            "native_schedule": self.native,
            "simulation_clock": self.clock,
            "time_basis": self.time_basis,
        }

    async def get_output_channels(self, project_name):
        return list(self.channels)

    async def get_simulation_time(self, project_name):
        return self.now

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


def test_mode_name_is_authorized_when_it_has_an_exact_command_binding():
    schedule = validate_lcc_schedule(
        [_event(target="metallic_return")],
        command_bindings=MODE_COMMAND_BINDING,
    )

    assert schedule[0].target == "metallic_return"


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

    assert isinstance(result, LccSwitchingToken)
    assert result.timing_mode == "native"
    assert result.events[0]["component_id"] == "17"
    assert result.events[0]["parameter_name"] == "Value"
    assert result.output_channels_verified == ("mode_status", "return_current")
    with pytest.raises(TypeError):
        result.events[0]["component_id"] = "99"
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


def test_preflight_requires_exact_emtdc_time_basis():
    backend = StrictBackend(time_basis="wall_clock")

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


def test_preflight_reports_missing_exact_binding_as_switching_unavailable():
    profile = _profile()
    profile["command_bindings"] = []
    backend = StrictBackend()

    with pytest.raises(BackendError) as raised:
        asyncio.run(preflight_lcc_switching(
            backend,
            "case",
            [_event()],
            evidence=_evidence(),
            profile=profile,
            required_output_channels=("mode_status", "return_current"),
        ))

    assert raised.value.code == "LCC_SWITCHING_UNAVAILABLE"
    assert backend.scheduled == []


def test_preflight_rejects_past_emtdc_events_but_allows_equal_time_boundary():
    backend = StrictBackend(now=1.0)

    with pytest.raises(BackendError) as raised:
        asyncio.run(preflight_lcc_switching(
            backend,
            "case",
            [_event(time_s=0.999)],
            evidence=_evidence(),
            profile=_profile(),
            required_output_channels=("mode_status", "return_current"),
        ))
    assert raised.value.code == "LCC_SWITCHING_UNAVAILABLE"
    assert backend.scheduled == []

    result = asyncio.run(preflight_lcc_switching(
        backend,
        "case",
        [_event(time_s=1.0)],
        evidence=_evidence(),
        profile=_profile(),
        required_output_channels=("mode_status", "return_current"),
    ))
    assert result.observed_time_s == 1.0


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

    token = asyncio.run(preflight_lcc_switching(backend, "case", [_event()], **kwargs))

    with pytest.raises(BackendError) as raised:
        asyncio.run(execute_lcc_schedule(backend, "case", token, confirm=False))
    assert raised.value.code == "LCC_CONFIRMATION_REQUIRED"
    assert backend.scheduled == []

    result = asyncio.run(execute_lcc_schedule(backend, "case", token, confirm=True))
    assert result[0]["mode"] == "native"
    assert result[0]["requested_time_s"] == 1.0
    assert backend.scheduled[0]["time_s"] == 1.0


def _sampled_channels(*channels):
    return {"channels": [
        {"path": name, "units": units, "domain": [0.0, 1.0, 2.0, 3.0], "values": values}
        for name, units, values in channels
    ], "recovery_bands": {"dc_voltage": {"absolute": 5.0, "units": "kV"}}}


def test_lcc_mode_metrics_cover_closure_imbalance_recovery_and_mismatch():
    samples = _sampled_channels(
        ("positive_pole_current", "kA", [1.0, 1.1, 1.0, 1.0]),
        ("negative_pole_current", "kA", [1.0, 0.9, 1.0, 1.0]),
        ("earth_return_current", "kA", [0.0, 0.2, 0.0, 0.0]),
        ("mode_command", "state", [0, 1, 1, 1]),
        ("mode_status", "state", [0, 0, 1, 1]),
        ("dc_voltage", "kV", [500.0, 500.0, 450.0, 500.0]),
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
    assert metrics["mode_transition_recovery_time_s"]["value"] == pytest.approx(1.0)
    assert metrics["mode_mismatch"]["value"] == pytest.approx(0.25)


@pytest.mark.parametrize("channels", [
    [("positive_pole_current", "", [1, 1, 1, 1]), ("negative_pole_current", "kA", [1, 1, 1, 1])],
    [("mode_command", "state", [0, 1, 1, 1])],
])
def test_lcc_mode_metrics_are_incomplete_for_missing_units_or_samples(channels):
    result = calculate_metrics(_sampled_channels(*channels), ["pole_current_imbalance", "mode_mismatch"])

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert any(item["status"] in {"missing", "invalid"} for item in result["metrics"])


def test_transition_recovery_detects_falling_edge_and_recovers_to_zero_target():
    samples = _sampled_channels(
        ("mode_command", "state", [1, 0, 0, 0]),
        ("mode_status", "state", [1, 1, 0, 0]),
        ("dc_voltage", "kV", [500.0, 500.0, 450.0, 500.0]),
    )

    result = calculate_metrics(samples, ["mode_transition_recovery_time_s"])

    assert result["verdict"] == "PASS"
    assert result["metrics"][0]["value"] == pytest.approx(1.0)


def test_transition_recovery_is_incomplete_without_approved_voltage_band():
    samples = _sampled_channels(
        ("mode_status", "state", [1, 1, 0, 0]),
        ("dc_voltage", "kV", [500.0, 500.0, 450.0, 500.0]),
    )
    samples.pop("recovery_bands")

    result = calculate_metrics(samples, ["mode_transition_recovery_time_s"])

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"


def _scenario_profile(project_stem="derived"):
    required_channels = [
        ("positive_pole_current", "kA"),
        ("negative_pole_current", "kA"),
        ("metallic_return_current", "kA"),
        ("mode_command", "state"),
        ("mode_status", "state"),
        ("dc_voltage", "kV"),
    ]
    return {
        "profile_version": 2,
        "required_assets": [],
        "mappings": [],
        "topology_constraints": {"family": "lcc"},
        "project_fingerprints": [{
            "project_stem": project_stem,
            "pscad_version": "4.6.2",
            "definitions": ["master:const"],
        }],
        "command_bindings": MODE_COMMAND_BINDING,
        "result_channels": [
            {
                "canonical": name,
                "path": f"Main/{name}",
                "call_id": index,
                "units": units,
            }
            for index, (name, units) in enumerate(required_channels, 1)
        ],
        "metric_roles": {},
        "sequences": [],
    }


class ScenarioLccBackend:
    def __init__(self, profile, *, time_basis="EMTDC", fail_capabilities_after_write=False):
        self.profile = profile
        self.time_basis = time_basis
        self.calls = []
        self.parameters = {17: {"Value": 0}}
        self.settings = {"PlotType": "OUT"}
        self.fail_capabilities_after_write = fail_capabilities_after_write

    async def get_timed_control_capabilities(self, project_name):
        self.calls.append("capabilities")
        changed_after_write = self.fail_capabilities_after_write and "parameter_write" in self.calls
        return {
            "native_schedule": not changed_after_write,
            "simulation_clock": not changed_after_write,
            "time_basis": self.time_basis,
        }

    async def get_simulation_time(self, project_name):
        self.calls.append("simulation_clock")
        return 0.0

    async def get_output_channels(self, project_name):
        self.calls.append("output_channels")
        return [
            {"path": item["path"], "call_id": item["call_id"], "units": item["units"]}
            for item in self.profile["result_channels"]
        ]

    async def get_project_settings(self, project_name):
        self.calls.append("project_settings")
        return dict(self.settings)

    async def get_component_parameters(self, project_name, component_id):
        self.calls.append("parameter_read")
        return dict(self.parameters[component_id])

    async def set_component_parameters(self, project_name, component_id, values):
        self.calls.append("parameter_write")
        self.parameters[component_id].update(values)

    async def schedule_timed_controls(self, project_name, events):
        self.calls.append("native_schedule")
        return [
            {"status": "registered", "observed_time_s": event["time_s"]}
            for event in events
        ]

    async def run_project(self, project_name):
        self.calls.append("run_project")

    async def get_run_status(self, project_name):
        return {"status": "completed", "progress": 100.0}

    async def get_project_output(self, project_name, structured=False):
        return []


def _write_scenario_project(path):
    path.write_text(
        """<project name='derived' version='4.6.2'>
        <definition name='Main'><canvas name='Main'>
        <component id='17' name='return selector' definition='master:const'>
        <parameter name='Value' value='0'/></component>
        </canvas></definition><definition name='master:const'/></project>""",
        encoding="utf-8",
    )


async def _wait_scenario_terminal(service, scenario_id):
    for _ in range(200):
        result = await service.scenario_status(scenario_id)
        if result["status"] in {"completed", "failed", "timed_out"}:
            return result
        await asyncio.sleep(0.001)
    raise AssertionError("scenario did not reach a terminal state")


def test_real_scenario_lcc_switching_preflights_before_each_write_class(monkeypatch, tmp_path):
    source = tmp_path / "source.pscx"
    derived = tmp_path / "derived.pscx"
    _write_scenario_project(source)
    _write_scenario_project(derived)
    profile = _scenario_profile()
    backend = ScenarioLccBackend(profile, fail_capabilities_after_write=True)
    service = HvdcDomainService(backend, path_policy=PathPolicy(workspace_root=str(tmp_path)))
    monkeypatch.setattr("pscad_mcp.hvdc.scenarios.load_profile", lambda *args, **kwargs: profile)
    scenario = {
        "name": "strict-lcc-switch",
        "profile": "strict_lcc_test",
        "project": str(source),
        "derived_project": str(derived),
        "parameter_changes": [{"target": "metallic_return", "value": 0}],
        "events": [{"event_id": "e1", "time_s": 1.0, "target": "metallic_return", "value": 1}],
        "run": {"timeout_s": 1.0},
    }

    async def exercise():
        started = await service.run_scenario(str(source), scenario, confirm=True)
        return await _wait_scenario_terminal(service, started["scenario_id"])

    terminal = asyncio.run(exercise())

    assert terminal["status"] == "completed", terminal["error"]
    parameter_write = backend.calls.index("parameter_write")
    native_schedule = backend.calls.index("native_schedule")
    assert all(backend.calls.index(item) < parameter_write for item in (
        "capabilities", "simulation_clock", "output_channels",
    ))
    assert all(item not in backend.calls[parameter_write + 1:native_schedule] for item in (
        "capabilities", "simulation_clock", "output_channels",
    ))


def test_real_scenario_lcc_switching_fails_before_writes_when_time_basis_is_not_emtdc(monkeypatch, tmp_path):
    source = tmp_path / "source.pscx"
    derived = tmp_path / "derived.pscx"
    _write_scenario_project(source)
    _write_scenario_project(derived)
    profile = _scenario_profile()
    backend = ScenarioLccBackend(profile, time_basis="wall_clock")
    service = HvdcDomainService(backend, path_policy=PathPolicy(workspace_root=str(tmp_path)))
    monkeypatch.setattr("pscad_mcp.hvdc.scenarios.load_profile", lambda *args, **kwargs: profile)
    scenario = {
        "name": "strict-lcc-switch",
        "profile": "strict_lcc_test",
        "project": str(source),
        "derived_project": str(derived),
        "operating_mode": "scheduled_switching",
        "parameter_changes": [],
        "events": [{"event_id": "e1", "time_s": 1.0, "target": "metallic_return", "value": 1}],
    }

    with pytest.raises(BackendError) as raised:
        asyncio.run(service.run_scenario(str(source), scenario, confirm=True))

    assert raised.value.code == "LCC_SWITCHING_UNAVAILABLE"
    assert "parameter_write" not in backend.calls
    assert "native_schedule" not in backend.calls


def test_real_scenario_mode_target_cannot_bypass_strict_lcc_branch_without_family_contract(monkeypatch, tmp_path):
    source = tmp_path / "source.pscx"
    derived = tmp_path / "derived.pscx"
    _write_scenario_project(source)
    _write_scenario_project(derived)
    profile = _scenario_profile()
    profile["topology_constraints"] = {}
    backend = ScenarioLccBackend(profile)
    service = HvdcDomainService(backend, path_policy=PathPolicy(workspace_root=str(tmp_path)))
    monkeypatch.setattr("pscad_mcp.hvdc.scenarios.load_profile", lambda *args, **kwargs: profile)
    scenario = {
        "name": "unqualified-lcc-switch",
        "profile": "strict_lcc_test",
        "project": str(source),
        "derived_project": str(derived),
        "parameter_changes": [],
        "events": [{"event_id": "e1", "time_s": 1.0, "target": "metallic_return", "value": 1}],
    }

    with pytest.raises(BackendError) as raised:
        asyncio.run(service.run_scenario(str(source), scenario, confirm=True))

    assert raised.value.code == "LCC_SWITCHING_UNAVAILABLE"
    assert "parameter_write" not in backend.calls
    assert "native_schedule" not in backend.calls


def test_real_scenario_mixed_lcc_and_aux_wallclock_schedule_is_rejected_before_writes(monkeypatch, tmp_path):
    source = tmp_path / "source.pscx"
    derived = tmp_path / "derived.pscx"
    _write_scenario_project(source)
    _write_scenario_project(derived)
    profile = _scenario_profile()
    backend = ScenarioLccBackend(profile)
    service = HvdcDomainService(backend, path_policy=PathPolicy(workspace_root=str(tmp_path)))
    monkeypatch.setattr("pscad_mcp.hvdc.scenarios.load_profile", lambda *args, **kwargs: profile)
    scenario = {
        "name": "mixed-lcc-switch",
        "profile": "strict_lcc_test",
        "project": str(source),
        "derived_project": str(derived),
        "parameter_changes": [],
        "events": [
            {"event_id": "e1", "time_s": 1.0, "target": "metallic_return", "value": 1},
            {
                "event_id": "aux",
                "time_s": 2.0,
                "target": "auxiliary_command",
                "value": 1,
                "wall_clock_s": 1_775_000_000.0,
            },
        ],
    }

    with pytest.raises(BackendError) as raised:
        asyncio.run(service.run_scenario(str(source), scenario, confirm=True))

    assert raised.value.code == "LCC_SWITCHING_UNAVAILABLE"
    assert raised.value.details["reason"] == "mixed_schedule_not_supported"
    assert "parameter_write" not in backend.calls
    assert "native_schedule" not in backend.calls
