import asyncio
import json

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.hvdc.service import HvdcDomainService


XML = """<project name='case' version='4.6.2'>
  <definition name='Main'><canvas name='Main'>
    <component id='17' name='Trip command' definition='master:const'>
      <parameter name='Value' value='0'/>
    </component>
  </canvas></definition>
  <definition name='loadbreaker_3'/>
</project>"""


class StrictBackend:
    def __init__(self, *, mode="polling", forced_readback=None):
        self.mode = mode
        self.parameters = {17: {"Value": 0}}
        self.forced_readback = forced_readback
        self.settings = {"PlotType": "OUT"}
        self.times = iter([0.0, 0.5, 1.02])
        self.calls = []
        self.status = "idle"

    async def list_projects(self):
        return []

    async def get_project_settings(self, project_name):
        return dict(self.settings)

    async def set_project_settings(self, project_name, settings):
        self.settings.update(settings)

    async def get_timed_control_capabilities(self, project_name):
        return {
            "native_schedule": self.mode == "native",
            "simulation_clock": self.mode == "polling",
        }

    async def schedule_timed_controls(self, project_name, events):
        self.calls.append(("schedule", [dict(event) for event in events]))
        return [{"status": "registered", "index": index} for index, _ in enumerate(events)]

    async def get_simulation_time(self, project_name):
        return next(self.times)

    async def get_component_parameters(self, project_name, component_id):
        if self.forced_readback is not None:
            return dict(self.forced_readback)
        return dict(self.parameters[component_id])

    async def set_component_parameters(self, project_name, component_id, values):
        self.calls.append(("set", component_id, dict(values)))
        self.parameters[component_id].update(values)
        if self.mode == "polling":
            self.status = "completed"

    async def run_project(self, project_name):
        self.calls.append(("run", project_name))
        self.status = "running"

    async def get_run_status(self, project_name):
        return {"status": self.status, "progress": 100.0 if self.status == "completed" else None}

    async def discover_output_files(self, project_name, started_after):
        return []


def _service(tmp_path, backend):
    source = tmp_path / "source.pscx"
    derived = tmp_path / "derived.pscx"
    source.write_text(XML, encoding="utf-8")
    derived.write_text(XML, encoding="utf-8")
    profile_dir = tmp_path / ".pscad-mcp" / "hvdc-profiles"
    profile_dir.mkdir(parents=True)
    (profile_dir / "strict_breaker.json").write_text(json.dumps({
        "profile_version": 2,
        "required_assets": [],
        "mappings": [],
        "project_fingerprints": [{"definitions": ["loadbreaker_3"]}],
        "command_bindings": [{
            "canonical": "breaker_command",
            "component": {"canvas": "Main", "definition": "master:const", "component_id": "17"},
            "parameter_name": "Value",
            "allowed_values": [0, 1],
            "semantics": "active_high",
            "read_back": True,
        }],
        "result_channels": [],
        "metric_roles": {},
        "sequences": [],
    }), encoding="utf-8")
    service = HvdcDomainService(backend, path_policy=PathPolicy(workspace_root=str(tmp_path)))
    return service, source, derived


def _scenario(derived, *, events=True):
    return {
        "name": "strict-trip",
        "profile": "strict_breaker",
        "project": "source",
        "derived_project": str(derived),
        "parameter_changes": [],
        "events": [{"time_s": 1.0, "target": "breaker_command", "value": 1}] if events else [],
        "run": {"timeout_s": 1},
    }


async def _terminal(service, scenario_id):
    for _ in range(500):
        result = await service.scenario_status(scenario_id)
        if result["status"] in {"completed", "failed", "timed_out"}:
            return result
        await asyncio.sleep(0)
    raise AssertionError("scenario did not reach a terminal state")


def test_strict_polling_event_records_simulation_time(tmp_path):
    backend = StrictBackend()
    service, source, derived = _service(tmp_path, backend)

    async def exercise():
        started = await service.run_scenario(str(source), _scenario(derived), confirm=True)
        return await _terminal(service, started["scenario_id"])

    result = asyncio.run(exercise())
    assert result["status"] == "completed"
    event = result["partial_completion"]["applied_events"][0]
    assert event["requested_time_s"] == 1.0
    assert event["observed_time_s"] == pytest.approx(1.02)
    assert event["timing_error_s"] == pytest.approx(0.02)
    assert backend.calls[-1][0] == "set"


def test_strict_timing_rejection_occurs_before_run_or_write(tmp_path):
    backend = StrictBackend(mode="unsupported")
    service, source, derived = _service(tmp_path, backend)
    with pytest.raises(BackendError) as raised:
        asyncio.run(service.run_scenario(str(source), _scenario(derived), confirm=True))
    assert raised.value.code == "HVDC_TIMED_CONTROL_UNAVAILABLE"
    assert backend.calls == []


def test_verified_parameter_mismatch_restores_old_value(tmp_path):
    backend = StrictBackend(forced_readback={"Value": 0})
    service, source, derived = _service(tmp_path, backend)
    scenario = _scenario(derived, events=False)
    scenario["parameter_changes"] = [{"target": "breaker_command", "value": 1}]
    async def exercise():
        started = await service.run_scenario(str(source), scenario, confirm=True)
        return await _terminal(service, started["scenario_id"])

    result = asyncio.run(exercise())
    assert result["status"] == "failed"
    assert result["error"]["code"] == "HVDC_SCENARIO_EXECUTION_FAILED"
    assert result["partial_completion"]["applied_parameter_changes"] == []
