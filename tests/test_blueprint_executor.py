from __future__ import annotations

import asyncio
import copy
from pathlib import Path

import pytest

from blueprint_builder_fakes import RecordingBlueprintPscadService
from pscad_mcp.builders.blueprint.assets import hash_tree, load_blueprint_asset
from pscad_mcp.builders.blueprint.executor import execute_build
from pscad_mcp.builders.blueprint.inventory import normalize_inventory
from pscad_mcp.builders.blueprint.models import BlueprintBuildState
from pscad_mcp.builders.blueprint.planner import create_plan
from pscad_mcp.core.path_policy import PathPolicy
from test_blueprint_assets import write_source_package
from test_blueprint_planner import live_inventory, plan
from test_blueprint_schema import valid_blueprint


def full_blueprint() -> dict:
    value = valid_blueprint()
    value["operations"] = [
        value["operations"][0],
        {"sequence": 2, "kind": "set_component_location", "target": "breaker_copy", "arguments": {"location": [21, 31]}, "operation_id": "op-002"},
        {"sequence": 3, "kind": "rotate_component", "target": "breaker_copy", "arguments": {"direction": "right", "expected_orientation": 90}, "operation_id": "op-003"},
        {**value["operations"][1], "sequence": 4, "operation_id": "op-004"},
        {"sequence": 5, "kind": "create_component", "target": "aux", "arguments": {"logical_id": "aux", "definition": "master:breaker", "location": [40, 30], "orientation": 0, "canvas": "Main", "parameters": {"LogicalId": "aux", "Name": "AUX"}}, "operation_id": "op-005"},
        {"sequence": 6, "kind": "create_wire", "target": "wire-1", "arguments": {"canvas": "Main", "vertices": [[21, 31], [30, 31], [30, 30], [39, 30]]}, "operation_id": "op-006"},
        {"sequence": 7, "kind": "connect_ports", "target": "connection-1", "arguments": {"canvas": "Main", "from": {"logical_id": "breaker_copy", "port": "B"}, "to": {"logical_id": "aux", "port": "A"}}, "operation_id": "op-007"},
        {"sequence": 8, "kind": "set_project_settings", "target": "project", "arguments": {"settings": {"time_step_s": 0.001}}, "operation_id": "op-008"},
        {"sequence": 9, "kind": "declare_output_channel", "target": "brk-state", "arguments": {"path": "Main/BRK_STATE", "units": "state", "call_id": 1}, "operation_id": "op-009"},
    ]
    return value


@pytest.mark.asyncio
async def test_executor_copies_before_write_applies_all_operations_and_validates_lifecycle(tmp_path):
    inventory = live_inventory()
    inventory["definitions"]["master:breaker"]["parameters"]["LogicalId"] = {"resolved": True, "units": None}
    build_plan = plan(tmp_path, blueprint=full_blueprint(), inventory=inventory)
    before = hash_tree(build_plan.source_path)
    service = RecordingBlueprintPscadService()

    record = await execute_build(build_plan, service, tmp_path, build_id="build-001", poll_interval_s=0, simulation_timeout_s=1)

    assert record.state is BlueprintBuildState.ACCEPTANCE_PASSED
    assert record.result["run_through_acceptance"] is True
    assert hash_tree(build_plan.source_path) == before
    assert Path(record.staging_path).is_dir()
    assert (Path(record.staging_path) / "BuiltCase.pscx").is_file()
    assert (Path(record.staging_path) / "support" / "breaker.pslx").is_file()
    assert record.component_bindings == {"source_breaker": 17, "breaker_copy": 18, "aux": 19}
    call_names = [call[0] for call in service.calls]
    for expected in [
        "load_projects", "clone_component", "set_component_location", "rotate_component",
        "set_component_parameters", "create_canvas_component", "create_wire", "connect_ports",
        "set_project_settings", "create_output_channel", "save_project", "reload_project",
        "build_project", "run_project", "get_run_status", "get_project_output",
    ]:
        assert expected in call_names
    assert call_names.index("save_project") < call_names.index("reload_project") < call_names.index("build_project") < call_names.index("run_project")
    assert len(record.history) >= 10
    assert (Path(record.staging_path) / "evidence" / "plan.json").is_file()
    assert (Path(record.staging_path) / "evidence" / "validation-report.json").is_file()
    assert (Path(record.staging_path) / "evidence" / "manifest.json").is_file()


