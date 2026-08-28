from __future__ import annotations

import math

import pytest

from pscad_mcp.builders.blueprint.acceptance import evaluate_acceptance, evaluate_rule
from pscad_mcp.core.backend.base import BackendError


@pytest.mark.parametrize(
    ("kind", "arguments", "values", "domain", "passed"),
    [
        ("all_finite", {}, [1.0, 2.0], None, True),
        ("exact_value", {"value": 1}, [1, 1], None, True),
        ("exact_set", {"values": [0, 1]}, [1, 0, 1], None, True),
        ("minimum", {"minimum": 0.0}, [0.0, 2.0], None, True),
        ("maximum", {"maximum": 2.0}, [0.0, 2.0], None, True),
        ("inclusive_range", {"minimum": 0.0, "maximum": 2.0}, [0.0, 2.0], None, True),
        ("allowed_states", {"values": [0, 1]}, [0, 1, 1], None, True),
        ("transition_count", {"count": 2}, [0, 1, 0], None, True),
        ("transition_time", {"to": 1, "minimum": 0.09, "maximum": 0.11}, [0, 1, 1], [0.0, 0.1, 0.2], True),
        ("window_summary", {"window": [0.5, 1.0], "metric": "mean", "minimum": 2.0, "maximum": 3.0}, [1, 2, 3], [0, 1, 2], True),
        ("monotonic", {"direction": "increasing", "strict": False}, [1, 2, 2], None, True),
        ("monotonic", {"direction": "decreasing", "strict": True}, [3, 2, 2], None, False),
    ],
)
def test_evaluate_rule_supports_generic_rule_kinds(kind, arguments, values, domain, passed):
    result = evaluate_rule({"kind": kind, "arguments": arguments}, values, domain=domain)
    assert result["passed"] is passed
    assert result["kind"] == kind


@pytest.mark.parametrize(
    ("rule", "values"),
    [
        ({"kind": "all_finite", "arguments": {}}, [math.nan]),
        ({"kind": "unknown", "arguments": {}}, [1]),
        ({"kind": "transition_time", "arguments": {"to": 1, "minimum": 0, "maximum": 1}}, [0, 1]),
        ({"kind": "window_summary", "arguments": {"window": [0.9, 0.1], "metric": "mean"}}, [1, 2]),
    ],
)
def test_evaluate_rule_rejects_invalid_contracts(rule, values):
    with pytest.raises(BackendError) as raised:
        evaluate_rule(rule, values)
    assert raised.value.code == "BLUEPRINT_ACCEPTANCE_INVALID"


def acceptance_contract(*, source_class="model_observed", physical=False, units="kV"):
    return {
        "required_structure": [],
        "required_parameters": [],
        "blocking_messages": ["fatal"],
        "outputs": [{"channel": "Main/VDC", "units": units, "required": True}],
        "rules": [
            {
                "rule_id": "vdc-range",
                "kind": "inclusive_range",
                "channel": "Main/VDC",
                "required": True,
                "source_class": source_class,
                "physical": physical,
                "arguments": {"minimum": 400.0, "maximum": 600.0},
            }
        ],
    }


def dataset(*, units="kV", values=None):
    return {
        "channels": {
            "Main/VDC": {
                "path": "Main/VDC",
                "units": units,
                "domain": [0.0, 0.1],
                "values": values or [500.0, 510.0],
            }
        }
    }


def test_acceptance_exposes_independent_flags_and_rule_evidence():
    report = evaluate_acceptance(
        acceptance_contract(source_class="engineering_accepted", physical=True),
        dataset(),
        structure_acceptance=True,
        parameters_acceptance=True,
        messages_acceptance=True,
        trusted_source_classes={"engineering_accepted"},
    )

    assert report["structure_acceptance"] is True
    assert report["run_through_acceptance"] is True
    assert report["physical_acceptance"] is True
    assert report["rules"][0]["rule_id"] == "vdc-range"
    assert report["rules"][0]["observed"] == {"count": 2, "minimum": 500.0, "maximum": 510.0}


@pytest.mark.parametrize("source_class", ["model_observed", "provisional", "implementation_policy"])
def test_provisional_or_model_observed_thresholds_cannot_pass_physical_acceptance(source_class):
    report = evaluate_acceptance(
        acceptance_contract(source_class=source_class, physical=True),
        dataset(),
        trusted_source_classes={"engineering_accepted"},
    )
    assert report["run_through_acceptance"] is True
    assert report["physical_acceptance"] is False


def test_configured_trust_cannot_grant_physical_acceptance_to_provisional_rules():
    report = evaluate_acceptance(
        acceptance_contract(source_class="provisional", physical=True),
        dataset(),
        trusted_source_classes={"engineering_accepted", "provisional"},
    )

    assert report["run_through_acceptance"] is True
    assert report["physical_acceptance"] is False


@pytest.mark.parametrize("failure", ["missing", "units", "values", "structure", "messages"])
def test_required_output_and_lifecycle_failures_block_run_through(failure):
    evidence = dataset()
    contract = acceptance_contract()
    kwargs = {}
    if failure == "missing":
        evidence["channels"] = {}
    elif failure == "units":
        evidence["channels"]["Main/VDC"]["units"] = "V"
    elif failure == "values":
        evidence["channels"]["Main/VDC"]["values"] = [399.0]
    elif failure == "structure":
        kwargs["structure_acceptance"] = False
    else:
        kwargs["messages_acceptance"] = False

    report = evaluate_acceptance(contract, evidence, **kwargs)

    assert report["run_through_acceptance"] is False
    assert report["physical_acceptance"] is False
