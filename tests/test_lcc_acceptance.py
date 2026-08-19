import json
import math

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.acceptance import (
    align_positive_zero_crossing,
    evaluate_acceptance,
    interpolate_to_grid,
    normalized_errors,
)
from pscad_mcp.hvdc.builders.lcc.assets import load_packaged_asset_set


FREQUENCY_HZ = 50.0
DT = 0.001


def _time(count=61, start=0.0):
    return [start + DT * index for index in range(count)]


def _sine(times, delay=0.0):
    return [math.sin(2.0 * math.pi * FREQUENCY_HZ * (time - delay)) for time in times]


def _golden_payload():
    times = _time()
    return {
        "time": times,
        "channels": {
            "Main/VAC_RECT_A": {"values": _sine(times), "units": "kV"},
            "Main/VDC_RECT": {"values": [500.0 for _ in times], "units": "kV"},
        },
    }


def _sample_payload(delay=DT):
    times = _time()
    return {
        "time": times,
        "channels": {
            "Main/VAC_RECT_A": {"values": _sine(times, delay=delay), "units": "kV"},
            "Main/VDC_RECT": {"values": [500.0 for _ in times], "units": "kV"},
        },
    }


def _golden_contract():
    return {
        "golden": {
            "comparison_window": [0.003, 0.038],
            "alignment": {
                "channel": "Main/VAC_RECT_A",
                "rule": "positive_zero_crossing",
                "frequency_hz": FREQUENCY_HZ,
                "max_cycles": 1.0,
            },
            "channels": [
                {
                    "name": "Main/VAC_RECT_A",
                    "units": "kV",
                    "scale_floor": 0.1,
                    "nrmse_limit": 1e-11,
                    "max_error_limit": 1e-11,
                    "required": True,
                }
            ],
        }
    }


def _physical_samples(**overrides):
    time = [0.04, 0.05, 0.06, 0.07]
    channels = {
        "Main/VDC_RECT": {"values": [500.0, 501.0, 499.0, 500.0], "units": "kV"},
        "Main/IDC": {"values": [2.0, 2.0, 2.0, 2.0], "units": "kA"},
        "Main/PDC": {"values": [1000.0, 1002.0, 998.0, 1000.0], "units": "MW"},
        "Main/P_RECT": {"values": [1010.0, 1010.0, 1010.0, 1010.0], "units": "MW"},
        "Main/P_INV": {"values": [-995.0, -995.0, -995.0, -995.0], "units": "MW"},
        "Main/ALPHA_RECT": {"values": [15.0, 15.2, 14.8, 15.0], "units": "deg"},
        "Main/GAMMA_INV": {"values": [18.0, 18.1, 17.9, 18.0], "units": "deg"},
        "Main/MU_RECT": {"values": [22.0, 22.1, 21.9, 22.0], "units": "deg"},
        "Main/IDC_ORDER": {"values": [2.01, 2.01, 2.01, 2.01], "units": "kA"},
    }
    for name, values in overrides.items():
        if values is None:
            channels.pop(name, None)
        else:
            channels[name]["values"] = values
    return {"time": time, "channels": channels}


