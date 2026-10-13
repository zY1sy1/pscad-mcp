"""Independent analytic checks for time-windowed physical sweep metrics."""

import math

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.workflows.sweep.metrics import evaluate_metrics, validate_metric_specs


def traces(time=(0, 0.25, 1), voltage=(2, 2, 2), current=(0, 0.25, 1)):
    return {
        "channels": [
            {
                "path": "V",
                "units": "kV",
                "domain": list(time),
                "values": list(voltage),
                "total_samples": 3,
            },
            {
                "path": "I",
                "units": "kA",
                "domain": list(time),
                "values": list(current),
                "total_samples": 3,
            },
        ]
    }


def metric(kind="energy", **overrides):
    spec = {
        "name": "test",
        "kind": kind,
        "output_path": "case_01.out",
        "window": [0.1, 0.8],
    }
    if kind == "energy":
        spec.update(voltage_channel="V", current_channel="I", mode="signed", polarity=1)
    elif kind == "i2t":
        spec.update(current_channel="I")
    else:
        spec.update(channel="I")
    spec.update(overrides)
    return spec


def evaluate(spec, payload=None):
    return evaluate_metrics(payload or traces(), validate_metric_specs([spec]))[0]


def test_energy_and_i2t_integrate_irregular_linear_signals_with_clipped_window():
    energy = evaluate(metric())
    assert energy["value"] == pytest.approx((0.8**2 - 0.1**2) * 1e6)
    assert energy["units"] == "J"
    assert energy["window"] == [0.1, 0.8]
    assert energy["statistics_scope"] == "bounded_sample_piecewise_linear"
    assert energy["total_samples"] == 3
    i2t = evaluate(metric("i2t"))
    assert i2t["value"] == pytest.approx((0.8**3 - 0.1**3) / 3 * 1e6)
    assert i2t["units"] == "A^2 s"


def test_product_of_two_linear_signals_is_integrated_exactly():
    result = evaluate(metric(window=[0, 1]), traces(voltage=(0, 0.25, 1)))
    assert result["value"] == pytest.approx(1e6 / 3)


@pytest.mark.parametrize(
    "mode,expected", [("signed", 0), ("positive", 0.5e6), ("absolute", 1e6)]
)
def test_energy_direction_and_zero_crossings_preserve_signed_power(mode, expected):
    result = evaluate(
        metric(mode=mode, window=[0, 1]), traces(time=(0, 0.5, 1), current=(-1, 0, 1))
    )
    assert result["value"] == pytest.approx(expected, abs=1e-9)
    reverse = evaluate(
        metric(mode=mode, polarity=-1, window=[0, 1]),
        traces(time=(0, 0.5, 1), current=(-1, 0, 1)),
    )
    assert reverse["value"] == pytest.approx(
        -expected if mode == "signed" else expected, abs=1e-9
    )


def test_positive_energy_finds_both_signal_roots_inside_a_single_segment():
    payload = traces(time=(0, 1), voltage=(-1, 3), current=(-3, 1))
    # (4t-1)(4t-3) is positive on [0,1/4] and [3/4,1].
    positive = evaluate(metric(mode="positive", window=[0, 1]), payload)
    assert positive["value"] == pytest.approx(2e6 / 3)


def test_threshold_crossing_is_interpolated_and_missing_events_are_explicit():
    result = evaluate(metric("threshold_crossing", threshold=0.4, operator=">="))
    assert result["value"] == pytest.approx(0.4)
    assert result["units"] == "s"
    missing = evaluate(metric("threshold_crossing", threshold=2, operator=">="))
    assert missing["value"] is None and missing["status"] == "not_observed"
    assert missing["reason"] == "threshold_not_reached"
    active = evaluate(metric("threshold_crossing", threshold=0.01, operator=">="))
    assert active["value"] == pytest.approx(0.1)


def test_peak_uses_the_requested_window_instead_of_whole_record():
    result = evaluate(metric("peak_abs"), traces(current=(100, 0.25, 1)))
    assert result["value"] == pytest.approx(60.1)
    assert result["units"] == "kA"


@pytest.mark.parametrize("window", [[0.1, 0.5], [0.5, 1.1]])
def test_window_outside_available_evidence_is_not_extrapolated(window):
    with pytest.raises(BackendError) as error:
        evaluate(metric(window=window), traces(time=(0.2, 0.25, 1)))
    assert error.value.code == "SWEEP_METRIC_UNAVAILABLE"


def test_units_must_be_declared_and_cannot_override_conflicting_metadata():
    payload = traces()
    payload["channels"][0]["units"] = None
    with pytest.raises(BackendError) as error:
        evaluate(metric(), payload)
    assert error.value.code == "SWEEP_METRIC_UNAVAILABLE"
    result = evaluate(metric(voltage_units="kV"), payload)
    assert result["inputs"]["voltage"]["units_source"] == "request"
    with pytest.raises(BackendError):
        evaluate(metric(current_units="A"))


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "time", "nan", "bool", "single"]
)
def test_invalid_or_ambiguous_waveforms_never_yield_a_numeric_metric(mutation):
    payload = traces()
    if mutation == "missing":
        payload["channels"].pop()
    elif mutation == "duplicate":
        payload["channels"].append(payload["channels"][1])
    elif mutation == "time":
        payload["channels"][1]["domain"][1] = 0.3
    elif mutation in {"nan", "bool"}:
        payload["channels"][1]["values"][1] = math.nan if mutation == "nan" else True
    else:
        for channel in payload["channels"]:
            channel.update(domain=[0], values=[1])
    with pytest.raises(BackendError):
        evaluate(metric(), payload)


@pytest.mark.parametrize(
    "change",
    [
        {"window": [1, 0]},
        {"window": [0, math.inf]},
        {"window": [False, 1]},
        {"mode": "eval"},
        {"polarity": True},
        {"polarity": []},
        {"output_path": "../outside.out"},
        {"voltage_channel": "*"},
        {"name": "x", "expression": "V*I"},
    ],
)
def test_metric_requests_reject_invalid_windows_expressions_and_escaping_paths(change):
    with pytest.raises(BackendError) as error:
        validate_metric_specs([metric(**change)])
    assert error.value.code == "SWEEP_INVALID_ANALYSIS"


def test_metric_names_and_request_size_are_bounded():
    with pytest.raises(BackendError):
        validate_metric_specs([metric(), metric()])
    with pytest.raises(BackendError):
        validate_metric_specs([metric(name=f"m{i}") for i in range(33)])


def test_non_observed_metric_is_excluded_from_optimization():
    from pscad_mcp.workflows.sweep.analysis import rank

    report = {
        "scenarios": [
            {
                "name": "no_event",
                "state": "succeeded",
                "metrics": [{"name": "trip", "status": "not_observed", "value": None}],
            },
            {
                "name": "event",
                "state": "succeeded",
                "metrics": [{"name": "trip", "status": "available", "value": 0.4}],
            },
        ]
    }
    result = rank(report, objective={"metric": "trip", "direction": "minimize"})
    assert result["best"]["name"] == "event"
    assert result["excluded"] == [
        {"name": "no_event", "reason": "metric_unavailable", "metric": "trip"}
    ]
