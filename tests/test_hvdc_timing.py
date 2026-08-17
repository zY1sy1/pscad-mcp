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

    async def no_delay(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_delay)
    result = asyncio.run(dispatch_timed_events(backend, "case", [{
        "time_s": 1.0,
        "component_id": "17",
        "parameter_name": "Value",
        "value": 1,
    }], mode="simulation_clock_polling"))

    assert backend.writes == [("case", 17, {"Value": 1})]
    assert result[0]["requested_time_s"] == 1.0
    assert result[0]["observed_time_s"] == 1.05
    assert result[0]["timing_error_s"] == pytest.approx(0.05)


def test_missing_strict_timing_capability_is_rejected():
    class Unsupported:
        async def get_timed_control_capabilities(self, project_name):
            return {"native_schedule": False, "simulation_clock": False}

    with pytest.raises(BackendError) as raised:
        asyncio.run(select_timing_mode(Unsupported(), "case"))
    assert raised.value.code == "HVDC_TIMED_CONTROL_UNAVAILABLE"