def _physical_contract(required=True):
    return {
        "physical_checks": [
            {
                "name": "rectifier_dc_voltage",
                "kind": "dc_magnitude_polarity",
                "required": required,
                "channel": "Main/VDC_RECT",
                "units": "kV",
                "window": [0.04, 0.07],
                "aggregation": "mean",
                "min": 498.0,
                "max": 502.0,
                "polarity": "positive",
            },
            {
                "name": "dc_current",
                "kind": "dc_magnitude_polarity",
                "required": required,
                "channel": "Main/IDC",
                "units": "kA",
                "window": [0.04, 0.07],
                "aggregation": "mean",
                "min": 1.95,
                "max": 2.05,
                "polarity": "positive",
            },
            {
                "name": "pdc_product",
                "kind": "pdc_product",
                "required": required,
                "voltage_channel": "Main/VDC_RECT",
                "current_channel": "Main/IDC",
                "power_channel": "Main/PDC",
                "voltage_units": "kV",
                "current_units": "kA",
                "power_units": "MW",
                "window": [0.04, 0.07],
                "max_abs": 3.0,
            },
            {
                "name": "terminal_power_balance",
                "kind": "terminal_power_balance",
                "required": required,
                "rectifier_power_channel": "Main/P_RECT",
                "inverter_power_channel": "Main/P_INV",
                "units": "MW",
                "window": [0.04, 0.07],
                "loss_allowance": 20.0,
            },
            {
                "name": "firing_angle",
                "kind": "angle_interval",
                "required": required,
                "channel": "Main/ALPHA_RECT",
                "units": "deg",
                "window": [0.04, 0.07],
                "min": 14.0,
                "max": 16.0,
            },
            {
                "name": "extinction_angle",
                "kind": "angle_interval",
                "required": required,
                "channel": "Main/GAMMA_INV",
                "units": "deg",
                "window": [0.04, 0.07],
                "min": 17.0,
                "max": 19.0,
            },
            {
                "name": "overlap_angle",
                "kind": "angle_interval",
                "required": required,
                "channel": "Main/MU_RECT",
                "units": "deg",
                "window": [0.04, 0.07],
                "min": 21.0,
                "max": 23.0,
            },
            {
                "name": "dc_voltage_ripple",
                "kind": "ripple",
                "required": required,
                "channel": "Main/VDC_RECT",
                "units": "kV",
                "window": [0.04, 0.07],
                "max_percent": 1.0,
            },
            {
                "name": "current_order_error",
                "kind": "steady_state_control_error",
                "required": required,
                "actual_channel": "Main/IDC",
                "target_channel": "Main/IDC_ORDER",
                "units": "kA",
                "window": [0.04, 0.07],
                "max_abs": 0.02,
            },
        ]
    }


def test_normalized_errors_use_percentile95_scale_floor_nrmse_and_maximum():
    actual = [1.0, 8.0, 23.0, 29.0]
    golden = [0.0, 10.0, 20.0, 30.0]

    nrmse, maximum = normalized_errors(actual, golden, scale_floor=1.0)

    scale = 28.5
    assert nrmse == pytest.approx(math.sqrt((1.0 + 4.0 + 9.0 + 1.0) / 4.0) / scale)
    assert maximum == pytest.approx(3.0 / scale)


def test_normalized_errors_reject_empty_or_unequal_vectors():
    for actual, golden in [([], []), ([1.0], []), ([1.0], [1.0, 2.0])]:
        with pytest.raises(BackendError) as raised:
            normalized_errors(actual, golden, scale_floor=1.0)
        assert raised.value.code == "LCC_ACCEPTANCE_INVALID"


def test_positive_zero_crossing_alignment_detects_known_one_sample_shift():
    times = _time()

    result = align_positive_zero_crossing(
        times,
        _sine(times, delay=DT),
        times,
        _sine(times),
        frequency_hz=FREQUENCY_HZ,
        max_cycles=1.0,
    )

    assert result["rule"] == "positive_zero_crossing"
    assert result["shift_seconds"] == pytest.approx(DT)
    assert result["max_shift_seconds"] == pytest.approx(1.0 / FREQUENCY_HZ)


def test_alignment_shift_is_bounded_to_one_fundamental_cycle():
    with pytest.raises(BackendError) as raised:
        align_positive_zero_crossing(
            [0.0, 0.021, 0.022],
            [-1.0, 0.0, 1.0],
            [0.0, 0.001, 0.002],
            [0.0, 1.0, 2.0],
            frequency_hz=FREQUENCY_HZ,
            max_cycles=1.0,
        )
    assert raised.value.code == "LCC_ACCEPTANCE_INCOMPLETE"


def test_linear_interpolation_and_extrapolation_rejection():
    assert interpolate_to_grid([0.0, 1.0, 2.0], [0.0, 10.0, 20.0], [0.5, 1.5]) == [5.0, 15.0]

    with pytest.raises(BackendError) as raised:
        interpolate_to_grid([0.0, 1.0], [0.0, 10.0], [-0.1])
    assert raised.value.code == "LCC_ACCEPTANCE_INCOMPLETE"


def test_evaluate_acceptance_compares_golden_on_shifted_golden_grid_without_extrapolation():
    result = evaluate_acceptance(_sample_payload(), _golden_payload(), _golden_contract())

    assert result["verdict"] == "PASS"
    assert result["alignment"]["status"] == "observed"
    assert result["alignment"]["shift_seconds"] == pytest.approx(DT)
    assert result["golden_checks"][0]["status"] == "observed"
    assert result["golden_checks"][0]["metrics"]["nrmse"] <= 1e-11
    assert result["canonical"]["golden_channels"] == ["Main/VAC_RECT_A"]
    json.dumps(result)


