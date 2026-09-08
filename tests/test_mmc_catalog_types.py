import copy

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.catalog import (
    MmcDefinitionSpec,
    MmcParameterSpec,
    parse_catalog,
    validate_parameters,
)


def _catalog(parameters, *, definition="test:TypedComponent"):
    return {
        "schema_version": 1,
        "pscad_version": "4.6.2",
        "definitions": {definition: {"parameters": parameters}},
    }


def _definition(parameters):
    return parse_catalog(_catalog(parameters)).definitions["test:TypedComponent"]


def test_catalog_validates_native_nodelabel_name_without_changing_text():
    catalog = parse_catalog(
        _catalog({"Name": {"type": "string"}}, definition="master:nodelabel")
    )
    requested = {"Name": "STATION_P_DC_POS"}

    normalized = validate_parameters(catalog.definitions["master:nodelabel"], requested)

    assert normalized == requested
    assert normalized is not requested


def test_catalog_validates_mixed_avm_parameter_types_and_defaults():
    definition = _definition(
        {
            "rated_power_mw": {"type": "number", "minimum": 0},
            "blocked_state_path": {
                "type": "text",
                "default": "half_bridge_diode_equivalent",
            },
            "intrinsic_dc_fault_blocking": {"type": "boolean", "default": False},
            "optional_gain": {"type": "real", "required": False},
        }
    )
    requested = {"rated_power_mw": 750.0}
    original = copy.deepcopy(requested)

    normalized = validate_parameters(definition, requested)

    assert normalized == {
        "rated_power_mw": 750.0,
        "blocked_state_path": "half_bridge_diode_equivalent",
        "intrinsic_dc_fault_blocking": False,
    }
    assert normalized["intrinsic_dc_fault_blocking"] is False
    assert requested == original


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        ("number", 1),
        ("real", 1.5),
        ("float", 1.5),
        ("double", 1),
        ("integer", 2),
        ("int", 2),
        ("string", ""),
        ("text", "  label with spaces  "),
        ("str", "label"),
        ("boolean", True),
        ("boolean", False),
        (" INTEGER ", 2),
    ],
)
def test_catalog_preserves_valid_scalar_values(value_type, value):
    definition = _definition({"Value": {"type": value_type}})

    normalized = validate_parameters(definition, {"Value": value})

    assert normalized == {"Value": value}
    assert type(normalized["Value"]) is type(value)


@pytest.mark.parametrize("value_type", ["number", "real", "float", "integer"])
@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        "1",
        None,
        [],
        {},
        float("nan"),
        float("inf"),
        -float("inf"),
        pytest.param(10**400, id="overflowing-integer"),
    ],
)
def test_numeric_parameters_reject_non_finite_and_non_numeric_values(value_type, value):
    definition = _definition({"Value": {"type": value_type}})

    with pytest.raises(BackendError) as raised:
        validate_parameters(definition, {"Value": value})

    assert raised.value.code == "MMC_PARAMETER_MISMATCH"
    assert raised.value.details["parameter"] == "Value"


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        ("integer", 1.0),
        ("integer", 1.5),
        ("boolean", 0),
        ("boolean", 1),
        ("boolean", "true"),
        ("boolean", None),
        ("string", 1),
        ("string", True),
        ("string", None),
        ("text", []),
    ],
)
def test_scalar_parameters_reject_values_of_another_type(value_type, value):
    definition = _definition({"Value": {"type": value_type}})

    with pytest.raises(BackendError) as raised:
        validate_parameters(definition, {"Value": value})

    assert raised.value.code == "MMC_PARAMETER_MISMATCH"


@pytest.mark.parametrize("value_type", ["number", "real", "integer"])
def test_numeric_parameters_retain_inclusive_range_contracts(value_type):
    definition = _definition({"Value": {"type": value_type, "min": 1, "max": 3}})

    for value in (1, 3):
        assert validate_parameters(definition, {"Value": value}) == {"Value": value}
    for value in (0, 4):
        with pytest.raises(BackendError) as raised:
            validate_parameters(definition, {"Value": value})
        assert raised.value.code == "MMC_PARAMETER_MISMATCH"
        assert "outside its exact range" in str(raised.value)


@pytest.mark.parametrize(
    ("value_type", "default"),
    [("integer", 1.5), ("boolean", 1), ("string", 1), ("number", float("nan"))],
)
def test_default_values_must_match_the_declared_type(value_type, default):
    definition = _definition({"Value": {"type": value_type, "default": default}})

    with pytest.raises(BackendError) as raised:
        validate_parameters(definition, {})

    assert raised.value.code == "MMC_PARAMETER_MISMATCH"


@pytest.mark.parametrize("value_type", ["object", "array", "choice", "enum", "typo"])
def test_catalog_rejects_unsupported_parameter_types(value_type):
    with pytest.raises(BackendError) as raised:
        _definition({"Value": {"type": value_type}})

    assert raised.value.code == "MMC_BLUEPRINT_INVALID"
    assert raised.value.details["value_type"] == value_type


def test_direct_parameter_specs_cannot_bypass_type_validation():
    definition = MmcDefinitionSpec(
        "test:TypedComponent", parameters={"Value": MmcParameterSpec("Value", "typo")}
    )

    with pytest.raises(BackendError) as raised:
        validate_parameters(definition, {"Value": 1})

    assert raised.value.code == "MMC_PARAMETER_MISMATCH"


def test_catalog_preserves_missing_unknown_and_unspecified_parameter_contracts():
    definition = _definition({"Value": {}})

    assert definition.parameters["Value"].value_type == "number"
    assert validate_parameters(definition, {"Value": 1.5}) == {"Value": 1.5}
    for requested in ({}, {"Value": 1.5, "Unknown": 2}):
        with pytest.raises(BackendError) as raised:
            validate_parameters(definition, requested)
        assert raised.value.code == "MMC_PARAMETER_MISMATCH"

    requested = {"Unspecified": "text", "Enabled": False}
    normalized = validate_parameters(_definition({}), requested)
    assert normalized == requested
    assert normalized is not requested
