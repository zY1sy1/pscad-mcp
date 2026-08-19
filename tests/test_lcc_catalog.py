import copy

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.catalog import (
    parse_catalog,
    require_definition,
    require_port,
    validate_parameters,
)


CATALOG = {
    "schema_version": 1,
    "name": "cigre_lcc_monopole_v1",
    "pscad_version": "4.6.2",
    "identity": "cigre_lcc_monopole_v1/catalog-pscad-4.6.2",
    "definitions": [
        {
            "scoped_name": "master:source3",
            "ports": [
                {"name": "A", "kind": "electrical", "dimension": 3, "offset": [12, 6]}
            ],
            "parameters": {
                "Amplitude": {"type": "float", "minimum": 0.0, "maximum": 1000.0},
                "Mode": {"type": "enum", "enum": ["balanced", "single"]},
                "Enabled": {"type": "boolean", "required": False},
            },
            "bounding_box": [-10, -10, 10, 10],
        },
        {
            "scoped_name": "cigre_lcc_v1:LCC12PulseBridge",
            "ports": [
                {"name": "AC", "kind": "electrical", "dimension": 3, "offset": [-12, 6]},
                {"name": "GATES", "kind": "data", "dimension": 12, "offset": [12, 6]},
            ],
            "parameters": {
                "ValveDrop": {"type": "float", "minimum": 0.0, "maximum": 10.0},
            },
            "bounding_box": [-20, -20, 20, 20],
        },
    ],
}


def _assert_code(call, code):
    with pytest.raises(BackendError) as raised:
        call()
    assert raised.value.code == code


def test_catalog_uses_exact_scoped_definition_and_port_contracts():
    catalog = parse_catalog(CATALOG)

    definition = require_definition(catalog, "master:source3")
    port = require_port(definition, "A", kind="electrical", dimension=3)

    assert definition.scoped_name == "master:source3"
    assert port.offset == (12, 6)
    _assert_code(lambda: require_definition(catalog, "source3"), "LCC_DEFINITION_MISSING")
    _assert_code(
        lambda: require_port(definition, "A", kind="data", dimension=3),
        "LCC_PORT_MISMATCH",
    )
    _assert_code(
        lambda: require_port(definition, "A", kind="electrical", dimension=12),
        "LCC_PORT_MISMATCH",
    )


def test_catalog_parameter_validation_is_exact_and_does_not_mutate_input():
    catalog = parse_catalog(CATALOG)
    definition = require_definition(catalog, "master:source3")
    requested = {"Amplitude": 230, "Mode": "balanced"}
    original = copy.deepcopy(requested)

    normalized = validate_parameters(definition, requested)

    assert requested == original
    assert normalized == requested
    _assert_code(lambda: validate_parameters(definition, {"Unknown": 1}), "LCC_PARAMETER_MISMATCH")
    _assert_code(lambda: validate_parameters(definition, {"Amplitude": True}), "LCC_PARAMETER_MISMATCH")
    _assert_code(lambda: validate_parameters(definition, {"Amplitude": -1}), "LCC_PARAMETER_MISMATCH")
    _assert_code(lambda: validate_parameters(definition, {"Amplitude": 1, "Mode": "bad"}), "LCC_PARAMETER_MISMATCH")


def test_catalog_rejects_invalid_schema_and_boolean_numeric_metadata():
    invalid = copy.deepcopy(CATALOG)
    invalid["definitions"][0]["ports"][0]["dimension"] = True

    _assert_code(lambda: parse_catalog(invalid), "LCC_BLUEPRINT_INVALID")

