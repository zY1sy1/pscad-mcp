from __future__ import annotations

import copy
from pathlib import Path

import pytest

from blueprint_builder_fakes import RecordingBlueprintPscadService
from pscad_mcp.builders.blueprint.assets import hash_tree
from pscad_mcp.builders.blueprint.executor import execute_build
from pscad_mcp.builders.blueprint.models import BlueprintBuildState
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
