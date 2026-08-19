import asyncio

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.preflight import verify_required_result_selectors


def test_measurement_contract_rejects_duplicate_observed_endpoint():
    from pscad_mcp.hvdc.builders.lcc.measurements import validate_measurements

    with pytest.raises(BackendError) as raised:
        validate_measurements(
            [
                {"canonical": "vdc_a", "path": "Main/Vdc", "call_id": 4, "units": "kV"},
                {"canonical": "vdc_b", "path": "Main/Vdc", "call_id": 4, "units": "kV"},
            ]
        )

    assert raised.value.code == "MEASUREMENT_CONTRACT_INVALID"
    assert raised.value.details["endpoint"] == {"path": "Main/Vdc", "call_id": 4}


def test_measurement_contract_rejects_duplicate_canonical():
    from pscad_mcp.hvdc.builders.lcc.measurements import validate_measurements

    with pytest.raises(BackendError) as raised:
        validate_measurements(
            [
                {"canonical": "vdc", "path": "Main/Vdc", "units": "kV"},
                {"canonical": "vdc", "path": "Main/Vdc2", "units": "kV"},
            ]
        )

    assert raised.value.code == "MEASUREMENT_CONTRACT_INVALID"


@pytest.mark.parametrize("missing", ["sources", "expression", "units", "time_domain"])
def test_derived_measurement_requires_complete_signal_contract(missing):
    from pscad_mcp.hvdc.builders.lcc.measurements import validate_measurements

    derived = {
        "canonical": "dc_power",
        "kind": "derived",
        "sources": ["dc_voltage", "dc_current"],
        "expression": "dc_voltage * dc_current",
        "units": "MW",
        "time_domain": "EMTDC",
    }
    derived.pop(missing)

    with pytest.raises(BackendError) as raised:
        validate_measurements([derived])

    assert raised.value.code == "MEASUREMENT_CONTRACT_INVALID"
    assert missing in str(raised.value)


def test_valid_observed_and_derived_measurements_are_normalized():
    from pscad_mcp.hvdc.builders.lcc.measurements import validate_measurements

    result = validate_measurements(
        [
            {"canonical": "dc_voltage", "path": "Main/Vdc", "units": "kV"},
            {"canonical": "dc_current", "path": "Main/Idc", "units": "kA"},
            {
                "canonical": "dc_power",
                "kind": "derived",
                "sources": ["dc_voltage", "dc_current"],
                "expression": "dc_voltage * dc_current",
                "units": "MW",
                "time_domain": "EMTDC",
            },
        ]
    )

    assert [item["canonical"] for item in result] == [
        "dc_current",
        "dc_power",
        "dc_voltage",
    ]
    assert next(item for item in result if item["canonical"] == "dc_voltage")["kind"] == "observed"


def test_preflight_rejects_ambiguous_endpoint_before_backend_inspection():
    profile = {
        "profile_version": 2,
        "result_channels": [
            {"canonical": "vdc_a", "path": "Main/Vdc", "call_id": 4, "units": "kV"},
            {"canonical": "vdc_b", "path": "Main/Vdc", "call_id": 4, "units": "kV"},
        ],
        "metric_roles": {},
    }

    class Backend:
        def __init__(self):
            self.inspected = False

        async def get_output_channels(self, project_name):
            self.inspected = True
            return []

    backend = Backend()
    with pytest.raises(BackendError) as raised:
        asyncio.run(verify_required_result_selectors(backend, "derived", profile, []))

    assert raised.value.code == "MEASUREMENT_CONTRACT_INVALID"
    assert backend.inspected is False
