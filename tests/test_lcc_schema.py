import copy
import json
from dataclasses import FrozenInstanceError

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.models import (
    LccAcceptanceCheck,
    LccBuildPlan,
    LccBuildRecord,
    LccBuildState,
    LccPlanOperation,
)
from pscad_mcp.hvdc.builders.lcc.schema import parse_blueprint


VALID_BLUEPRINT = {
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
        },
        {
            "logical_id": "converter",
            "definition": "cigre_lcc_v1:12pulse_bridge",
            "location": {"x": 100, "y": 0},
            "orientation": 0,
            "parameters": {},
            "ports": ["ac"],
        },
    ],
    "nets": [
        {
            "logical_id": "rectifier_ac",
            "kind": "electrical",
            "endpoints": [
                {"component": "rectifier_source", "port": "ac"},
                {"component": "converter", "port": "ac"},
            ],
            "route": {"vertices": [[10, 0], [90, 0]]},
        }
    ],
    "outputs": [
        {
            "logical_id": "rectifier_dc_voltage",
            "path": "Main.rectifier_dc_voltage",
            "units": "kV",
            "role": "dc_voltage",
        }
    ],
}


def _assert_invalid(blueprint):
    with pytest.raises(BackendError) as raised:
        parse_blueprint(blueprint)
    assert raised.value.code == "LCC_BLUEPRINT_INVALID"


def test_parse_valid_blueprint_is_immutable_and_json_safe():
    blueprint = parse_blueprint(VALID_BLUEPRINT)

    assert blueprint.name == "cigre_lcc_monopole_v1"
    assert blueprint.topology == "lcc"
    assert blueprint.poles == 1
    assert blueprint.terminals == 2
    assert blueprint.components[0].logical_id == "rectifier_source"
    assert json.loads(json.dumps(blueprint.to_dict()))["schema_version"] == 1

    with pytest.raises(FrozenInstanceError):
        blueprint.name = "changed"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update({"unexpected": True}),
        lambda value: value["components"].append(
            {
                "logical_id": "rectifier_source",
                "definition": "master:duplicate",
                "location": {"x": 200, "y": 0},
                "orientation": 0,
                "parameters": {},
                "ports": ["ac"],
            }
        ),
        lambda value: value["nets"][0]["endpoints"].__setitem__(
            0, {"component": "missing_component", "port": "ac"}
        ),
        lambda value: value["components"][0]["location"].__setitem__("x", 1.5),
        lambda value: value["components"][0].__setitem__("orientation", 8),
        lambda value: value["nets"][0]["route"].__setitem__(
            "vertices", [[0, 0], [1, 1]]
        ),
        lambda value: value.__setitem__("poles", 0),
    ],
    ids=[
        "unknown top-level field",
        "duplicate logical id",
        "missing endpoint",
        "non-integer coordinates",
        "orientation outside range",
        "diagonal route segment",
        "non-positive pole count",
    ],
)
def test_rejects_invalid_blueprint(mutator):
    candidate = copy.deepcopy(VALID_BLUEPRINT)
    mutator(candidate)
    _assert_invalid(candidate)


def test_schema_accepts_future_positive_pole_count():
    candidate = copy.deepcopy(VALID_BLUEPRINT)
    candidate["poles"] = 2

    assert parse_blueprint(candidate).poles == 2


@pytest.mark.parametrize(
    "path",
    [
        ("schema_version",),
        ("poles",),
        ("terminals",),
        ("components", 0, "location", "x"),
        ("components", 0, "orientation"),
        ("settings", "time_step_s"),
    ],
)
def test_rejects_booleans_where_numbers_are_required(path):
    candidate = copy.deepcopy(VALID_BLUEPRINT)
    target = candidate
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = True

    _assert_invalid(candidate)


def test_rejects_unknown_nested_fields():
    candidate = copy.deepcopy(VALID_BLUEPRINT)
    candidate["components"][0]["unexpected"] = "nope"

    _assert_invalid(candidate)


def test_record_serialization_normalizes_build_state_and_nested_records():
    operation = LccPlanOperation(
        sequence=1,
        kind="place_component",
        target="rectifier_source",
        arguments={"location": [0, 0]},
    )
    check = LccAcceptanceCheck(
        name="steady_state",
        kind="physical",
        required=True,
        expected={"status": "pass"},
    )
    plan = LccBuildPlan(
        blueprint=parse_blueprint(VALID_BLUEPRINT),
        operations=(operation,),
        plan_hash="abc123",
        acceptance_checks=(check,),
    )
    record = LccBuildRecord(
        build_id="build-1",
        state=LccBuildState.VALIDATED,
        plan=plan,
    )

    payload = record.to_dict()

    assert payload["state"] == "validated"
    assert payload["plan"]["operations"][0]["kind"] == "place_component"
    assert json.loads(json.dumps(payload))["build_id"] == "build-1"


@pytest.mark.parametrize("value", [{1: "not-json"}, {"value": float("nan")}, {"value": object()}])
def test_record_serialization_rejects_non_json_values(value):
    with pytest.raises(TypeError):
        record = LccBuildRecord(build_id="build-1", state=LccBuildState.VALIDATED, result=value)
        record.to_dict()


def test_rejects_non_string_object_keys_with_backend_error():
    candidate = copy.deepcopy(VALID_BLUEPRINT)
    candidate[1] = "invalid-key"

    with pytest.raises(BackendError) as raised:
        parse_blueprint(candidate)

    assert raised.value.code == "LCC_BLUEPRINT_INVALID"


def test_nested_record_values_are_immutable():
    blueprint = parse_blueprint(VALID_BLUEPRINT)

    with pytest.raises(TypeError):
        blueprint.settings["time_step_s"] = 1.0
    with pytest.raises(TypeError):
        blueprint.components[0].parameters["amplitude_kv"] = 1.0


def test_preserves_structured_port_contracts():
    candidate = copy.deepcopy(VALID_BLUEPRINT)
    candidate["components"][0]["ports"] = [{"name": "ac", "kind": "electrical", "dimension": 3}]

    blueprint = parse_blueprint(candidate)

    assert blueprint.components[0].ports == ("ac",)
    assert blueprint.components[0].port_contracts[0]["kind"] == "electrical"
    assert blueprint.components[0].port_contracts[0]["dimension"] == 3


def test_rejects_overflowing_numeric_settings_with_backend_error():
    candidate = copy.deepcopy(VALID_BLUEPRINT)
    candidate["settings"]["time_step_s"] = 10**1000

    _assert_invalid(candidate)


def test_rejects_malformed_optional_named_records():
    candidate = copy.deepcopy(VALID_BLUEPRINT)
    candidate["canvases"] = [{}]

    _assert_invalid(candidate)


def test_rejects_conflicting_profile_fields():
    candidate = copy.deepcopy(VALID_BLUEPRINT)
    candidate["profile"] = "one"
    candidate["benchmark_profile"] = "two"

    _assert_invalid(candidate)
