import asyncio

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.timing import dispatch_timed_events, select_timing_mode


class NativeTimingBackend:
    async def get_timed_control_capabilities(self, project_name):
        return {"native_schedule": True, "simulation_clock": True}

    async def schedule_timed_controls(self, project_name, events):
        return [{"index": 0, "requested_time_s": 1.0, "observed_time_s": 1.0, "status": "registered"}]


class PollingTimingBackend:
    def __init__(self):
        self.times = iter([0.0, 0.4, 1.05])
        self.writes = []

    async def get_timed_control_capabilities(self, project_name):
        return {"native_schedule": False, "simulation_clock": True}

    async def get_simulation_time(self, project_name):
        return next(self.times)

    async def set_component_parameters(self, project_name, component_id, values):
        self.writes.append((project_name, component_id, values))


def test_native_timing_is_preferred():
    assert asyncio.run(select_timing_mode(NativeTimingBackend(), "case")) == "native"


def test_polling_dispatch_uses_reported_simulation_time(monkeypatch):
    backend = PollingTimingBackend()
    delays = []

    async def no_delay(_seconds):
        delays.append(_seconds)

    monkeypatch.setattr(asyncio, "sleep", no_delay)
    result = asyncio.run(dispatch_timed_events(backend, "case", [{
        "time_s": 1.0,
        "event_id": "event-0",
        "component_id": "17",
        "parameter_name": "Value",
        "value": 1,
    }], mode="simulation_clock_polling"))

    assert backend.writes == [("case", 17, {"Value": 1})]
    assert result[0]["requested_time_s"] == 1.0
    assert result[0]["observed_time_s"] == 1.05
    assert result[0]["timing_error_s"] == pytest.approx(0.05)
    assert result[0]["event_id"] == "event-0"
    assert delays and all(delay > 0 for delay in delays)


def test_polling_rejects_a_stalled_simulation_clock(monkeypatch):
    class Stalled:
        def __init__(self):
            self.calls = 0

        async def get_simulation_time(self, project_name):
            self.calls += 1
            return 0.0

    backend = Stalled()

    async def no_delay(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_delay)
    with pytest.raises(BackendError) as raised:
        asyncio.run(dispatch_timed_events(
            backend,
            "case",
            [{"time_s": 1.0, "component_id": 1, "parameter_name": "Value", "value": 1}],
            mode="simulation_clock_polling",
            liveness_deadline_s=0.01,
            max_stalled_polls=2,
        ))
    assert raised.value.code == "HVDC_TIMED_CONTROL_UNAVAILABLE"


def test_duplicate_event_ids_are_rejected_before_dispatch():
    class Backend:
        async def get_simulation_time(self, project_name):
            return 1.0

    with pytest.raises(BackendError) as raised:
        asyncio.run(dispatch_timed_events(
            Backend(),
            "case",
            [
                {"event_id": "same", "time_s": 0.0, "component_id": 1, "parameter_name": "Value", "value": 1},
                {"event_id": "same", "time_s": 0.1, "component_id": 1, "parameter_name": "Value", "value": 0},
            ],
            mode="simulation_clock_polling",
        ))
    assert raised.value.code == "HVDC_TIMED_CONTROL_UNAVAILABLE"


def test_missing_strict_timing_capability_is_rejected():
    class Unsupported:
        async def get_timed_control_capabilities(self, project_name):
            return {"native_schedule": False, "simulation_clock": False}

    with pytest.raises(BackendError) as raised:
        asyncio.run(select_timing_mode(Unsupported(), "case"))
    assert raised.value.code == "HVDC_TIMED_CONTROL_UNAVAILABLE"
