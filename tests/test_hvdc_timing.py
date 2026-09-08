import asyncio

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.timing import dispatch_timed_events, select_timing_mode


class NativeTimingBackend:
    async def get_timed_control_capabilities(self, project_name):
        return {"native_schedule": True, "simulation_clock": True,
                "time_basis": "EMTDC", "time_units": "s", "verified": True}

    async def schedule_timed_controls(self, project_name, events):
        return [{"index": 0, "requested_time_s": 1.0, "observed_time_s": 1.0, "status": "registered"}]


class PollingTimingBackend:
    def __init__(self):
        self.times = iter([0.0, 0.4, 1.05, 1.05])
        self.writes = []

    async def get_timed_control_capabilities(self, project_name):
        return {"native_schedule": False, "simulation_clock": True,
                "time_basis": "EMTDC", "time_units": "s", "verified": True,
                "max_timing_error_s": 0.1}

    async def get_simulation_time(self, project_name):
        return next(self.times)

    async def set_component_parameters(self, project_name, component_id, values):
        self.writes.append((project_name, component_id, values))

    async def get_component_parameters(self, project_name, component_id):
        return self.writes[-1][2]


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
    class Stalled(PollingTimingBackend):
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


@pytest.mark.parametrize("capabilities", [
    {"native_schedule": True},
    {"simulation_clock": True, "time_basis": "wall_clock", "verified": True},
    {"simulation_clock": True, "time_basis": "EMTDC", "verified": False},
])
def test_unproven_clock_is_rejected(capabilities):
    class Backend:
        async def get_timed_control_capabilities(self, project_name):
            return capabilities

    with pytest.raises(BackendError):
        asyncio.run(select_timing_mode(Backend(), "case"))


@pytest.mark.parametrize("override", [
    {"time_s": -1}, {"time_s": float("nan")}, {"time_s": float("inf")},
    {"end_time_s": 0.5}, {"value": float("nan")},
])
def test_invalid_events_are_rejected_before_native_registration(override):
    class Backend:
        called = False

        async def schedule_timed_controls(self, project, events):
            self.called = True
            return [dict(item) for item in events]

    backend = Backend()
    event = {"event_id": "e1", "time_s": 1.0, "component_id": 17,
             "parameter_name": "Value", "value": 1, **override}
    with pytest.raises(BackendError):
        asyncio.run(dispatch_timed_events(backend, "case", [event], mode="native"))
    assert backend.called is False


@pytest.mark.parametrize("override", [
    {"event_id": "different"}, {"component_id": 18},
    {"parameter_name": "Other"}, {"value": 0},
])
def test_native_ack_identity_must_match_not_only_count(override):
    event = {"event_id": "e1", "time_s": 1.0, "component_id": 17,
             "parameter_name": "Value", "value": 1}

    class Backend:
        async def schedule_timed_controls(self, project, events):
            return [{**event, **override, "status": "registered"}]

    with pytest.raises(BackendError):
        asyncio.run(dispatch_timed_events(Backend(), "case", [event], mode="native"))


def test_polling_intervals_fail_before_the_first_write():
    backend = PollingTimingBackend()
    with pytest.raises(BackendError, match="point events"):
        asyncio.run(dispatch_timed_events(backend, "case", [{"time_s": 1.0, "end_time_s": 2.0,
            "component_id": 17, "parameter_name": "Value", "value": 1, "after_value": 0}], mode="simulation_clock_polling"))
    assert backend.writes == []


def test_polling_checks_write_completion_time_against_fixed_bound():
    backend = PollingTimingBackend()
    backend.times = iter([1.0, 1.2])
    with pytest.raises(BackendError, match="timing error"):
        asyncio.run(dispatch_timed_events(backend, "case", [{"time_s": 1.0,
            "component_id": 17, "parameter_name": "Value", "value": 1}], mode="simulation_clock_polling"))


def test_native_interval_ack_checks_restoration_value():
    event = {"event_id": "interval", "time_s": 1.0, "end_time_s": 2.0,
             "component_id": 17, "parameter_name": "Value", "value": 1,
             "before_value": 0, "after_value": 0}

    class Backend:
        async def schedule_timed_controls(self, project, events):
            return [{**event, "after_value": 2}]

    with pytest.raises(BackendError, match="differs"):
        asyncio.run(dispatch_timed_events(Backend(), "case", [event], mode="native"))
