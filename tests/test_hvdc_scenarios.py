import asyncio
import pytest

from pscad_mcp.hvdc.scenarios import validate_scenario
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import ConfirmationRequired
from pscad_mcp.hvdc.service import HvdcDomainService


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


def test_bound_event_is_applied_after_run_starts():
    class Backend:
        def __init__(self):
            self.calls = []
        async def run_project(self, project_name):
            self.calls.append(("run", project_name))
        async def set_component_parameters(self, project_name, component_id, values):
            self.calls.append(("set", project_name, component_id, values))
    backend = Backend()
    service = HvdcDomainService(backend)
    scenario = {"name": "trip", "profile": "hvdc_breaker_difforder", "project": "case", "derived_project": "case_derived", "parameter_changes": [], "events": [{"time_s": 0.0, "target": "breaker_command", "component_id": 2, "parameter_name": "Command", "value": 1}]}
    result = asyncio.run(service.run_scenario("case", scenario, confirm=True))
    assert result["status"] == "running"
    assert backend.calls == [("run", "case_derived"), ("set", "case_derived", 2, {"Command": 1})]


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
