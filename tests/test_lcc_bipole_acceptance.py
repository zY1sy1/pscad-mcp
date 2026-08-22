import hashlib
import json
import math

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.acceptance import evaluate_acceptance


TIME = [0.8, 0.9, 1.0]
CONVENTION = "rectifier_input_positive_inverter_output_positive"
COMPARISON_POLICY = {
    "kind": "max_ulps",
    "max_ulps": 16,
    "rel_tol": 0.0,
    "abs_tol": 0.0,
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
        "direction_convention": CONVENTION,
    }
    check.update(overrides)
    return {"physical_checks": [check]}


def _threshold_digest(check):
    threshold_contract = {
        "name": check["name"].strip(),
        "kind": check["kind"],
        "required": check.get("required", True),
        "window": [float(value) for value in check["window"]] if check.get("window") is not None else None,
        "direction_convention": check["direction_convention"],
        "rectifier_power_channel": check["rectifier_power_channel"],
        "inverter_power_channel": check["inverter_power_channel"],
        "units": check["units"],
        "max_loss": float(check["max_loss"]) if check.get("max_loss") is not None else None,
        "max_percent": float(check["max_percent"]) if check.get("max_percent") is not None else None,
        "comparison_policy": COMPARISON_POLICY,
    }
    encoded = json.dumps(
        threshold_contract,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _approved_source(check):
    return {
        "kind": "reviewed_acceptance_limit",
        "artifact_sha256": "a" * 64,
        "locator": "HVDC_Bipolar_1000MW_500kV acceptance review, terminal loss",
        "review_id": "LCC-ACCEPT-001",
        "review_status": "approved",
        "threshold_contract_sha256": _threshold_digest(check),
    }


def _trusted_registry(source):
    return {source["review_id"]: dict(source)}


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
    samples = {
        "time": TIME,
        "channels": {"Main/IDC": _channel([1.0, 1.0, 1.0], "pu")},
    }
    contract = {
        "physical_checks": [
            {
                "name": "dc_current_pu",
                "kind": "dc_magnitude_polarity",
                "channel": "Main/IDC",
                "units": "pu",
                "min": 1.0,
                "max": 1.0,
            }
        ]
    }
    result = evaluate_acceptance(
        samples,
        {},
        contract,
    )

    assert result["verdict"] == "PASS"
    assert result["physical_checks"][0]["observed"]["units"] == "pu"


@pytest.mark.parametrize("units", ["pu", "kV", "kA"])
def test_terminal_power_loss_rejects_non_power_dimensions(units):
    result = evaluate_acceptance(
        _real_style_samples(power_units=units),
        {},
        _loss_contract(units=units),
    )

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["errors"][0]["reason"] == "unit mismatch"


@pytest.mark.parametrize("requested_units", ["kV", "kA"])
def test_per_unit_values_cannot_convert_to_physical_units_without_base(requested_units):
    samples = {
        "time": TIME,
        "channels": {"Main/PU": _channel([1.0, 1.0, 1.0], "pu")},
    }
    contract = {
        "physical_checks": [
            {
                "name": "pu_without_base",
                "kind": "dc_magnitude_polarity",
                "channel": "Main/PU",
                "units": requested_units,
            }
        ]
    }
    result = evaluate_acceptance(
        samples,
        {},
        contract,
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
        "direction_convention": CONVENTION
    }


@pytest.mark.parametrize("threshold", [{"max_loss": 60.0}, {"max_percent": 5.0}])
def test_terminal_power_loss_threshold_without_approved_source_is_incomplete(threshold):
    result = evaluate_acceptance(_real_style_samples(), {}, _loss_contract(**threshold))

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    check = result["physical_checks"][0]
    assert check["outcome"] == "INCOMPLETE_ANALYSIS"
    assert check["comparison_policy"] == COMPARISON_POLICY
    assert result["errors"][0]["reason"] == "missing approved threshold source"
    json.dumps(result)


def test_terminal_power_loss_threshold_with_approved_source_is_enforced():
    contract = _loss_contract(max_loss=51.0, max_percent=5.0)
    source = _approved_source(contract["physical_checks"][0])
    contract["physical_checks"][0]["approved_source"] = source
    trusted = _trusted_registry(source)
    trusted_before = json.loads(json.dumps(trusted))
    result = evaluate_acceptance(
        _real_style_samples(),
        {},
        contract,
        trusted_threshold_sources=trusted,
    )

    assert result["verdict"] == "PASS"
    assert result["physical_checks"][0]["expected"]["approved_source"] == source
    assert result["physical_checks"][0]["comparison_policy"] == COMPARISON_POLICY
    assert trusted == trusted_before


@pytest.mark.parametrize(
    ("rectifier", "inverter", "threshold", "expected_verdict"),
    [
        (1028.7, 977.9, 50.8, "PASS"),
        (1.3, 1.0, 0.3, "PASS"),
        (1.30000000000001, 1.0, 0.3, "FAIL"),
    ],
)
def test_terminal_power_loss_uses_fixed_ulp_boundary_policy(rectifier, inverter, threshold, expected_verdict):
    samples = _real_style_samples()
    samples["channels"]["Main/PR"]["values"] = [rectifier] * len(TIME)
    samples["channels"]["Main/PI"]["values"] = [inverter] * len(TIME)
    contract = _loss_contract(max_loss=threshold)
    source = _approved_source(contract["physical_checks"][0])
    contract["physical_checks"][0]["approved_source"] = source

    result = evaluate_acceptance(
        samples,
        {},
        contract,
        trusted_threshold_sources=_trusted_registry(source),
    )

    assert result["verdict"] == expected_verdict
    assert result["physical_checks"][0]["comparison_policy"] == COMPARISON_POLICY


def test_terminal_power_loss_overflow_is_incomplete_and_strict_json_safe():
    samples = _real_style_samples()
    samples["channels"]["Main/PR"] = _channel([1e308, 1e308, 1e308], "MW")
    samples["channels"]["Main/PI"] = _channel([1e308, 1e308, 1e308], "MW")

    result = evaluate_acceptance(samples, {}, _loss_contract())

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["errors"][0]["reason"] == "non-finite derived value"
    json.dumps(result, allow_nan=False)


def test_terminal_power_loss_unit_conversion_overflow_is_incomplete_and_json_safe():
    samples = _real_style_samples(power_units="MW")
    samples["channels"]["Main/PR"]["values"] = [1e308] * len(TIME)
    samples["channels"]["Main/PI"]["values"] = [1e307] * len(TIME)

    result = evaluate_acceptance(samples, {}, _loss_contract(units="W"))

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["errors"][0]["reason"] == "non-finite derived value"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("threshold", [{"max_loss": 50.0}, {"max_percent": 4.9}])
def test_terminal_power_loss_approved_threshold_violation_fails(threshold):
    contract = _loss_contract(**threshold)
    source = _approved_source(contract["physical_checks"][0])
    contract["physical_checks"][0]["approved_source"] = source
    result = evaluate_acceptance(
        _real_style_samples(),
        {},
        contract,
        trusted_threshold_sources=_trusted_registry(source),
    )

    assert result["verdict"] == "FAIL"
    assert result["physical_checks"][0]["outcome"] == "FAIL"


@pytest.mark.parametrize("field", ["artifact_sha256", "locator", "review_status"])
def test_terminal_power_loss_rejects_tampered_or_unapproved_source(field):
    contract = _loss_contract(max_loss=60.0)
    source = _approved_source(contract["physical_checks"][0])
    trusted = _trusted_registry(source)
    tampered_source = dict(source)
    tampered_source[field] = {
        "artifact_sha256": "b" * 64,
        "locator": "tampered locator",
        "review_status": "draft",
    }[field]
    contract["physical_checks"][0]["approved_source"] = tampered_source

    with pytest.raises(BackendError) as raised:
        evaluate_acceptance(
            _real_style_samples(),
            {},
            contract,
            trusted_threshold_sources=trusted,
        )

    assert raised.value.code == "LCC_ACCEPTANCE_INVALID"
    json.dumps(raised.value.details)


def test_terminal_power_loss_rejects_threshold_tamper_against_approved_digest():
    approved_contract = _loss_contract(max_loss=51.0)
    source = _approved_source(approved_contract["physical_checks"][0])
    tampered_contract = _loss_contract(max_loss=60.0, approved_source=source)

    with pytest.raises(BackendError) as raised:
        evaluate_acceptance(
            _real_style_samples(),
            {},
            tampered_contract,
            trusted_threshold_sources=_trusted_registry(source),
        )

    assert raised.value.code == "LCC_ACCEPTANCE_INVALID"
    assert raised.value.details["field"] == "approved_source.threshold_contract_sha256"


@pytest.mark.parametrize(
    ("field", "tampered_value"),
    [
        ("name", "renamed_terminal_loss"),
        ("required", False),
        ("window", [0.8, 0.9]),
        ("direction_convention", "opposite_signs"),
        ("rectifier_power_channel", "Main/OTHER_PR"),
        ("inverter_power_channel", "Main/OTHER_PI"),
        ("units", "kW"),
        ("max_percent", 4.0),
    ],
)
def test_every_terminal_loss_judgement_field_is_bound_to_approval(field, tampered_value):
    approved_contract = _loss_contract(max_loss=60.0, window=[0.8, 1.0])
    source = _approved_source(approved_contract["physical_checks"][0])
    tampered_contract = json.loads(json.dumps(approved_contract))
    tampered_contract["physical_checks"][0]["approved_source"] = source
    tampered_contract["physical_checks"][0][field] = tampered_value

    with pytest.raises(BackendError) as raised:
        evaluate_acceptance(
            _real_style_samples(),
            {},
            tampered_contract,
            trusted_threshold_sources=_trusted_registry(source),
        )

    assert raised.value.code == "LCC_ACCEPTANCE_INVALID"
    expected_field = "direction_convention" if field == "direction_convention" else "approved_source.threshold_contract_sha256"
    assert raised.value.details["field"] == expected_field


def test_terminal_power_loss_rejects_unknown_future_judgement_field():
    contract = _loss_contract(aggregation="mean")

    with pytest.raises(BackendError) as raised:
        evaluate_acceptance(_real_style_samples(), {}, contract)

    assert raised.value.code == "LCC_ACCEPTANCE_INVALID"
    assert raised.value.details["field"] == "physical terminal loss check"


def test_arbitrary_well_formed_hash_cannot_pass_without_trusted_registry():
    contract = _loss_contract(max_loss=60.0)
    source = _approved_source(contract["physical_checks"][0])
    source["artifact_sha256"] = "f" * 64
    contract["physical_checks"][0]["approved_source"] = source

    result = evaluate_acceptance(_real_style_samples(), {}, contract)

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["errors"][0]["reason"] == "missing trusted threshold source registry"
    assert "approved_source" not in result["physical_checks"][0].get("expected", {})


def test_untrusted_100k_source_text_is_not_echoed_without_registry():
    huge = "x" * 100_000
    contract = _loss_contract(
        max_loss=60.0,
        approved_source={
            "kind": huge,
            "artifact_sha256": "a" * 64,
            "locator": huge,
            "review_id": huge,
            "review_status": "approved",
            "threshold_contract_sha256": "b" * 64,
        },
    )

    result = evaluate_acceptance(_real_style_samples(), {}, contract)
    serialized = json.dumps(result)

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert huge not in serialized
    assert len(serialized) < 20_000


def test_no_threshold_does_not_echo_arbitrary_approved_source():
    huge = "x" * 100_000
    contract = _loss_contract(approved_source={"untrusted": huge})

    result = evaluate_acceptance(_real_style_samples(), {}, contract)
    serialized = json.dumps(result)

    assert result["verdict"] == "PASS"
    assert "approved_source" not in result["physical_checks"][0].get("expected", {})
    assert huge not in serialized


def test_positive_direction_convention_rejects_negative_inverter_power():
    samples = _real_style_samples()
    samples["channels"]["Main/PI"]["values"] = [-977.9] * len(TIME)

    result = evaluate_acceptance(samples, {}, _loss_contract())

    assert result["verdict"] == "FAIL"
    assert result["physical_checks"][0]["observed"]["inverter_power_mean"] < 0.0


def test_terminal_power_loss_fails_when_power_flow_invariant_is_violated():
    samples = _real_style_samples()
    samples["channels"]["Main/PI"]["values"] = [1030.0] * len(TIME)

    result = evaluate_acceptance(samples, {}, _loss_contract())

    assert result["verdict"] == "FAIL"
    assert result["physical_checks"][0]["observed"]["loss"] < 0.0


def test_terminal_power_order_uses_original_operand_scale_for_cancellation():
    samples = _real_style_samples()
    samples["channels"]["Main/PR"]["values"] = [0.3] * len(TIME)
    samples["channels"]["Main/PI"]["values"] = [0.1 + 0.2] * len(TIME)

    result = evaluate_acceptance(samples, {}, _loss_contract())

    assert result["verdict"] == "PASS"
    assert result["physical_checks"][0]["observed"]["loss"] < 0.0


def test_terminal_power_order_rejects_more_than_policy_ulps_on_original_scale():
    inverter = 0.3
    for _ in range(COMPARISON_POLICY["max_ulps"] + 1):
        inverter = math.nextafter(inverter, math.inf)
    samples = _real_style_samples()
    samples["channels"]["Main/PR"]["values"] = [0.3] * len(TIME)
    samples["channels"]["Main/PI"]["values"] = [inverter] * len(TIME)

    result = evaluate_acceptance(samples, {}, _loss_contract())

    assert result["verdict"] == "FAIL"


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
