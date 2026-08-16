import asyncio
import time
import pytest

from pscad_mcp.hvdc.scenarios import validate_scenario
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import ConfirmationRequired
from pscad_mcp.hvdc.service import HvdcDomainService


def _write_command_project(path):
    path.write_text(
        "<project><canvas name='Main'><component id='2' name='control' definition='control'>"
        "<parameter name='Name' value='current order'/></component></canvas></project>",
        encoding="utf-8",
    )


class ScenarioBackend:
    def __init__(self, projects=("case_derived",)):
        self.calls = []
        self.projects = list(projects)

    async def list_projects(self):
        return [{"name": name} for name in self.projects]

    async def run_project(self, project_name):
        self.calls.append(("run", project_name))

    async def set_component_parameters(self, project_name, component_id, values):
        self.calls.append(("set", project_name, component_id, values))

    async def get_run_status(self, project_name):
        return {"status": "completed", "progress": 100.0}


async def _wait_for_terminal(service, scenario_id, timeout=0.5):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        result = await service.scenario_status(scenario_id)
        if result["status"] in {"completed", "failed", "timed_out"}:
            return result
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"scenario stayed {result['status']!r}")
        await asyncio.sleep(0.001)


def test_unsupported_event_is_structured_capability_error():
    scenario = {"name": "trip", "profile": "hvdc_breaker_difforder", "project": "case", "parameter_changes": [], "events": [{"time_s": 1, "target": "insert_fault", "value": 1}]}
    result = validate_scenario(scenario)
    assert result["valid"] is False
    assert result["errors"][0]["code"] == "HVDC_CAPABILITY_UNAVAILABLE"


def test_scenario_requires_confirmation_before_parameter_mutation():
    service = HvdcDomainService()
    scenario = {"name": "trip", "profile": "hvdc_breaker_difforder", "project": "case", "parameter_changes": [{"target": "fault_command", "component_id": 1, "parameter_name": "Fault", "value": 1}], "events": []}
    try:
        asyncio.run(service.run_scenario("case", scenario, confirm=False))
    except ConfirmationRequired as error:
        assert error.code == "CONFIRMATION_REQUIRED"
    else:
        raise AssertionError("confirmation was not required")


def test_even_baseline_run_requires_confirmation():
    service = HvdcDomainService()
    scenario = {"name": "baseline", "profile": "lcc_bipolar_generic", "project": "case", "parameter_changes": [], "events": []}
    try:
        asyncio.run(service.run_scenario("case", scenario, confirm=False))
    except ConfirmationRequired as error:
        assert error.code == "CONFIRMATION_REQUIRED"
    else:
        raise AssertionError("confirmation was not required")


def test_scenario_record_preserves_analysis_recovery_baselines():
    service = HvdcDomainService(ScenarioBackend())
    scenario = {
        "name": "baseline",
        "profile": "lcc_bipolar_generic",
        "project": "case_derived",
        "parameter_changes": [],
        "events": [],
        "analysis": {
            "metrics": ["dc_current_recovery_time_s"],
            "recovery_baselines": {"dc_current": 1.0},
        },
    }

    async def exercise():
        started = await service.run_scenario("case_derived", scenario, confirm=True)
        await _wait_for_terminal(service, started["scenario_id"])
        return started

    started = asyncio.run(exercise())

    assert started["analysis"] == scenario["analysis"]
    assert started["recovery_baselines"] == {"dc_current": 1.0}


@pytest.mark.parametrize(
    "analysis",
    [
        "not-an-object",
        {"recovery_baselines": []},
        {"recovery_baselines": {"dc_current": "unknown"}},
        {"recovery_baselines": {"dc_current": float("nan")}},
    ],
)
def test_scenario_analysis_recovery_baselines_are_validated(analysis):
    scenario = {
        "name": "baseline",
        "profile": "lcc_bipolar_generic",
        "project": "case",
        "parameter_changes": [],
        "events": [],
        "analysis": analysis,
    }

    result = validate_scenario(scenario)

    assert result["valid"] is False
    assert result["errors"][0]["field"].startswith("analysis")


