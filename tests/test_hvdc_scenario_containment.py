import asyncio
import os
import time

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import PscadService
from pscad_mcp.hvdc.service import HvdcDomainService


def _write_project(path):
    path.write_text(
        "<project><canvas name='Main'><component id='2' name='control' definition='control'>"
        "<parameter name='Name' value='current order'/></component></canvas></project>",
        encoding="utf-8",
    )


def _scenario(source, *, event_time=None, timeout_s=1):
    events = []
    if event_time is not None:
        events.append({"time_s": event_time, "target": "current_order", "value": 3})
    return {
        "name": "contained",
        "profile": "lcc_bipolar_generic",
        "project": str(source),
        "derived_project": "case_derived",
        "parameter_changes": [],
        "events": events,
        "run": {"timeout_s": timeout_s},
    }


async def _terminal(service, scenario_id, timeout=0.5):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        record = await service.scenario_status(scenario_id)
        if record["status"] in {"completed", "failed", "timed_out"}:
            return record
        await asyncio.sleep(0.001)
    raise AssertionError("scenario did not reach a terminal record")


class BlockingBackend:
    def __init__(self):
        self.run_entered = asyncio.Event()
        self.release_run = asyncio.Event()
        self.stopped = False
        self.calls = []

    async def list_projects(self):
        return [{"name": "case_derived"}]

    async def run_project(self, project_name):
        self.calls.append(("run", project_name, asyncio.get_running_loop().time()))
        self.run_entered.set()
        await self.release_run.wait()

    async def set_component_parameters(self, project_name, component_id, values):
        self.calls.append(("set", project_name, component_id, values, asyncio.get_running_loop().time()))

    async def get_run_status(self, project_name):
        if self.stopped:
            return {"status": "stopped", "progress": None}
        if self.release_run.is_set():
            return {"status": "completed", "progress": 100.0}
        return {"status": "running", "progress": None}

    async def get_project_output(self, project_name, structured=False):
        return []


def test_application_wide_scenario_reservation_rejects_concurrent_start(tmp_path):
    source = tmp_path / "case.pscx"
    _write_project(source)
    backend = BlockingBackend()
    service = HvdcDomainService(backend, path_policy=PathPolicy(workspace_root=str(tmp_path)))

    async def exercise():
        first = await service.run_scenario(str(source), _scenario(source), confirm=True)
        await asyncio.wait_for(backend.run_entered.wait(), 0.1)
        with pytest.raises(BackendError) as raised:
            await service.run_scenario(str(source), _scenario(source), confirm=True)
        backend.release_run.set()
        terminal = await _terminal(service, first["scenario_id"])
        await asyncio.sleep(0)
        return first, raised.value, terminal

    first, error, terminal = asyncio.run(exercise())
    assert error.code == "HVDC_SCENARIO_CONFLICT"
    assert error.details["active_scenario_id"] == first["scenario_id"]
    assert terminal["status"] == "completed"
    assert service._active_scenario_id is None


def test_timeout_attempts_stop_and_releases_reservation_only_when_contained(tmp_path):
    source = tmp_path / "case.pscx"
    _write_project(source)

    class StoppableBackend(BlockingBackend):
        async def stop_simulation(self, project_name):
            self.calls.append(("stop", project_name))
            self.stopped = True
            self.release_run.set()
            return "stopped"

    backend = StoppableBackend()
    service = HvdcDomainService(backend, path_policy=PathPolicy(workspace_root=str(tmp_path)))

    async def exercise():
        started = await service.run_scenario(str(source), _scenario(source, timeout_s=0.02), confirm=True)
        terminal = await _terminal(service, started["scenario_id"])
        await asyncio.sleep(0)
        return terminal

    terminal = asyncio.run(exercise())
    assert terminal["status"] == "timed_out"
    assert terminal["outcome"] == "timed_out_contained"
    assert terminal["containment"]["status"] == "contained"
    assert terminal["containment"]["stop"]["result"] == "stopped"
    assert terminal["partial_completion"]["run_started"] in {True, "unknown"}
    assert service._active_scenario_id is None


def test_cancellation_resistant_run_is_stopped_without_deadlocking_timeout(tmp_path):
    source = tmp_path / "case.pscx"
    _write_project(source)

    class CancellationResistantBackend(BlockingBackend):
        async def run_project(self, project_name):
            self.run_entered.set()
            try:
                await self.release_run.wait()
            except asyncio.CancelledError:
                await self.release_run.wait()

        async def stop_simulation(self, project_name):
            self.stopped = True
            self.release_run.set()
            return "stopped"

    backend = CancellationResistantBackend()
    service = HvdcDomainService(backend, path_policy=PathPolicy(workspace_root=str(tmp_path)))

    async def exercise():
        started = await service.run_scenario(str(source), _scenario(source, timeout_s=0.02), confirm=True)
        terminal = await _terminal(service, started["scenario_id"], timeout=0.3)
        await asyncio.sleep(0)
        return terminal

    terminal = asyncio.run(exercise())
    assert terminal["status"] == "timed_out"
    assert terminal["containment"]["status"] == "contained"
    assert service._scenario_run_tasks == {}


