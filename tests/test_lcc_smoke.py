from __future__ import annotations

import copy
import importlib
import math

import pytest

from pscad_mcp.core.backend.base import BackendError

REQUIRED = (
    "Main/IDC",
    "Main/VDC_RECT",
    "Main/VDC_INV",
    "Main/AO_RECT_Y",
    "Main/AO_RECT_D",
    "Main/AO_INV_Y",
    "Main/AO_INV_D",
    "Main/GAMMA_INV",
    "Main/ENABLE_RECT",
    "Main/ENABLE_INV",
)


def _subject():
    return importlib.import_module(
        "pscad_mcp.hvdc.builders.lcc.smoke"
    ).evaluate_fixed_smoke


def contract() -> dict[str, object]:
    return {
        "schema_version": 1,
        "identity": "cigre_lcc_monopole_v1/wp1b_smoke",
        "duration_s": 0.1,
        "output_step_s": 0.00005,
        "required_channels": list(REQUIRED),
        "enable_channels": ["Main/ENABLE_RECT", "Main/ENABLE_INV"],
        "ao_limits_rad": {
            "Main/AO_RECT_Y": [
                0.08726646259971647,
                0.5235987755982988,
            ],
            "Main/AO_RECT_D": [
                0.08726646259971647,
                0.5235987755982988,
            ],
            "Main/AO_INV_Y": [0.52, 1.92],
            "Main/AO_INV_D": [0.52, 1.92],
        },
    }


def valid_samples() -> dict[str, object]:
    time = [index * 0.00005 for index in range(2001)]
    values = {
        "Main/IDC": ([1.0 for _ in time], "kA"),
        "Main/VDC_RECT": ([500.0 for _ in time], "kV"),
        "Main/VDC_INV": ([-480.0 for _ in time], "kV"),
        "Main/AO_RECT_Y": (
            [0.2617993877991494 for _ in time],
            "rad",
        ),
        "Main/AO_RECT_D": (
            [0.2617993877991494 for _ in time],
            "rad",
        ),
        "Main/AO_INV_Y": ([1.57 for _ in time], "rad"),
        "Main/AO_INV_D": ([1.57 for _ in time], "rad"),
        "Main/GAMMA_INV": (
            [0.3141592653589793 for _ in time],
            "rad",
        ),
        "Main/ENABLE_RECT": ([1.0 for _ in time], "state"),
        "Main/ENABLE_INV": ([1.0 for _ in time], "state"),
    }
    return {
        "channels": {
            name: {
                "time": list(time),
                "values": channel_values,
                "units": units,
            }
            for name, (channel_values, units) in values.items()
        }
    }


def mutate_samples(
    payload: dict[str, object],
    mutation: str,
) -> dict[str, object]:
    candidate = copy.deepcopy(payload)
    channels = candidate["channels"]
    if mutation == "missing_channel":
        channels.pop("Main/IDC")
    elif mutation == "non_monotonic_time":
        channel = channels["Main/IDC"]
        channel["time"][100] = channel["time"][99]
    elif mutation == "short_domain":
        for channel in channels.values():
            channel["time"] = channel["time"][:1000]
            channel["values"] = channel["values"][:1000]
    elif mutation == "shifted_domain":
        channel = channels["Main/VDC_INV"]
        channel["time"] = [value + 0.00005 for value in channel["time"]]
    elif mutation == "nan":
        channels["Main/IDC"]["values"][1] = math.nan
    elif mutation == "disabled":
        channels["Main/ENABLE_RECT"]["values"][0] = 0.0
    elif mutation == "ao_low":
        channels["Main/AO_RECT_Y"]["values"][0] = 0.01
    elif mutation == "ao_high":
        channels["Main/AO_INV_D"]["values"][0] = 2.0
    elif mutation == "length_mismatch":
        channels["Main/IDC"]["values"].pop()
    elif mutation == "missing_values":
        channels["Main/IDC"].pop("values")
    else:
        raise AssertionError(f"unsupported mutation: {mutation}")
    return candidate


def test_valid_no_fault_smoke_passes_without_acceptance_claims():
    result = _subject()(valid_samples(), contract())

    assert result["verdict"] == "PASS"
    assert result["checks"] == {
        "time_domain": True,
        "finite_outputs": True,
        "controls_enabled": True,
        "ao_within_limits": True,
    }
    assert result["evidence"]["domain_start_s"] == pytest.approx(0.0)
    assert result["evidence"]["domain_end_s"] == pytest.approx(0.1)
    assert result["evidence"]["samples"] == 2001
    assert "golden" not in result
    assert "disturbance" not in result
    assert "accepted" not in result


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("missing_channel", "missing_channel"),
        ("non_monotonic_time", "invalid_time_domain"),
        ("short_domain", "invalid_time_domain"),
        ("shifted_domain", "inconsistent_time_domain"),
        ("nan", "nonfinite_output"),
        ("disabled", "control_not_enabled"),
        ("ao_low", "ao_out_of_bounds"),
        ("ao_high", "ao_out_of_bounds"),
        ("length_mismatch", "invalid_time_domain"),
        ("missing_values", "nonfinite_output"),
    ],
)
def test_smoke_failures_are_structured(mutation: str, reason: str):
    with pytest.raises(BackendError) as failure:
        _subject()(mutate_samples(valid_samples(), mutation), contract())

    assert failure.value.code == "LCC_FIXED_SMOKE_FAILED"
    assert failure.value.details["reason"] == reason


@pytest.mark.parametrize(
    "mutation",
    [
        "extra_field",
        "duplicate_required",
        "unknown_enable",
        "nonfinite_limit",
        "inverted_limit",
    ],
)
def test_smoke_contract_is_strict_and_finite(mutation: str):
    value = contract()
    if mutation == "extra_field":
        value["unexpected"] = True
    elif mutation == "duplicate_required":
        value["required_channels"].append("Main/IDC")
    elif mutation == "unknown_enable":
        value["enable_channels"].append("Main/UNKNOWN")
    elif mutation == "nonfinite_limit":
        value["ao_limits_rad"]["Main/AO_RECT_Y"][0] = math.nan
    elif mutation == "inverted_limit":
        value["ao_limits_rad"]["Main/AO_RECT_Y"] = [1.0, 0.0]

    with pytest.raises(BackendError) as failure:
        _subject()(valid_samples(), value)

    assert failure.value.code == "LCC_FIXED_SMOKE_INVALID"


def test_global_time_payload_is_supported():
    payload = valid_samples()
    first = next(iter(payload["channels"].values()))
    payload["time"] = list(first["time"])
    for channel in payload["channels"].values():
        channel.pop("time")

    result = _subject()(payload, contract())

    assert result["verdict"] == "PASS"
