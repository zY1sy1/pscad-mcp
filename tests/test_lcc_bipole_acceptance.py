import json

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.acceptance import evaluate_acceptance


TIME = [0.8, 0.9, 1.0]
APPROVED_SOURCE = {
    "kind": "reviewed_acceptance_limit",
    "artifact_sha256": "a" * 64,
    "locator": "HVDC_Bipolar_1000MW_500kV acceptance review, terminal loss",
    "review_id": "LCC-ACCEPT-001",
    "review_status": "approved",
}


def _channel(values, units):
    return {"values": values, "units": units}


def _loss_contract(**overrides):
    check = {
        "name": "terminal_loss",
        "kind": "terminal_power_loss",
        "required": True,
        "rectifier_power_channel": "Main/PR",
        "inverter_power_channel": "Main/PI",
        "units": "MW",
        "direction_convention": "rectifier_input_positive_inverter_output_positive",
    }
    check.update(overrides)
    return {"physical_checks": [check]}


def _real_style_samples(*, gamma_units="deg", power_units="MW"):
    channels = {
        f"Main/UNUSED_{index:02d}": _channel([float(index)] * len(TIME), " " if index % 2 else "")
        for index in range(46)
    }
    channels.update(
        {
            "Main/PR": _channel([1028.7] * len(TIME), power_units),
            "Main/PI": _channel([977.9] * len(TIME), power_units),
            "Main/GAMMA": _channel([18.0, 18.1, 17.9], gamma_units),
        }
    )
    assert len(channels) == 49
    return {"time": TIME, "channels": channels}


def test_real_style_49_channels_ignore_blank_units_on_unreferenced_channels():
    result = evaluate_acceptance(_real_style_samples(), {}, _loss_contract())

    assert result["verdict"] == "PASS"
    check = result["physical_checks"][0]
    assert check["status"] == "derived"
    assert check["observed"]["rectifier_power_mean"] == pytest.approx(1028.7)
    assert check["observed"]["inverter_power_mean"] == pytest.approx(977.9)
    assert check["observed"]["loss"] == pytest.approx(50.8)
    assert check["observed"]["loss_percent"] == pytest.approx(50.8 / 1028.7 * 100.0)
    json.dumps(result)


def test_referenced_gamma_with_blank_units_is_incomplete():
    contract = {
        "physical_checks": [
            {
                "name": "gamma",
                "kind": "angle_interval",
                "required": True,
                "channel": "Main/GAMMA",
                "units": "deg",
                "min": 15.0,
                "max": 25.0,
            }
        ]
    }

    result = evaluate_acceptance(_real_style_samples(gamma_units="  "), {}, contract)

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["physical_checks"][0]["status"] == "invalid"
    assert result["errors"][0]["reason"] == "unit mismatch"
    assert result["errors"][0]["channel"] == "Main/GAMMA"
    json.dumps(result)


def test_per_unit_values_support_same_unit_conversion():
    result = evaluate_acceptance(
        _real_style_samples(power_units="pu"),
        {},
        _loss_contract(units="pu"),
    )

    assert result["verdict"] == "PASS"
    assert result["physical_checks"][0]["observed"]["units"] == "pu"


@pytest.mark.parametrize("requested_units", ["kV", "kA"])
def test_per_unit_values_cannot_convert_to_physical_units_without_base(requested_units):
    result = evaluate_acceptance(
        _real_style_samples(power_units="pu"),
        {},
        _loss_contract(units=requested_units),
    )

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["errors"][0]["reason"] == "unit mismatch"
    assert result["errors"][0]["observed_units"] == "pu"
    assert result["errors"][0]["expected_units"] == requested_units


def test_terminal_power_loss_requires_explicit_direction_convention():
    contract = _loss_contract()
    del contract["physical_checks"][0]["direction_convention"]

    with pytest.raises(BackendError) as raised:
        evaluate_acceptance(_real_style_samples(), {}, contract)

    assert raised.value.code == "LCC_ACCEPTANCE_INVALID"


def test_terminal_power_loss_invariant_passes_without_numeric_threshold():
    result = evaluate_acceptance(_real_style_samples(), {}, _loss_contract())

    assert result["verdict"] == "PASS"
    assert result["physical_checks"][0]["expected"] == {
        "direction_convention": "rectifier_input_positive_inverter_output_positive"
    }


@pytest.mark.parametrize("threshold", [{"max_loss": 60.0}, {"max_percent": 5.0}])
def test_terminal_power_loss_threshold_without_approved_source_is_incomplete(threshold):
    result = evaluate_acceptance(_real_style_samples(), {}, _loss_contract(**threshold))

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    check = result["physical_checks"][0]
    assert check["outcome"] == "INCOMPLETE_ANALYSIS"
    assert result["errors"][0]["reason"] == "missing approved threshold source"
    json.dumps(result)


def test_terminal_power_loss_threshold_with_approved_source_is_enforced():
    result = evaluate_acceptance(
        _real_style_samples(),
        {},
        _loss_contract(max_loss=51.0, max_percent=5.0, approved_source=APPROVED_SOURCE),
    )

    assert result["verdict"] == "PASS"
    assert result["physical_checks"][0]["expected"]["approved_source"] == APPROVED_SOURCE


@pytest.mark.parametrize("threshold", [{"max_loss": 50.0}, {"max_percent": 4.9}])
def test_terminal_power_loss_approved_threshold_violation_fails(threshold):
    result = evaluate_acceptance(
        _real_style_samples(),
        {},
        _loss_contract(**threshold, approved_source=APPROVED_SOURCE),
    )

    assert result["verdict"] == "FAIL"
    assert result["physical_checks"][0]["outcome"] == "FAIL"


@pytest.mark.parametrize(
    "tampered_source",
    [
        {**APPROVED_SOURCE, "artifact_sha256": "not-a-sha256"},
        {**APPROVED_SOURCE, "review_status": "draft"},
        {key: value for key, value in APPROVED_SOURCE.items() if key != "review_id"},
    ],
)
def test_terminal_power_loss_rejects_tampered_or_unapproved_source(tampered_source):
    with pytest.raises(BackendError) as raised:
        evaluate_acceptance(
            _real_style_samples(),
            {},
            _loss_contract(max_loss=60.0, approved_source=tampered_source),
        )

    assert raised.value.code == "LCC_ACCEPTANCE_INVALID"
    json.dumps(raised.value.details)


def test_terminal_power_loss_fails_when_power_flow_invariant_is_violated():
    samples = _real_style_samples()
    samples["channels"]["Main/PI"]["values"] = [1030.0] * len(TIME)

    result = evaluate_acceptance(samples, {}, _loss_contract())

    assert result["verdict"] == "FAIL"
    assert result["physical_checks"][0]["observed"]["loss"] < 0.0


def test_legacy_terminal_power_balance_retains_opposite_sign_semantics():
    samples = _real_style_samples()
    samples["channels"]["Main/PI"]["values"] = [-977.9] * len(TIME)
    contract = {
        "physical_checks": [
            {
                "name": "legacy_balance",
                "kind": "terminal_power_balance",
                "rectifier_power_channel": "Main/PR",
                "inverter_power_channel": "Main/PI",
                "units": "MW",
                "loss_allowance": 51.0,
            }
        ]
    }

    result = evaluate_acceptance(samples, {}, contract)

    assert result["verdict"] == "PASS"
    assert result["physical_checks"][0]["observed"]["imbalance"] == pytest.approx(50.8)