@pytest.mark.asyncio
async def test_executor_quarantines_readback_mismatch_and_preserves_source(tmp_path):
    build_plan = plan(tmp_path)
    before = hash_tree(build_plan.source_path)
    service = RecordingBlueprintPscadService(location_drift=True)

    record = await execute_build(build_plan, service, tmp_path, build_id="build-drift", poll_interval_s=0)

    assert record.state is BlueprintBuildState.QUARANTINED
    assert record.error["code"] == "BLUEPRINT_READBACK_MISMATCH"
    assert "quarantine" in record.staging_path
    assert Path(record.staging_path).is_dir()
    assert hash_tree(build_plan.source_path) == before
    assert not record.result


@pytest.mark.asyncio
async def test_executor_stops_and_quarantines_simulation_timeout(tmp_path):
    build_plan = plan(tmp_path)
    service = RecordingBlueprintPscadService(run_statuses=["running"] * 20)

    record = await execute_build(
        build_plan,
        service,
        tmp_path,
        build_id="build-timeout",
        poll_interval_s=0.001,
        simulation_timeout_s=0.005,
    )

    assert record.state is BlueprintBuildState.QUARANTINED
    assert record.error["code"] == "BLUEPRINT_BUILD_TIMED_OUT"
    assert "stop_simulation" in [call[0] for call in service.calls]
    assert [item["state"] for item in record.history if "state" in item][-2:] == ["timed_out", "quarantined"]
    stop_index = next(index for index, call in enumerate(service.calls) if call[0] == "stop_simulation")
    assert any(call[0] == "get_run_status" for call in service.calls[stop_index + 1 :])


@pytest.mark.asyncio
async def test_executor_shields_stop_settlement_and_records_interruption_on_cancel(tmp_path):
    class BlockingStatusService(RecordingBlueprintPscadService):
        def __init__(self):
            super().__init__()
            self.status_started = asyncio.Event()
            self.stopped = False

        async def get_run_status(self, project_name):
            self._call("get_run_status", project_name)
            if self.stopped:
                return {"status": "stopped"}
            self.status_started.set()
            await asyncio.sleep(60)
            return {"status": "running"}

        async def stop_simulation(self, project_name):
            self._call("stop_simulation", project_name)
            self.stopped = True
            return "stopped"

    service = BlockingStatusService()
    task = asyncio.create_task(
        execute_build(
            plan(tmp_path),
            service,
            tmp_path,
            build_id="build-cancelled",
            poll_interval_s=0,
        )
    )
    await service.status_started.wait()
    task.cancel()

    record = await task

    assert record.state is BlueprintBuildState.QUARANTINED
    assert record.error["code"] == "BLUEPRINT_BUILD_INTERRUPTED"
    assert [item["state"] for item in record.history if "state" in item][-2:] == ["interrupted", "quarantined"]
    assert service.stopped is True


@pytest.mark.asyncio
async def test_executor_bounds_non_terminal_stop_settlement(tmp_path):
    class NeverSettlesService(RecordingBlueprintPscadService):
        async def get_run_status(self, project_name):
            self._call("get_run_status", project_name)
            return {"status": "running"}

    record = await execute_build(
        plan(tmp_path),
        NeverSettlesService(),
        tmp_path,
        build_id="build-never-settles",
        poll_interval_s=0.001,
        simulation_timeout_s=0.003,
        settlement_timeout_s=0.005,
    )

    assert record.state is BlueprintBuildState.QUARANTINED
    assert record.error["code"] == "BLUEPRINT_SETTLEMENT_TIMED_OUT"


@pytest.mark.asyncio
async def test_executor_reloads_saved_disk_state_before_compile(tmp_path):
    class TamperedSaveService(RecordingBlueprintPscadService):
        async def save_project(self, project_name, *, confirm=False):
            result = await super().save_project(project_name, confirm=confirm)
            assert self.project_file is not None
            self.project_file.write_text(
                self.project_file.read_text(encoding="utf-8").replace('name="Name" value="BRK_COPY"', 'name="Name" value="DISK_DRIFT"'),
                encoding="utf-8",
            )
            return result

    service = TamperedSaveService()
    record = await execute_build(plan(tmp_path), service, tmp_path, build_id="build-disk-drift")

    assert record.state is BlueprintBuildState.QUARANTINED
    assert record.error["code"] == "BLUEPRINT_READBACK_MISMATCH"
    assert "build_project" not in [call[0] for call in service.calls]


