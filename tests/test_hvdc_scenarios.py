import asyncio

from pscad_mcp.hvdc.scenarios import validate_scenario
from pscad_mcp.core.service import ConfirmationRequired
from pscad_mcp.hvdc.service import HvdcDomainService


def test_unsupported_event_is_structured_capability_error():
    scenario = {"name": "trip", "profile": "hvdc_breaker_difforder", "project": "case", "parameter_changes": [], "events": [{"time_s": 1, "target": "insert_fault", "value": 1}]}
    result = validate_scenario(scenario)
    assert result["valid"] is False
    assert result["errors"][0]["code"] == "HVDC_CAPABILITY_UNAVAILABLE"


def test_scenario_requires_confirmation_before_parameter_mutation():
    service = HvdcDomainService()
    scenario = {"name": "trip", "profile": "hvdc_breaker_difforder", "project": "case", "parameter_changes": [{"target": "fault_command", "value": 1}], "events": []}
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