@pytest.mark.parametrize(
    "metrics",
    [
        "dc_voltage_peak",
        [],
        [""],
        [1],
    ],
)
def test_scenario_analysis_metrics_must_be_nonempty_string_list(metrics):
    result = validate_scenario(
        {
            "name": "baseline",
            "profile": "lcc_bipolar_generic",
            "project": "case",
            "parameter_changes": [],
            "events": [],
            "analysis": {"metrics": metrics},
        }
    )

    assert result["valid"] is False
    assert result["errors"][0]["field"] == "analysis.metrics"


def test_unbound_event_cannot_execute_as_baseline():
    scenario = {"name": "trip", "profile": "hvdc_breaker_difforder", "project": "case", "parameter_changes": [], "events": [{"time_s": 1.0, "target": "breaker_command", "value": 1}]}
    service = HvdcDomainService()
    from pscad_mcp.core.backend.base import BackendError
    try:
        asyncio.run(service.run_scenario("case", scenario, confirm=True))
    except BackendError as error:
        assert error.code == "HVDC_CAPABILITY_UNAVAILABLE"
    else:
        raise AssertionError("unbound event was accepted")


def test_source_file_mutation_requires_explicit_derived_project(tmp_path):
    source = tmp_path / "source.pscx"
    source.write_text("<project />", encoding="utf-8")
    service = HvdcDomainService()
    scenario = {"name": "change", "profile": "lcc_bipolar_generic", "project": str(source), "parameter_changes": [{"target": "x", "component_id": 1, "parameter_name": "P", "value": 2}], "events": []}
    from pscad_mcp.core.backend.base import BackendError
    try:
        asyncio.run(service.run_scenario(str(source), scenario, confirm=True))
    except BackendError as error:
        assert error.code == "HVDC_CAPABILITY_UNAVAILABLE"
    else:
        raise AssertionError("source mutation was not blocked")


def test_auto_bound_command_is_applied_from_the_selected_profile(tmp_path):
    source = tmp_path / "case.pscx"
    _write_command_project(source)
    backend = ScenarioBackend()
    service = HvdcDomainService(backend, path_policy=PathPolicy(workspace_root=str(tmp_path)))
    scenario = {
        "name": "change",
        "profile": "lcc_bipolar_generic",
        "project": str(source),
        "derived_project": "case_derived",
        "parameter_changes": [{"target": "current_order", "value": 2}],
        "events": [],
    }

    async def exercise():
        started = await service.run_scenario(str(source), scenario, confirm=True)
        terminal = await _wait_for_terminal(service, started["scenario_id"])
        return started, terminal

    started, terminal = asyncio.run(exercise())
    assert started["status"] == "validated"
    assert terminal["status"] == "completed"
    assert terminal["changed_parameters"][0]["component_id"] == "2"
    assert terminal["changed_parameters"][0]["parameter_name"] == "Name"
    assert backend.calls == [("set", "case_derived", 2, {"Name": 2}), ("run", "case_derived")]


def test_explicit_binding_must_exactly_match_observed_mapping_source(tmp_path):
    source = tmp_path / "case.pscx"
    _write_command_project(source)
    backend = ScenarioBackend()
    service = HvdcDomainService(backend, path_policy=PathPolicy(workspace_root=str(tmp_path)))
    scenario = {
        "name": "change",
        "profile": "lcc_bipolar_generic",
        "project": str(source),
        "derived_project": "case_derived",
        "parameter_changes": [
            {"target": "current_order", "component_id": 99, "parameter_name": "Arbitrary", "value": 2}
        ],
        "events": [],
    }
    with pytest.raises(BackendError) as raised:
        asyncio.run(service.run_scenario(str(source), scenario, confirm=True))
    assert raised.value.code == "HVDC_MAPPING_MISSING"
    assert raised.value.details["approved_source"] == {"component_id": "2", "parameter_name": "Name"}
    assert backend.calls == []


