from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pscad_mcp.hvdc.builders.mmc import executor as executor_module
from pscad_mcp.hvdc.builders.mmc.executor import execute_build

from tests.mmc_builder_fakes import RecordingMmcService
from tests.test_mmc_executor import _plan


class BlockingMmcService(RecordingMmcService):
    def __init__(self):
        super().__init__(run_statuses=["running"])
        self.status_started = asyncio.Event()
        self.stopped = False

    async def get_run_status(self, project_name: str) -> dict[str, str]:
        self._call("get_run_status", project_name)
        self.status_started.set()
        if self.stopped:
            return {"status": "stopped"}
        await asyncio.sleep(60)
        return {"status": "running"}

    async def stop_simulation(self, project_name: str) -> str:
        self._call("stop_simulation", project_name)
        self.stopped = True
        return "stopped"


def test_cancelled_executor_records_interrupted_and_stops_simulation(tmp_path, monkeypatch):
    monkeypatch.setattr(executor_module, "read_project_graph", lambda path: object())
    monkeypatch.setattr(executor_module, "validate_project_graph", lambda graph, blueprint: {"valid": True, "findings": []})
    plan = _plan(tmp_path)
    service = BlockingMmcService()

    async def run_and_cancel():
        task = asyncio.create_task(execute_build(plan, service, tmp_path, build_id="build-interrupted", poll_interval_s=0, allow_test_double=True))
        await service.status_started.wait()
        task.cancel()
        return await task

    record = asyncio.run(run_and_cancel())

    assert record.state.value == "interrupted"
    assert record.error["code"] == "MMC_BUILD_FAILED"
    assert "stop_simulation" in [call[0] for call in service.calls]
    assert not Path(plan.target_path).exists()


@pytest.mark.parametrize(
    "fail_on",
    ["create_project", "set_project_settings", "add_canvas_component", "create_output_channel", "save_project", "build_project", "run_project", "get_project_output", "save_project_as"],
)
def test_failure_at_each_public_mutation_boundary_never_runs_publish_afterward(tmp_path, monkeypatch, fail_on):
    monkeypatch.setattr(executor_module, "read_project_graph", lambda path: object())
    monkeypatch.setattr(executor_module, "validate_project_graph", lambda graph, blueprint: {"valid": True, "findings": []})
    plan = _plan(tmp_path)
    service = RecordingMmcService(fail_on=fail_on)

    record = asyncio.run(execute_build(plan, service, tmp_path, build_id=f"failure-{fail_on}", poll_interval_s=0, allow_test_double=True))

    assert record.state.value == "failed"
    names = [call[0] for call in service.calls]
    failure_index = names.index(fail_on)
    assert "save_project_as" not in names[failure_index + 1 :]
    assert not Path(plan.target_path).exists()