def test_required_manifest_checks_without_executable_declarations_are_incomplete():
    result = evaluate_acceptance(
        {},
        {},
        {
            "checks": [
                {"name": "golden_waveforms", "kind": "golden", "required": True},
                {"name": "power_balance", "kind": "physical", "required": True},
            ]
        },
    )

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["errors"]
    assert all(check["outcome"] == "INCOMPLETE_ANALYSIS" for check in result["golden_checks"] + result["physical_checks"])


def test_unknown_required_manifest_check_cannot_produce_pass():
    result = evaluate_acceptance(
        _sample_payload(),
        _golden_payload(),
        {
            **_golden_contract(),
            "checks": [{"name": "future_gate", "kind": "future", "required": True}],
        },
    )

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["manifest_checks"][0]["outcome"] == "INCOMPLETE_ANALYSIS"


@pytest.mark.parametrize(
    "comparison_window",
    [
        0.003,
        [0.003],
        [[0.003, 0.038], 0.038],
        ["start", 0.038],
        [0.038, 0.003],
    ],
)
def test_malformed_golden_comparison_window_raises_invalid_backend_error(comparison_window):
    contract = _golden_contract()
    contract["golden"]["comparison_window"] = comparison_window

    with pytest.raises(BackendError) as raised:
        evaluate_acceptance(_sample_payload(), _golden_payload(), contract)

    assert raised.value.code == "LCC_ACCEPTANCE_INVALID"


@pytest.mark.parametrize(
    ("samples", "golden", "contract", "reason"),
    [
        (
            {"time": _time(), "channels": {}},
            _golden_payload(),
            _golden_contract(),
            "missing channel",
        ),
        (
            {"time": _time(), "channels": {"Main/VAC_RECT_A": {"values": [], "units": "kV"}}},
            _golden_payload(),
            _golden_contract(),
            "empty samples",
        ),
        (
            {"time": _time(), "channels": {"Main/VAC_RECT_A": {"values": [math.nan] + _sine(_time())[1:], "units": "kV"}}},
            _golden_payload(),
            _golden_contract(),
            "non-finite sample",
        ),
        (
            {"time": [0.0, 0.001, 0.001], "channels": {"Main/VAC_RECT_A": {"values": [0.0, 1.0, 2.0], "units": "kV"}}},
            _golden_payload(),
            _golden_contract(),
            "duplicate or non-monotonic time",
        ),
        (
            {"time": _time(), "channels": {"Main/VAC_RECT_A": {"values": _sine(_time()), "units": "V"}}},
            _golden_payload(),
            _golden_contract(),
            "unit mismatch",
        ),
        (
            {"time": _time(), "channels": {"Main/VAC_RECT_A": {"values": [1.0 for _ in _time()], "units": "kV"}}},
            _golden_payload(),
            _golden_contract(),
            "alignment failed",
        ),
        (
            {"channels": {"Main/VAC_RECT_A": {"time": [1.0, 1.001], "values": [0.0, 1.0], "units": "kV"}}},
            _golden_payload(),
            {
                "golden": {
                    "comparison_window": [0.003, 0.038],
                    "channels": [
                        {
                            "name": "Main/VAC_RECT_A",
                            "units": "kV",
                            "scale_floor": 0.1,
                            "nrmse_limit": 1e-11,
                            "max_error_limit": 1e-11,
                            "required": True,
                        }
                    ],
                }
            },
            "inconsistent domains",
        ),
    ],
)
def test_data_quality_failures_are_incomplete_not_zero_filled(samples, golden, contract, reason):
    result = evaluate_acceptance(samples, golden, contract)

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["errors"][0]["reason"] == reason
    assert all(check.get("observed") != 0 for check in result["golden_checks"])


def test_channel_sample_limit_is_enforced_deterministically():
    result = evaluate_acceptance(
        {
            "time": [index * DT for index in range(1_000_001)],
            "channels": {"Main/VAC_RECT_A": {"values": [0.0 for _ in range(1_000_001)], "units": "kV"}},
        },
        _golden_payload(),
        _golden_contract(),
    )

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["errors"][0]["reason"] == "too many samples"
    assert result["errors"][0]["limit"] == 1_000_000