def test_measurement_mapping_cannot_be_used_as_a_mutation_target(tmp_path):
    source = tmp_path / "case.pscx"
    source.write_text(
        "<project><canvas name='Main'><component id='4' name='meter' definition='meter'>"
        "<parameter name='Idc' value='3 kA'/></component></canvas></project>",
        encoding="utf-8",
    )
    service = HvdcDomainService(ScenarioBackend(), path_policy=PathPolicy(workspace_root=str(tmp_path)))
    scenario = {
        "name": "bad",
        "profile": "lcc_bipolar_generic",
        "project": str(source),
        "derived_project": "case_derived",
        "parameter_changes": [{"target": "dc_current", "value": 4}],
        "events": [],
    }
    with pytest.raises(BackendError) as raised:
        asyncio.run(service.run_scenario(str(source), scenario, confirm=True))
    assert raised.value.code == "HVDC_CAPABILITY_UNAVAILABLE"
    assert raised.value.details["direction"] == "measurement"


def test_mutating_target_must_be_distinct_after_case_insensitive_path_normalization(tmp_path):
    source = tmp_path / "Case.pscx"
    _write_command_project(source)
    service = HvdcDomainService(ScenarioBackend(), path_policy=PathPolicy(workspace_root=str(tmp_path)))
    scenario = {
        "name": "same-target",
        "profile": "lcc_bipolar_generic",
        "project": str(source),
        "derived_project": str(source).upper(),
        "parameter_changes": [{"target": "current_order", "value": 2}],
        "events": [],
    }
    with pytest.raises(BackendError) as raised:
        asyncio.run(service.run_scenario(str(source), scenario, confirm=True))
    assert raised.value.code == "HVDC_SCENARIO_INVALID"
    assert raised.value.details["reason"] == "source_and_target_match"


def test_path_target_cannot_bypass_distinctness_from_logical_source_name(tmp_path):
    source = tmp_path / "case.pscx"
    _write_command_project(source)
    service = HvdcDomainService(ScenarioBackend(), path_policy=PathPolicy(workspace_root=str(tmp_path)))
    scenario = {
        "name": "mixed-same-target",
        "profile": "lcc_bipolar_generic",
        "project": "case",
        "derived_project": str(source),
        "parameter_changes": [{"target": "current_order", "value": 2}],
        "events": [],
    }
    with pytest.raises(BackendError) as raised:
        asyncio.run(service.run_scenario("case", scenario, confirm=True))
    assert raised.value.code == "HVDC_SCENARIO_INVALID"
    assert raised.value.details["reason"] == "source_and_target_match"


def test_path_like_target_without_suffix_still_obeys_workspace_policy(tmp_path):
    source = tmp_path / "case.pscx"
    _write_command_project(source)
    outside = tmp_path.parent / f"outside-{time.time_ns()}"
    outside.with_suffix(".pscx").write_text("<project />", encoding="utf-8")
    service = HvdcDomainService(ScenarioBackend(), path_policy=PathPolicy(workspace_root=str(tmp_path)))
    scenario = {
        "name": "escape",
        "profile": "lcc_bipolar_generic",
        "project": str(source),
        "derived_project": str(outside),
        "parameter_changes": [{"target": "current_order", "value": 2}],
        "events": [],
    }
    try:
        with pytest.raises(BackendError) as raised:
            asyncio.run(service.run_scenario(str(source), scenario, confirm=True))
        assert raised.value.code == "INVALID_ARGUMENT"
    finally:
        outside.with_suffix(".pscx").unlink()


def test_path_like_baseline_execution_target_obeys_workspace_policy(tmp_path):
    source = tmp_path / "external.pscx"
    source.write_text("<project />", encoding="utf-8")
    service = HvdcDomainService(ScenarioBackend(projects=()))
    scenario = {
        "name": "baseline",
        "profile": "lcc_bipolar_generic",
        "project": str(source),
        "parameter_changes": [],
        "events": [],
    }
    with pytest.raises(BackendError) as raised:
        asyncio.run(service.run_scenario(str(source), scenario, confirm=True))
    assert raised.value.code == "WORKSPACE_NOT_CONFIGURED"


def test_logical_derived_target_must_already_be_loaded(tmp_path):
    source = tmp_path / "case.pscx"
    _write_command_project(source)
    backend = ScenarioBackend(projects=())
    service = HvdcDomainService(backend, path_policy=PathPolicy(workspace_root=str(tmp_path)))
    scenario = {
        "name": "missing",
        "profile": "lcc_bipolar_generic",
        "project": str(source),
        "derived_project": "missing_derived",
        "parameter_changes": [{"target": "current_order", "value": 2}],
        "events": [],
    }
    with pytest.raises(BackendError) as raised:
        asyncio.run(service.run_scenario(str(source), scenario, confirm=True))
    assert raised.value.code == "NOT_FOUND"
    assert backend.calls == []


