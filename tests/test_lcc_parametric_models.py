import copy
import json
from dataclasses import FrozenInstanceError

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.parametric_models import (
    DerivedParameter,
    DerivedParameterReport,
    LccModeEvent,
    LccModeRequest,
    LccParameterOverride,
    LccRatings,
    LccTemplateMapping,
    ParametricLccRequest,
)
from pscad_mcp.hvdc.builders.lcc.schema import parse_blueprint, parse_parametric_request


VALID_REQUEST = {
    "topology": "bipolar",
    "ratings": {
        "rated_power_mw": 1200.0,
        "dc_voltage_kv": 500.0,
        "dc_current_ka": 2.4,
        "ac_voltage_kv": 500.0,
        "frequency_hz": 50.0,
        "scr": 3.0,
    },
    "engineering_overrides": {"smoothing_reactor_mh": 120.0},
    "operation_modes": ["bipolar_run", "monopolar_earth_return"],
    "return_path_assets": ["neutral_bus", "earth_return"],
    "mode_requests": [
        {
            "mode": "bipolar_run",
            "events": [
                {"event_id": "e1", "time_s": 1.0, "target": "metallic_return", "value": 1},
                {"event_id": "e2", "time_s": 2.0, "target": "metallic_return", "value": 0},
            ],
        }
    ],
}


def _assert_request_invalid(candidate, code):
    with pytest.raises(BackendError) as raised:
        parse_parametric_request(candidate)
    assert raised.value.code == code


def test_parametric_records_are_frozen_and_json_safe():
    request = ParametricLccRequest(
        topology="bipolar",
        ratings=LccRatings(
            rated_power_mw=1200.0,
            dc_voltage_kv=500.0,
            dc_current_ka=2.4,
            ac_voltage_kv=500.0,
            frequency_hz=50.0,
            scr=3.0,
        ),
        engineering_overrides={"smoothing_reactor_mh": 120.0},
        operation_modes=("bipolar_run", "monopolar_earth_return"),
        return_path_assets=("neutral_bus", "earth_return"),
    )

    payload = request.to_dict()

    assert payload["topology"] == "bipolar"
    assert payload["ratings"]["dc_current_ka"] == 2.4
    assert payload["return_path_assets"] == ["neutral_bus", "earth_return"]
    assert json.loads(json.dumps(payload))["engineering_overrides"]["smoothing_reactor_mh"] == 120.0

    with pytest.raises(FrozenInstanceError):
        request.topology = "monopolar"
    with pytest.raises(TypeError):
        request.engineering_overrides["smoothing_reactor_mh"] = 100.0


def test_parametric_record_helpers_remain_json_safe():
    override = LccParameterOverride(name="smoothing_reactor_mh", value=120.0)
    report = DerivedParameterReport(
        parameters=(
            DerivedParameter(
                name="dc_power_mw",
                value=1200.0,
                source="derived",
                formula="P = V * I",
            ),
        ),
    )
    mode_event = LccModeEvent(event_id="e1", time_s=1.0, target="metallic_return", value=1)
    mode_request = LccModeRequest(mode="bipolar_run", events=(mode_event,))
    mapping = LccTemplateMapping(role="earth_electrode", definition="cigre_lcc_v1:EarthElectrode")

    assert override.to_dict()["name"] == "smoothing_reactor_mh"
    assert report.to_dict()["parameters"][0]["source"] == "derived"
    assert mode_request.to_dict()["events"][0]["event_id"] == "e1"
    assert mapping.to_dict()["role"] == "earth_electrode"


@pytest.mark.parametrize(
    "mutator, code",
    [
        (lambda value: value["ratings"].update({"unexpected": True}), "LCC_RATING_INVALID"),
        (lambda value: value["ratings"].__setitem__("dc_current_ka", True), "LCC_RATING_INVALID"),
        (lambda value: value["ratings"].__setitem__("dc_current_ka", float("nan")), "LCC_RATING_INVALID"),
        (lambda value: value["ratings"].__setitem__("dc_current_ka", 0.0), "LCC_RATING_INVALID"),
        (lambda value: value.__setitem__("topology", "mesh"), "LCC_OPERATING_MODE_INVALID"),
        (lambda value: value["operation_modes"].__setitem__(0, "not_a_mode"), "LCC_OPERATING_MODE_INVALID"),
        (lambda value: value["mode_requests"][0]["events"].__setitem__(0, {"event_id": "e1", "time_s": -1.0, "target": "metallic_return", "value": 1}), "LCC_OPERATING_MODE_INVALID"),
        (lambda value: value["mode_requests"][0]["events"].__setitem__(
            1, {"event_id": "e2", "time_s": 0.5, "target": "metallic_return", "value": 0}
        ), "LCC_OPERATING_MODE_INVALID"),
    ],
)
def test_parametric_parser_rejects_invalid_input(mutator, code):
    candidate = copy.deepcopy(VALID_REQUEST)
    mutator(candidate)
    _assert_request_invalid(candidate, code)


def test_parametric_parser_preserves_blueprint_behavior():
    candidate = {
        "schema_version": 1,
        "name": "cigre_lcc_monopole_v1",
        "topology": "lcc",
        "poles": 1,
        "terminals": 2,
        "settings": {
            "time_step_s": 5e-5,
            "output_step_s": 5e-5,
            "simulation_duration_s": 1.0,
            "compiler_target": "fortran",
            "output_enabled": True,
        },
        "components": [
            {
                "logical_id": "rectifier_source",
                "definition": "master:ac_source",
                "location": {"x": 0, "y": 0},
                "orientation": 0,
                "parameters": {"amplitude_kv": 230.0},
                "ports": ["ac"],
            }
        ],
        "nets": [],
        "outputs": [],
    }

    assert parse_blueprint(candidate).name == "cigre_lcc_monopole_v1"


def test_parametric_parser_rejects_duplicate_return_asset_evidence():
    candidate = copy.deepcopy(VALID_REQUEST)
    candidate["return_path_assets"] = ["neutral_bus", "neutral_bus"]

    _assert_request_invalid(candidate, "LCC_OPERATING_MODE_INVALID")
