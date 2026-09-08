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
    class Backend(NativeTimingBackend):
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

    class Backend(NativeTimingBackend):
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

    class Backend(NativeTimingBackend):
        async def schedule_timed_controls(self, project, events):
            return [{**event, "after_value": 2}]

    with pytest.raises(BackendError, match="differs"):
        asyncio.run(dispatch_timed_events(Backend(), "case", [event], mode="native"))


def test_native_provider_cannot_rewrite_the_contract_or_callers_request():
    event = {"event_id": "e1", "time_s": 1.0, "component_id": 17,
             "parameter_name": "Value", "value": 1,
             "target": {"instance_path": "Main", "owner": "17", "parameter": "Value"}}

    class Backend(NativeTimingBackend):
        async def schedule_timed_controls(self, project, events):
            events[0]["value"] = 999
            events[0]["target"]["owner"] = "999"
            return events

    with pytest.raises(BackendError, match="differs"):
        asyncio.run(dispatch_timed_events(Backend(), "case", [event], mode="native"))
    assert event["value"] == 1
    assert event["target"]["owner"] == "17"


def test_direct_native_dispatch_requires_verified_capabilities():
    class Backend(NativeTimingBackend):
        def __init__(self):
            self.calls = []

        async def get_timed_control_capabilities(self, project_name):
            return {"native_schedule": True, "time_basis": "wall_clock"}

        async def schedule_timed_controls(self, project_name, events):
            self.calls.append(events)
            return events

    backend = Backend()
    with pytest.raises(BackendError):
        asyncio.run(dispatch_timed_events(backend, "case", [{"event_id": "a", "time_s": 1,
            "component_id": 17, "parameter_name": "Value", "value": 1}], mode="native"))
    assert backend.calls == []


def test_missing_event_value_fails_before_any_native_registration():
    class Backend(NativeTimingBackend):
        def __init__(self):
            self.calls = []

        async def schedule_timed_controls(self, project_name, events):
            self.calls.append(events)
            return events

    backend = Backend()
    with pytest.raises(BackendError):
        asyncio.run(dispatch_timed_events(backend, "case", [{"event_id": "a", "time_s": 1,
            "component_id": 17, "parameter_name": "Value"}], mode="native"))
    assert backend.calls == []


def test_conflicting_flat_and_nested_target_fails_before_any_write():
    backend = PollingTimingBackend()
    events = [{"time_s": 0.4, "component_id": 17, "parameter_name": "Value", "value": 1},
              {"time_s": 1.0, "component_id": 18, "parameter_name": "Value", "value": 0,
               "target": {"instance_path": "Main", "owner": "17", "parameter": "Value"}}]
    with pytest.raises(BackendError):
        asyncio.run(dispatch_timed_events(backend, "case", events, mode="simulation_clock_polling"))
    assert backend.writes == []


def test_polling_normalizes_nested_only_binding_before_execution():
    backend = PollingTimingBackend()
    result = asyncio.run(dispatch_timed_events(backend, "case", [{"time_s": 1,
        "target": {"instance_path": "Main", "owner": "17", "parameter": "Value"},
        "value": 1}], mode="simulation_clock_polling"))
    assert backend.writes == [("case", 17, {"Value": 1})]
    assert result[0]["timing_error_s"] == pytest.approx(0.05)


def test_mixed_target_forms_cannot_dispatch_two_values_at_the_same_time():
    backend = PollingTimingBackend()
    backend.times = iter([1.05, 1.05, 1.05])
    events = [{"time_s": 1.0, "component_id": 17, "parameter_name": "Value", "value": 1},
              {"time_s": 1.0, "target": {"instance_path": "Main", "owner": "17", "parameter": "Value"}, "value": 0}]
    with pytest.raises(BackendError, match="conflict"):
        asyncio.run(dispatch_timed_events(backend, "case", events, mode="simulation_clock_polling"))
    assert backend.writes == []


def test_polling_rejects_non_main_scope_before_any_event_write():
    backend = PollingTimingBackend()
    backend.times = iter([1.0, 1.0, 2.0, 2.0])
    events = [{"event_id": "main", "time_s": 1.0, "component_id": 17, "parameter_name": "Value", "value": 1},
              {"event_id": "other", "time_s": 2.0, "target": {"instance_path": "Other", "owner": "17", "parameter": "Value"}, "value": 0}]
    with pytest.raises(BackendError, match="Main"):
        asyncio.run(dispatch_timed_events(backend, "case", events, mode="simulation_clock_polling"))
    assert backend.writes == []


@pytest.mark.parametrize("declared_scope", [False, True])
def test_native_non_main_scope_requires_explicit_provider_support(declared_scope):
    class Backend(NativeTimingBackend):
        async def get_timed_control_capabilities(self, project_name):
            result = await super().get_timed_control_capabilities(project_name)
            if declared_scope:
                result["supported_instance_paths"] = ["Main", "Other"]
            return result

        async def schedule_timed_controls(self, project_name, events):
            return events

    events = [{"event_id": "other", "time_s": 1.0, "target": {"instance_path": "Other", "owner": "17", "parameter": "Value"}, "value": 0}]
    if declared_scope:
        result = asyncio.run(dispatch_timed_events(Backend(), "case", events, mode="native"))
        assert result[0]["target"]["instance_path"] == "Other"
    else:
        with pytest.raises(BackendError, match="scope"):
            asyncio.run(dispatch_timed_events(Backend(), "case", events, mode="native"))