def test_workspace_registered_profile_is_available_to_scenario_validation_and_run(tmp_path):
    mapping = tmp_path / "scenario-custom.json"
    mapping.write_text('{"required_assets": [], "mappings": []}', encoding="utf-8")
    service = HvdcDomainService(path_policy=PathPolicy(workspace_root=str(tmp_path)))
    service.register_profile("scenario_custom", str(mapping))
    scenario = {
        "name": "baseline",
        "profile": "scenario_custom",
        "project": "case",
        "parameter_changes": [],
        "events": [],
    }

    validation = asyncio.run(service.validate_scenario(scenario))
    assert validation["valid"] is True
    with pytest.raises(ConfirmationRequired):
        asyncio.run(service.run_scenario("case", scenario, confirm=False))


@pytest.mark.parametrize("timeout_s", [True, 0, -1, float("inf"), 86401])
def test_run_timeout_must_be_finite_positive_and_bounded(timeout_s):
    scenario = {
        "name": "baseline",
        "profile": "lcc_bipolar_generic",
        "project": "case",
        "parameter_changes": [],
        "events": [],
        "run": {"timeout_s": timeout_s},
    }
    result = validate_scenario(scenario)
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "run.timeout_s"


def test_timed_events_run_in_background_without_blocking_the_start_call(tmp_path):
    source = tmp_path / "case.pscx"
    _write_command_project(source)
    class TimedBackend(ScenarioBackend):
        async def get_run_status(self, project_name):
            delivered = any(call[0] == "set" for call in self.calls)
            return {"status": "completed" if delivered else "running", "progress": 100.0 if delivered else None}

    backend = TimedBackend()
    service = HvdcDomainService(backend, path_policy=PathPolicy(workspace_root=str(tmp_path)))
    scenario = {
        "name": "timed",
        "profile": "lcc_bipolar_generic",
        "project": str(source),
        "derived_project": "case_derived",
        "parameter_changes": [],
        "events": [{"time_s": 0.1, "target": "current_order", "value": 3}],
        "run": {"timeout_s": 1},
    }

    async def exercise():
        before = asyncio.get_running_loop().time()
        started = await service.run_scenario(str(source), scenario, confirm=True)
        elapsed = asyncio.get_running_loop().time() - before
        await asyncio.sleep(0.02)
        interim = await service.scenario_status(started["scenario_id"])
        interim_calls = list(backend.calls)
        terminal = await _wait_for_terminal(service, started["scenario_id"])
        return started, elapsed, interim, interim_calls, terminal

    started, elapsed, interim, interim_calls, terminal = asyncio.run(exercise())
    assert elapsed < 0.05
    assert started["status"] == "validated"
    assert interim["status"] == "running"
    assert not any(call[0] == "set" for call in interim_calls)
    assert terminal["status"] == "completed"
    assert backend.calls == [("run", "case_derived"), ("set", "case_derived", 2, {"Name": 3})]


def test_backend_error_is_structured_and_preserves_partial_completion(tmp_path):
    source = tmp_path / "case.pscx"
    _write_command_project(source)

    class FailingBackend(ScenarioBackend):
        async def set_component_parameters(self, project_name, component_id, values):
            raise BackendError("VENDOR_FAILURE", "parameter rejected", "fake", "set_component_parameters", {"vendor_code": 17})

    service = HvdcDomainService(FailingBackend(), path_policy=PathPolicy(workspace_root=str(tmp_path)))
    scenario = {
        "name": "fails",
        "profile": "lcc_bipolar_generic",
        "project": str(source),
        "derived_project": "case_derived",
        "parameter_changes": [{"target": "current_order", "value": 3}],
        "events": [],
        "run": {"timeout_s": 1},
    }

    async def exercise():
        started = await service.run_scenario(str(source), scenario, confirm=True)
        return await _wait_for_terminal(service, started["scenario_id"])

    terminal = asyncio.run(exercise())
    assert terminal["status"] == "failed"
    assert terminal["error"] == {
        "code": "VENDOR_FAILURE",
        "message": "parameter rejected",
        "backend": "fake",
        "operation": "set_component_parameters",
        "details": {"vendor_code": 17},
    }
    assert terminal["partial_completion"] == {
        "applied_parameter_changes": [],
        "applied_events": [],
        "run_started": False,
        "run_command_dispatched": False,
    }