@pytest.mark.asyncio
async def test_executor_rejects_existing_build_directory_without_overwriting(tmp_path):
    build_plan = plan(tmp_path)
    build_root = tmp_path / ".pscad-mcp" / "blueprint-builds" / "build-existing"
    build_root.mkdir(parents=True)
    marker = build_root / "owner.txt"
    marker.write_text("existing", encoding="utf-8")

    record = await execute_build(build_plan, RecordingBlueprintPscadService(), tmp_path, build_id="build-existing")

    assert record.state is BlueprintBuildState.REJECTED
    assert record.error["code"] == "BLUEPRINT_BUILD_CONFLICT"
    assert marker.read_text(encoding="utf-8") == "existing"


@pytest.mark.asyncio
async def test_executor_loads_staged_companion_library_with_renamed_project(tmp_path):
    source = write_source_package(tmp_path)
    (source / "BreakerArc.pslx").write_text("<library/>", encoding="utf-8")
    blueprint = valid_blueprint()
    blueprint["source_package"]["required"].append({"path": "BreakerArc.pslx", "kind": "file"})
    build_plan = create_plan(
        load_blueprint_asset(blueprint),
        str(source),
        "BuiltCase",
        normalize_inventory(live_inventory()),
        PathPolicy(str(tmp_path)),
    )
    service = RecordingBlueprintPscadService()

    record = await execute_build(build_plan, service, tmp_path, build_id="build-library", poll_interval_s=0)

    assert record.state is BlueprintBuildState.ACCEPTANCE_PASSED
    load = next(call for call in service.calls if call[0] == "load_projects")
    assert [Path(path).name for path in load[1][0]] == ["BuiltCase.pscx", "BreakerArc.pslx"]


@pytest.mark.asyncio
async def test_executor_uses_real_pscad_service_mutation_signatures(tmp_path):
    class StrictSignatureService(RecordingBlueprintPscadService):
        async def set_component_parameters(self, project_name, component_id, parameters):
            return await super().set_component_parameters(project_name, component_id, parameters)

        async def set_project_settings(self, project_name, settings):
            return await super().set_project_settings(project_name, settings)

    inventory = live_inventory()
    inventory["definitions"]["master:breaker"]["parameters"]["LogicalId"] = {
        "resolved": True,
        "units": None,
    }

    record = await execute_build(
        plan(tmp_path, blueprint=full_blueprint(), inventory=inventory),
        StrictSignatureService(),
        tmp_path,
        build_id="build-real-signatures",
        poll_interval_s=0,
    )

    assert record.state is BlueprintBuildState.ACCEPTANCE_PASSED


@pytest.mark.asyncio
async def test_executor_rejects_unchanged_preexisting_target_output(tmp_path):
    class NoOutputService(RecordingBlueprintPscadService):
        async def run_project(self, project_name):
            self._call("run_project", project_name)
            return "started"

    source = write_source_package(tmp_path)
    (source / "BuiltCase.inf").write_text(
        'PGB(1) Output Desc="BRK_STATE" Group="Main" Max=1 Min=0 Units="state"\n',
        encoding="utf-8",
    )
    (source / "BuiltCase_01.out").write_text("0.0 0\n0.1 1\n", encoding="utf-8")
    build_plan = create_plan(
        load_blueprint_asset(valid_blueprint()),
        str(source),
        "BuiltCase",
        normalize_inventory(live_inventory()),
        PathPolicy(str(tmp_path)),
    )

    record = await execute_build(
        build_plan,
        NoOutputService(),
        tmp_path,
        build_id="build-stale-output",
        poll_interval_s=0,
    )

    assert record.state is BlueprintBuildState.QUARANTINED
    assert record.error["code"] == "BLUEPRINT_OUTPUT_STALE"


@pytest.mark.asyncio
async def test_executor_rejects_post_run_blocking_messages(tmp_path):
    class PostRunFatalService(RecordingBlueprintPscadService):
        def __init__(self):
            super().__init__()
            self.message_reads = 0

        async def get_project_output(self, project_name, structured=False):
            self._call("get_project_output", project_name, structured=structured)
            self.message_reads += 1
            if self.message_reads == 1:
                return []
            return [{"severity": "error", "text": "Fatal runtime issue"}]

    record = await execute_build(
        plan(tmp_path),
        PostRunFatalService(),
        tmp_path,
        build_id="build-post-run-message",
        poll_interval_s=0,
    )

    assert record.state is BlueprintBuildState.QUARANTINED
    assert record.error["code"] == "BLUEPRINT_ACCEPTANCE_FAILED"
    assert record.error["details"]["validation"]["messages_acceptance"] is False
