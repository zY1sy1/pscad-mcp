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


class DiscoveredOutputMmcService(RecordingMmcService):
    def __init__(self, output_path: Path, *, outside: bool = False):
        super().__init__()
        self.output_path = output_path
        self.outside = outside

    async def discover_output_files(self, project_file: str, *, started_after: float, max_files: int):
        self._call("discover_output_files", project_file, started_after=started_after, max_files=max_files)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text("owned output", encoding="utf-8")
        return [str(self.output_path)]

    async def read_output_file(self, file_path: str, *, max_samples: int, summary_only: bool):
        self._call("read_output_file", file_path, max_samples=max_samples, summary_only=summary_only)
        return {"verdict": "PASS"}


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


def test_output_discovery_rejects_file_outside_builder_staging(tmp_path, monkeypatch):
    monkeypatch.setattr(executor_module, "read_project_graph", lambda path: object())
    monkeypatch.setattr(executor_module, "validate_project_graph", lambda graph, blueprint: {"valid": True, "findings": []})
    plan = _plan(tmp_path)
    service = DiscoveredOutputMmcService(tmp_path / "external" / "result.out")

    record = asyncio.run(execute_build(plan, service, tmp_path, build_id="output-outside", poll_interval_s=0, allow_test_double=True))

    assert record.state.value == "failed"
    assert record.error["code"] == "MMC_OUTPUT_INCOMPLETE"
    assert record.error["details"]["reason"] == "output_outside_staging"
    assert "save_project_as" not in [call[0] for call in service.calls]
    assert not Path(plan.target_path).exists()


def test_output_discovery_records_owned_output_and_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(executor_module, "read_project_graph", lambda path: object())
    monkeypatch.setattr(executor_module, "validate_project_graph", lambda graph, blueprint: {"valid": True, "findings": []})
    plan = _plan(tmp_path)
    output_path = Path(plan.staging_path) / "MMC_TEST.out"
    service = DiscoveredOutputMmcService(output_path)

    record = asyncio.run(execute_build(plan, service, tmp_path, build_id="output-owned", poll_interval_s=0, allow_test_double=True))

    assert record.state.value == "published"
    assert record.result["output_file"] == str(output_path.resolve())
    assert len(record.result["output_sha256"]) == 64
    names = [call[0] for call in service.calls]
    assert "get_project_output" not in names
    assert names.index("discover_output_files") < names.index("read_output_file")