def test_timeout_transitions_and_background_task_reference_is_cleaned(tmp_path):
    source = tmp_path / "case.pscx"
    source.write_text("<project />", encoding="utf-8")

    class HangingBackend(ScenarioBackend):
        async def run_project(self, project_name):
            await asyncio.Event().wait()

    service = HvdcDomainService(HangingBackend(), path_policy=PathPolicy(workspace_root=str(tmp_path)))
    scenario = {
        "name": "timeout",
        "profile": "lcc_bipolar_generic",
        "project": str(source),
        "parameter_changes": [],
        "events": [],
        "run": {"timeout_s": 0.02},
    }

    async def exercise():
        started = await service.run_scenario(str(source), scenario, confirm=True)
        terminal = await _wait_for_terminal(service, started["scenario_id"])
        await asyncio.sleep(0)
        return terminal

    terminal = asyncio.run(exercise())
    assert terminal["status"] == "timed_out"
    assert terminal["error"]["code"] == "HVDC_SCENARIO_TIMEOUT"
    assert service._scenario_tasks == {}


def test_timeout_is_not_defeated_by_output_discovery_during_cancellation(tmp_path):
    source = tmp_path / "case.pscx"
    _write_command_project(source)

    class HangingDiscoveryBackend(ScenarioBackend):
        async def list_output_files(self, project_name):
            await asyncio.Event().wait()

    service = HvdcDomainService(HangingDiscoveryBackend(), path_policy=PathPolicy(workspace_root=str(tmp_path)))
    scenario = {
        "name": "bounded-timeout",
        "profile": "lcc_bipolar_generic",
        "project": str(source),
        "derived_project": "case_derived",
        "parameter_changes": [],
        "events": [{"time_s": 1, "target": "current_order", "value": 3}],
        "run": {"timeout_s": 0.02},
    }

    async def exercise():
        started = await service.run_scenario(str(source), scenario, confirm=True)
        return await _wait_for_terminal(service, started["scenario_id"], timeout=0.2)

    terminal = asyncio.run(exercise())
    assert terminal["status"] == "timed_out"
    assert service._scenario_tasks == {}


def test_status_refreshes_terminal_run_state_and_structured_messages():
    class StatusBackend:
        async def get_run_status(self, project_name):
            return {"status": "completed", "progress": 100.0}

        async def get_project_output(self, project_name, structured=False):
            assert structured is True
            return [{"severity": "warning", "text": "solver note", "source": {"line": 4}}]

    service = HvdcDomainService(StatusBackend())
    service._scenarios["refresh"] = {
        "scenario_id": "refresh",
        "target_project": "derived",
        "status": "running",
        "messages": [],
    }
    result = asyncio.run(service.scenario_status("refresh"))
    assert result["status"] == "completed"
    assert result["project_status"] == {"status": "completed", "progress": 100.0}
    assert result["messages"] == [{"severity": "warning", "text": "solver note", "source": {"line": 4}}]


def test_status_refresh_does_not_finish_scenario_while_event_task_is_active(tmp_path):
    source = tmp_path / "case.pscx"
    _write_command_project(source)

    class ActiveBackend(ScenarioBackend):
        def __init__(self):
            super().__init__()
            self.status_calls = 0

        async def get_run_status(self, project_name):
            self.status_calls += 1
            status = "running" if self.status_calls == 1 else "failed"
            return {"status": status, "progress": 100.0}

    service = HvdcDomainService(ActiveBackend(), path_policy=PathPolicy(workspace_root=str(tmp_path)))
    scenario = {
        "name": "active",
        "profile": "lcc_bipolar_generic",
        "project": str(source),
        "derived_project": "case_derived",
        "parameter_changes": [],
        "events": [{"time_s": 0.05, "target": "current_order", "value": 3}],
        "run": {"timeout_s": 1},
    }

    async def exercise():
        started = await service.run_scenario(str(source), scenario, confirm=True)
        await asyncio.sleep(0.001)
        interim = await service.scenario_status(started["scenario_id"])
        terminal = await _wait_for_terminal(service, started["scenario_id"])
        return interim, terminal

    interim, terminal = asyncio.run(exercise())
    assert interim["status"] == "running"
    assert interim["project_status"]["status"] == "failed"
    assert terminal["status"] == "failed"
    assert terminal["error"]["code"] == "HVDC_SCENARIO_RUN_FAILED"


