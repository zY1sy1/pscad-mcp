import asyncio

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.backend.modern import ModernBackend
from tests.backend_fakes import ImmediateExecutor


class TimingProject:
    def __init__(self):
        self.scheduled = []
        self.simulation_time = 0.0

    def schedule_timed_controls(self, events):
        self.scheduled.extend(dict(event) for event in events)
        return [{"status": "registered", "index": index} for index, _ in enumerate(events)]

    def get_simulation_time(self):
        return self.simulation_time


@pytest.mark.parametrize("backend_factory", [
    lambda: LegacyBackend(ImmediateExecutor(), version="4.6.2", x64=True, automation_module=False),
    lambda: ModernBackend(ImmediateExecutor(), version="5.0.2", x64=True, pscad_module=False, psout_module=False),
])
def test_backends_use_explicit_project_timing_provider(backend_factory):
    backend = backend_factory()
    project = TimingProject()

    async def project_for(_name):
        return project

    backend._project = project_for
    capabilities = asyncio.run(backend.get_timed_control_capabilities("case"))
    assert capabilities["native_schedule"] is True
    assert capabilities["simulation_clock"] is True
    acknowledgements = asyncio.run(backend.schedule_timed_controls("case", [{"time_s": 1.0}]))
    assert acknowledgements[0]["status"] == "registered"
    project.simulation_time = 1.25
    assert asyncio.run(backend.get_simulation_time("case")) == 1.25


@pytest.mark.parametrize("backend_factory", [
    lambda: LegacyBackend(ImmediateExecutor(), version="4.6.2", x64=True, automation_module=False),
    lambda: ModernBackend(ImmediateExecutor(), version="5.0.2", x64=True, pscad_module=False, psout_module=False),
])
def test_backends_reject_missing_explicit_timing_provider(backend_factory):
    backend = backend_factory()

    async def project_for(_name):
        return object()

    backend._project = project_for
    assert asyncio.run(backend.get_timed_control_capabilities("case")) == {
        "native_schedule": False,
        "simulation_clock": False,
        "time_basis": "EMTDC",
    }
    with pytest.raises(BackendError) as raised:
        asyncio.run(backend.schedule_timed_controls("case", []))
    assert raised.value.code == "CAPABILITY_UNAVAILABLE"