def test_unused_channel_over_sample_limit_is_rejected_during_canonical_validation():
    samples = _sample_payload()
    long_time = [index * DT for index in range(1_000_001)]
    samples["channels"]["Main/UNUSED"] = {
        "time": long_time,
        "values": [0.0] * len(long_time),
        "units": "kV",
    }

    result = evaluate_acceptance(samples, _golden_payload(), _golden_contract())

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["errors"][0]["reason"] == "too many samples"
    assert result["errors"][0]["limit"] == 1_000_000


def test_multi_channel_physical_check_rejects_equal_length_shifted_domains():
    time = [0.04, 0.05, 0.06, 0.07]
    shifted_time = [value + 0.001 for value in time]
    samples = {
        "channels": {
            "Main/VDC_RECT": {"time": time, "values": [500.0] * 4, "units": "kV"},
            "Main/IDC": {"time": shifted_time, "values": [2.0] * 4, "units": "kA"},
            "Main/PDC": {"time": time, "values": [1000.0] * 4, "units": "MW"},
        }
    }
    contract = {
        "physical_checks": [
            {
                "name": "pdc_product",
                "kind": "pdc_product",
                "required": True,
                "voltage_channel": "Main/VDC_RECT",
                "current_channel": "Main/IDC",
                "power_channel": "Main/PDC",
                "voltage_units": "kV",
                "current_units": "kA",
                "power_units": "MW",
                "max_abs": 1.0,
            }
        ]
    }

    result = evaluate_acceptance(samples, {}, contract)

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    check = result["physical_checks"][0]
    assert check["status"] == "invalid"
    assert check["outcome"] == "INCOMPLETE_ANALYSIS"
    assert any(
        error["reason"] == "inconsistent domains" and error["check"] == "pdc_product"
        for error in result["errors"]
    )


def test_physical_checks_pass_with_observed_and_derived_details():
    result = evaluate_acceptance(_physical_samples(), {}, _physical_contract())

    assert result["verdict"] == "PASS"
    checks = {check["name"]: check for check in result["physical_checks"]}
    assert checks["rectifier_dc_voltage"]["status"] == "observed"
    assert checks["rectifier_dc_voltage"]["observed"]["mean"] == pytest.approx(500.0)
    assert checks["pdc_product"]["status"] == "derived"
    assert checks["pdc_product"]["observed"]["derived_power_mean"] == pytest.approx(1000.0)
    assert checks["terminal_power_balance"]["status"] == "derived"
    assert checks["terminal_power_balance"]["observed"]["imbalance"] == pytest.approx(15.0)
    json.dumps(result)


def test_physical_required_bound_violation_fails():
    result = evaluate_acceptance(
        _physical_samples(**{"Main/ALPHA_RECT": [30.0, 30.0, 30.0, 30.0]}),
        {},
        _physical_contract(),
    )

    assert result["verdict"] == "FAIL"
    firing = next(check for check in result["physical_checks"] if check["name"] == "firing_angle")
    assert firing["outcome"] == "FAIL"
    assert firing["observed"]["mean"] == 30.0


def test_optional_missing_physical_check_does_not_block_pass():
    result = evaluate_acceptance(
        _physical_samples(**{"Main/MU_RECT": None}),
        {},
        _physical_contract(required=False),
    )

    assert result["verdict"] == "PASS"
    overlap = next(check for check in result["physical_checks"] if check["name"] == "overlap_angle")
    assert overlap["status"] == "missing"
    assert overlap["outcome"] == "INCOMPLETE_ANALYSIS"
    assert overlap["required"] is False


def test_malformed_contract_raises_backend_error():
    with pytest.raises(BackendError) as raised:
        evaluate_acceptance(_sample_payload(), _golden_payload(), {"golden": {"channels": "Main/VAC_RECT_A"}})

    assert raised.value.code == "LCC_ACCEPTANCE_INVALID"


def test_placeholder_golden_baseline_cannot_produce_acceptance_pass():
    asset_set = load_packaged_asset_set()

    result = evaluate_acceptance(asset_set.golden, asset_set.golden, asset_set.acceptance)

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["errors"][0]["reason"] == "unverified golden baseline"
