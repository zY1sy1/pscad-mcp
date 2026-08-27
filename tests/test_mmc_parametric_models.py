import json

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.parametric_models import parse_parametric_request
from tests.mmc_parametric_fakes import valid_request


def test_parse_dual_engine_request_is_finite_and_immutable() -> None:
    request = parse_parametric_request(valid_request(model_fidelity="both"))
    assert request.model_fidelity == "both"
    assert request.topology == "two_terminal_symmetrical_monopole"
    assert request.converter == "half_bridge"
    assert request.dc_voltage_kv == 640.0
    assert request.station_p.short_circuit_ratio == 5.0
    with pytest.raises(TypeError):
        request.engineering_overrides["arm_inductance_h"] = 1.0
    assert json.loads(json.dumps(request.to_dict()))["station_vdc"]["ac_voltage_kv"] == 230.0


@pytest.mark.parametrize("field", ["dc_voltage_kv", "active_power_mw", "frequency_hz"])
def test_request_rejects_non_finite_values(field: str) -> None:
    payload = valid_request()
    payload[field] = float("nan")
    with pytest.raises(BackendError) as raised:
        parse_parametric_request(payload)
    assert raised.value.code == "MMC_REQUEST_INVALID"


def test_request_rejects_unknown_fields_and_boolean_numbers() -> None:
    with pytest.raises(BackendError):
        parse_parametric_request(valid_request(unexpected=True))
    payload = valid_request()
    payload["dc_voltage_kv"] = True
    with pytest.raises(BackendError):
        parse_parametric_request(payload)


def test_engineering_overrides_require_finite_values_and_supported_units() -> None:
    request = parse_parametric_request(
        valid_request(engineering_overrides={"arm_inductance_h": {"value": 0.05, "unit": "H"}})
    )
    assert request.engineering_overrides["arm_inductance_h"]["unit"] == "H"
    with pytest.raises(BackendError):
        parse_parametric_request(
            valid_request(engineering_overrides={"arm_inductance_h": {"value": 0.05, "unit": "bananas"}})
        )