def test_uncontained_timeout_is_needs_review_and_keeps_reservation(tmp_path):
    source = tmp_path / "case.pscx"
    _write_project(source)

    class UncontainedBackend:
        def __init__(self):
            self.run_entered = asyncio.Event()

        async def list_projects(self):
            return [{"name": "case_derived"}]

        async def run_project(self, project_name):
            self.run_entered.set()
            await asyncio.Event().wait()

    backend = UncontainedBackend()
    service = HvdcDomainService(backend, path_policy=PathPolicy(workspace_root=str(tmp_path)))

    async def exercise():
        started = await service.run_scenario(str(source), _scenario(source, timeout_s=0.02), confirm=True)
        terminal = await _terminal(service, started["scenario_id"])
        with pytest.raises(BackendError) as raised:
            await service.run_scenario(str(source), _scenario(source), confirm=True)
        return started, terminal, raised.value

    started, terminal, error = asyncio.run(exercise())
    assert terminal["status"] == "timed_out"
    assert terminal["outcome"] == "needs_review"
    assert terminal["containment"]["status"] == "unknown"
    assert terminal["partial_completion"]["run_started"] == "unknown"
    assert error.code == "HVDC_SCENARIO_CONFLICT"
    assert error.details["active_scenario_id"] == started["scenario_id"]
    assert service._active_scenario_id == started["scenario_id"]


def test_timed_event_is_dispatched_while_blocking_run_command_is_active(tmp_path):
    source = tmp_path / "case.pscx"
    _write_project(source)

    class EventReleasesRunBackend(BlockingBackend):
        async def set_component_parameters(self, project_name, component_id, values):
            await super().set_component_parameters(project_name, component_id, values)
            self.release_run.set()

    backend = EventReleasesRunBackend()
    service = HvdcDomainService(backend, path_policy=PathPolicy(workspace_root=str(tmp_path)))

    async def exercise():
        started = await service.run_scenario(
            str(source), _scenario(source, event_time=0.02, timeout_s=0.3), confirm=True
        )
        return await _terminal(service, started["scenario_id"])

    terminal = asyncio.run(exercise())
    run_call = next(call for call in backend.calls if call[0] == "run")
    set_call = next(call for call in backend.calls if call[0] == "set")
    assert terminal["status"] == "completed"
    assert 0.01 <= set_call[-1] - run_call[-1] < 0.15


def test_locked_timed_event_times_out_without_late_delivery_and_is_contained(tmp_path):
    source = tmp_path / "case.pscx"
    _write_project(source)

    class LockedBackend(BlockingBackend):
        def __init__(self):
            super().__init__()
            self.lock = asyncio.Lock()
            self.delivered = []

        async def run_project(self, project_name):
            async with self.lock:
                await super().run_project(project_name)

        async def set_component_parameters(self, project_name, component_id, values):
            async with self.lock:
                self.delivered.append(values)

        async def stop_simulation(self, project_name):
            self.stopped = True
            self.release_run.set()
            return "stopped"

    backend = LockedBackend()
    service = HvdcDomainService(backend, path_policy=PathPolicy(workspace_root=str(tmp_path)))

    async def exercise():
        started = await service.run_scenario(
            str(source), _scenario(source, event_time=0.01, timeout_s=0.04), confirm=True
        )
        terminal = await _terminal(service, started["scenario_id"])
        await asyncio.sleep(0.02)
        return terminal

    terminal = asyncio.run(exercise())
    assert terminal["status"] == "timed_out"
    assert terminal["outcome"] == "timed_out_contained"
    assert terminal["partial_completion"]["applied_events"] == []
    assert backend.delivered == []


def test_pscad_service_discovers_only_new_outputs_tied_to_project(tmp_path):
    project = tmp_path / "derived.pscx"
    project.write_text("<project />", encoding="utf-8")
    project_outputs = tmp_path / "derived.gf46"
    project_outputs.mkdir()
    unrelated_outputs = tmp_path / "other.gf46"
    unrelated_outputs.mkdir()
    misleading_outputs = tmp_path / "derived.gf46-backup"
    misleading_outputs.mkdir()
    before = time.time()
    old_output = project_outputs / "old.out"
    old_output.write_text("old", encoding="utf-8")
    os.utime(old_output, (before - 10, before - 10))
    new_output = project_outputs / "TL1.out"
    new_output.write_text("new", encoding="utf-8")
    direct_output = tmp_path / "derived.psout"
    direct_output.write_text("new", encoding="utf-8")
    unrelated = unrelated_outputs / "TL1.out"
    unrelated.write_text("unrelated", encoding="utf-8")
    misleading = misleading_outputs / "TL1.out"
    misleading.write_text("unrelated", encoding="utf-8")
    service = PscadService(
        lambda: None,
        path_policy=PathPolicy(workspace_root=str(tmp_path)),
    )

    result = asyncio.run(service.discover_output_files(str(project), started_after=before))
    logical_result = asyncio.run(service.discover_output_files("derived", started_after=before))

    assert result == sorted([str(direct_output.resolve()), str(new_output.resolve())])
    assert logical_result == result
