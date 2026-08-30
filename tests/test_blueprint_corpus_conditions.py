from __future__ import annotations

from decimal import Decimal

import pytest

from pscad_mcp.builders.blueprint.corpus_conditions import (
    ConditionUnresolved,
    evaluate_condition,
)


@pytest.mark.parametrize(
    ("expression", "instance", "defaults", "expected"),
    [
        ("true", {}, {}, True),
        ("false", {}, {}, False),
        ("View==0", {"View": "0"}, {}, True),
        ("!(DPath==1)", {"DPath": "0"}, {}, True),
        (
            "(Size==2) && ((Type==4)||(Type==6))",
            {"Size": "2", "Type": "6"},
            {},
            True,
        ),
        (
            "MeasV+MeasP+MeasQ==0",
            {"MeasV": "0", "MeasP": "0", "MeasQ": "0"},
            {},
            True,
        ),
        ("View==1", {}, {"View": 1}, True),
        ("View!=0", {"View": "1"}, {}, True),
        ("DPath", {"DPath": "2"}, {}, True),
        ("(DPath)&&(A)", {"DPath": "1", "A": "1"}, {}, True),
        ("INTR == 1", {"INTR": "1"}, {}, True),
        ("1+2>2 && 0 || 1", {}, {}, True),
        ("true==1", {}, {}, True),
        ("0.25+0.75==1", {}, {}, True),
        ("  View == 0  ", {"View": Decimal(0)}, {}, True),
    ],
)
def test_evaluate_condition_uses_closed_precedence(
    expression,
    instance,
    defaults,
    expected,
):
    assert evaluate_condition(expression, instance, defaults) is expected


@pytest.mark.parametrize(
    "expression",
    [
        "A-1",
        "A*2",
        "A/2",
        "func(A)",
        "A[0]",
        "A=1",
        "A<B",
        "A==1==true",
        "true+1",
        "true>0",
    ],
)
def test_evaluate_condition_rejects_syntax_or_types_outside_the_contract(
    expression,
):
    with pytest.raises(ConditionUnresolved):
        evaluate_condition(expression, {"A": "1", "B": "2"}, {})


@pytest.mark.parametrize(
    ("expression", "instance", "defaults"),
    [
        ("Missing==1", {}, {}),
        ("A==1", {"A": ("1", "2")}, {}),
        ("A>1", {"A": "nan"}, {}),
        ("A==1", {"A": "closed"}, {}),
        ("view==0", {"View": "0"}, {}),
    ],
)
def test_evaluate_condition_rejects_unresolved_identifier_values(
    expression,
    instance,
    defaults,
):
    with pytest.raises(ConditionUnresolved):
        evaluate_condition(expression, instance, defaults)


def test_evaluate_condition_short_circuits_unresolved_branches():
    assert evaluate_condition("true || Missing==1", {}, {}) is True
    assert evaluate_condition("false && Missing", {}, {}) is False


@pytest.mark.parametrize("expression", [None, "", "   "])
def test_empty_condition_is_active(expression):
    assert evaluate_condition(expression, {}, {}) is True
