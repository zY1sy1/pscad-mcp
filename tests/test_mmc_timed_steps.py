"""Sustained EMTDC steps must retain their values and expose real transitions."""

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc import timed_control
from tests.test_mmc_timed_control import _inputs


def _step_plan(tmp_path, *, reversal=False, unchanged=False):
    source, master, event = _inputs(tmp_path)
    event.update(event_shape="step", end_time_s=0.05, after_value=1)
    events = [event]
    if unchanged:
        event.update(value=0, after_value=0)
    if reversal:
        event["end_time_s"] = 0.035
        events.append(
            {
                **event,
                "event_id": "reverse",
                "time_s": 0.035,
                "end_time_s": 0.05,
                "before_value": 1,
                "value": -1,
                "after_value": -1,
            }
        )
    plan = timed_control.plan_embedded_control(
        source,
        events,
        master_path=master,
        time_step_s=1e-5,
        output_step_s=1e-5,
        duration_s=0.05,
        max_timing_error_s=2e-5,
    )
    times = [i * 1e-5 for i in range(5001)]
    values = [0 if t < 0.02 else 1 if not reversal or t < 0.035 else -1 for t in times]
    if unchanged:
        values = [0 for _ in times]
    channel = {
        "description": plan["event_channels"][0]["description"],
        "units": "1",
        "time": times,
        "values": values,
    }
    return plan, {"channels": [channel]}


def test_sustained_step_is_verified_without_an_unrequested_falling_edge(tmp_path):
    plan, samples = _step_plan(tmp_path)
    measurements = timed_control.measure_event_waveforms(plan, samples)
    assert len(measurements) == 1
    assert measurements[0]["rise_time_s"] == pytest.approx(0.02)
    assert measurements[0]["fall_time_s"] is None
    assert measurements[0]["event_shape"] == "step"


def test_reversal_checks_both_sustained_step_edges(tmp_path):
    plan, samples = _step_plan(tmp_path, reversal=True)
    measurements = timed_control.measure_event_waveforms(plan, samples)
    assert [m["rise_time_s"] for m in measurements] == pytest.approx([0.02, 0.035])
    samples["channels"][0]["values"][-1] = 0
    with pytest.raises(BackendError):
        timed_control.measure_event_waveforms(plan, samples)


def test_unchanged_setpoint_is_reported_as_unobservable_timing(tmp_path):
    plan, samples = _step_plan(tmp_path, unchanged=True)
    measurement = timed_control.measure_event_waveforms(plan, samples)[0]
    assert measurement["timing_measurement_applicable"] is False
    assert measurement["rise_time_s"] is None
    samples["channels"][0]["values"][2500] = 1
    with pytest.raises(BackendError):
        timed_control.measure_event_waveforms(plan, samples)
