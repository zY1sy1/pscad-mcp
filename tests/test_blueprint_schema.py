from __future__ import annotations

import copy
import json

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.builders.blueprint.models import BlueprintBuildState
from pscad_mcp.builders.blueprint.schema import parse_blueprint


def valid_blueprint() -> dict:
    return {
        "identity": {
            "schema_version": 1,
            "name": "breaker-copy-v1",
            "supported_pscad_versions": ["4.6.2", "5.0.2"],
            "inspection_profile": "breaker",
        },
        "source_package": {
            "entry_point": "source.pscx",
            "required": [
                {"path": "source.pscx", "kind": "file"},
                {"path": "support", "kind": "directory"},
            ],
            "handling_policy": "read_only",
        },
        "operations": [
            {
                "sequence": 1,
                "kind": "clone_component",
                "target": "source_breaker",
                "arguments": {
                    "logical_id": "breaker_copy",
                    "location": [20, 30],
                    "expected_definition": "master:breaker",
                    "canvas": "Main",
                },
                "operation_id": "op-001",
            },
            {
                "sequence": 2,
                "kind": "set_component_parameters",
                "target": "breaker_copy",
                "arguments": {
                    "parameters": {"Name": "BRK_COPY"},
                    "units": {},
                },
                "operation_id": "op-002",
            },
        ],
        "acceptance": {
            "required_structure": [{"logical_id": "breaker_copy", "definition": "master:breaker"}],
            "required_parameters": [{"logical_id": "breaker_copy", "name": "Name", "value": "BRK_COPY"}],
            "blocking_messages": ["error", "fatal"],
            "outputs": [{"channel": "Main/BRK_STATE", "units": "state", "required": True}],
            "rules": [
                {
                    "rule_id": "finite-state",
                    "kind": "all_finite",
                    "channel": "Main/BRK_STATE",
                    "required": True,
                    "source_class": "model_observed",
                    "physical": False,
                    "arguments": {},
                }
            ],
        },
        "publication": {
            "delivery_package": True,
            "evidence_files": ["plan.json", "validation-report.json", "manifest.json"],
            "scope": "model_run_through_only",
        },
    }


def assert_schema_error(value: object, code: str = "BLUEPRINT_SCHEMA_INVALID") -> BackendError:
    with pytest.raises(BackendError) as raised:
        parse_blueprint(value)
    assert raised.value.code == code
    return raised.value


def test_parse_blueprint_returns_immutable_json_safe_records():
    value = valid_blueprint()

    parsed = parse_blueprint(value)

    assert parsed.identity.name == "breaker-copy-v1"
    assert parsed.operations[0].operation_id == "op-001"
    assert parsed.operations[0].arguments["location"] == (20, 30)
    assert parsed.to_dict() == value
    assert json.loads(json.dumps(parsed.to_dict(), allow_nan=False)) == value
    with pytest.raises(TypeError):
        parsed.operations[0].arguments["logical_id"] = "changed"
    with pytest.raises(TypeError):
        parsed.publication.evidence_files[0] = "changed"


def test_parse_blueprint_copies_input_before_freezing():
    value = valid_blueprint()
    parsed = parse_blueprint(value)

    value["operations"][0]["arguments"]["location"][0] = 999

    assert parsed.operations[0].arguments["location"] == (20, 30)


@pytest.mark.parametrize("extra_path", ["top", "identity", "source", "operation", "acceptance", "publication"])
def test_parse_blueprint_rejects_unknown_fields(extra_path):
    value = valid_blueprint()
    target = {
        "top": value,
        "identity": value["identity"],
        "source": value["source_package"],
        "operation": value["operations"][0],
        "acceptance": value["acceptance"],
        "publication": value["publication"],
    }[extra_path]
    target["unexpected"] = True

    assert_schema_error(value)


@pytest.mark.parametrize("schema_version", [0, 2, True, "1"])
def test_parse_blueprint_rejects_unknown_or_non_integer_schema_versions(schema_version):
    value = valid_blueprint()
    value["identity"]["schema_version"] = schema_version

    assert_schema_error(value, "BLUEPRINT_SCHEMA_UNSUPPORTED" if schema_version == 2 else "BLUEPRINT_SCHEMA_INVALID")


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value["operations"].reverse(),
        lambda value: value["operations"][1].update(sequence=1),
        lambda value: value["operations"][1].update(operation_id="op-001"),
        lambda value: value["operations"][0].update(kind="delete_component"),
        lambda value: value["operations"][0]["arguments"].update(location=[True, 2]),
        lambda value: value["operations"][0]["arguments"].update(value=float("nan")),
        lambda value: value["acceptance"]["rules"][0].update(source_class="invented"),
        lambda value: value["publication"].update(scope="physical_acceptance"),
        lambda value: value["source_package"].update(handling_policy="overwrite"),
    ],
)
def test_parse_blueprint_rejects_unsafe_or_ambiguous_contracts(mutator):
    value = valid_blueprint()
    mutator(value)

    assert_schema_error(value)


def test_build_state_declares_ordered_and_terminal_states():
    assert BlueprintBuildState.PLANNED.value == "planned"
    assert BlueprintBuildState.RELOADED.value == "reloaded"
    assert BlueprintBuildState.ACCEPTANCE_PASSED.value == "acceptance_passed"
    assert BlueprintBuildState.QUARANTINED.value == "quarantined"
    assert BlueprintBuildState.PUBLISHED.value == "published"


def test_parse_blueprint_rejects_duplicate_required_paths_and_output_channels():
    value = valid_blueprint()
    value["source_package"]["required"].append(copy.deepcopy(value["source_package"]["required"][0]))
    assert_schema_error(value)

    value = valid_blueprint()
    value["acceptance"]["outputs"].append(copy.deepcopy(value["acceptance"]["outputs"][0]))
    assert_schema_error(value)