def test_explicit_output_files_are_policy_validated_and_unresolved_discovery_is_recorded(tmp_path):
    source = tmp_path / "case.pscx"
    source.write_text("<project />", encoding="utf-8")
    output = tmp_path / "case.psout"
    output.write_text("result", encoding="utf-8")
    service = HvdcDomainService(ScenarioBackend(projects=()), path_policy=PathPolicy(workspace_root=str(tmp_path)))
    scenario = {
        "name": "baseline",
        "profile": "lcc_bipolar_generic",
        "project": str(source),
        "parameter_changes": [],
        "events": [],
        "output_files": [str(output)],
    }

    async def exercise():
        started = await service.run_scenario(str(source), scenario, confirm=True)
        return await _wait_for_terminal(service, started["scenario_id"])

    terminal = asyncio.run(exercise())
    assert terminal["output_files"] == [str(output.resolve())]
    assert {warning.get("code") for warning in terminal["warnings"] if isinstance(warning, dict)} == {"OUTPUT_DISCOVERY_UNAVAILABLE"}


def test_backend_output_discovery_is_captured_and_policy_checked(tmp_path):
    source = tmp_path / "case.pscx"
    source.write_text("<project />", encoding="utf-8")
    output = tmp_path / "generated.psout"
    output.write_text("result", encoding="utf-8")

    class OutputBackend(ScenarioBackend):
        async def list_output_files(self, project_name):
            return [str(output)]

    service = HvdcDomainService(OutputBackend(projects=()), path_policy=PathPolicy(workspace_root=str(tmp_path)))
    scenario = {
        "name": "baseline",
        "profile": "lcc_bipolar_generic",
        "project": str(source),
        "parameter_changes": [],
        "events": [],
    }

    async def exercise():
        started = await service.run_scenario(str(source), scenario, confirm=True)
        return await _wait_for_terminal(service, started["scenario_id"])

    terminal = asyncio.run(exercise())
    assert terminal["output_files"] == [str(output.resolve())]
    assert terminal["output_discovery"] == "backend"


def test_failed_run_captures_outputs_produced_before_event_failure(tmp_path):
    source = tmp_path / "case.pscx"
    _write_command_project(source)
    output = tmp_path / "partial.psout"
    output.write_text("partial result", encoding="utf-8")

    class PartialBackend(ScenarioBackend):
        def __init__(self):
            super().__init__()
            self.stopped = False

        async def set_component_parameters(self, project_name, component_id, values):
            raise BackendError("EVENT_FAILED", "event rejected", "fake", "set_component_parameters")

        async def list_output_files(self, project_name):
            return [str(output)]

        async def get_run_status(self, project_name):
            return {"status": "stopped" if self.stopped else "running", "progress": None}

        async def stop_simulation(self, project_name):
            self.stopped = True
            return "stopped"

    service = HvdcDomainService(PartialBackend(), path_policy=PathPolicy(workspace_root=str(tmp_path)))
    scenario = {
        "name": "partial",
        "profile": "lcc_bipolar_generic",
        "project": str(source),
        "derived_project": "case_derived",
        "parameter_changes": [],
        "events": [{"time_s": 0, "target": "current_order", "value": 3}],
    }

    async def exercise():
        started = await service.run_scenario(str(source), scenario, confirm=True)
        return await _wait_for_terminal(service, started["scenario_id"])

    terminal = asyncio.run(exercise())
    assert terminal["status"] == "failed"
    assert terminal["partial_completion"]["run_started"] is True
    assert terminal["output_files"] == [str(output.resolve())]
