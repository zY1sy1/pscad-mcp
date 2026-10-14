"""The routed PWM path refuses partial rating changes and fallback writes."""

import asyncio
from types import SimpleNamespace

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.pwm_routed_engine import (
    execute_routed_pwm_candidate,
    require_supported_request,
)
from tests.mmc_parametric_fakes import valid_request


def test_supported_reference_point_is_explicit():
    require_supported_request(
        valid_request(model_fidelity="detailed_pwm", converter="full_bridge")
    )


@pytest.mark.parametrize(
    "override",
    [
        {"active_power_mw": 900.0},
        {"frequency_hz": 50.0},
        {"dc_link": {"kind": "overhead_line", "length_km": 100.0}},
        {"engineering_overrides": {"arm_inductance_h": {"value": 0.1, "unit": "H"}}},
    ],
)
def test_unbound_rating_changes_cannot_be_silently_ignored(override):
    with pytest.raises(BackendError) as raised:
        require_supported_request(
            valid_request(
                model_fidelity="detailed_pwm", converter="full_bridge", **override
            )
        )
    assert raised.value.code == "MMC_PWM_PARAMETER_UNSUPPORTED"
    assert raised.value.details["unsupported_fields"]


def test_fallback_candidate_is_rejected_before_accessing_pscad_or_files(tmp_path):
    plan = SimpleNamespace(
        capabilities={
            "routed_pwm_preparation": {
                "request": valid_request(
                    model_fidelity="detailed_pwm", converter="full_bridge"
                )
            }
        },
        workspace=str(tmp_path),
    )
    with pytest.raises(BackendError) as raised:
        asyncio.run(
            execute_routed_pwm_candidate(
                plan, object(), SimpleNamespace(purpose="energy_balance"), []
            )
        )
    assert raised.value.code == "MMC_PWM_PARAMETER_UNSUPPORTED"
    assert not list(tmp_path.iterdir())
