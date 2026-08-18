from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from pscad_mcp.hvdc.builders.lcc.executor import execute_build
from pscad_mcp.hvdc.builders.lcc.models import (
    LccBlueprint,
    LccBuildPlan,
    LccComponentSpec,
    LccPlanOperation,
)

from lcc_builder_fakes import RecordingPscadService


def _plan(tmp_path: Path) -> LccBuildPlan:
    blueprint = LccBlueprint(
        schema_version=1,
        name="executor_test",
        topology="lcc",
        poles=1,
        terminals=2,
        settings={"simulation_duration_s": 1.0},
        components=(
            LccComponentSpec("source", "master:source", (10, 20), parameters={"LogicalId": "source"}),
            LccComponentSpec("load", "master:load", (40, 20), parameters={"LogicalId": "load"}),
        ),
        nets=(),
        outputs=(),
    )
    staging = tmp_path / ".pscad-mcp" / "lcc-builds" / "executor.staging"
    target = tmp_path / "final.pscx"
    operations = [
        LccPlanOperation(1, "materialize_library", "library/cigre.pslx", {}, "materialize:library:000", "materialize_library"),
        LccPlanOperation(2, "create_staging", "executor", {"target_path": str(target), "staging_path": str(staging)}, "create_staging:executor:000", "create_staging"),
        LccPlanOperation(3, "set_project_settings", "executor", {"settings": {"simulation_duration_s": 1.0}}, "set_settings:executor:000", "set_settings"),
        LccPlanOperation(4, "place_component", "source", {"definition": "master:source", "location": [10, 20], "orientation": 0, "parameters": {"LogicalId": "source"}, "ports": []}, "place_power:source:000", "place_power"),
        LccPlanOperation(5, "place_component", "load", {"definition": "master:load", "location": [40, 20], "orientation": 0, "parameters": {"LogicalId": "load"}, "ports": []}, "place_power:load:001", "place_power"),
        LccPlanOperation(6, "verify_parameters", "source", {"parameters": {"LogicalId": "source"}}, "verify_parameters:source:000", "verify_parameters"),
        LccPlanOperation(7, "verify_parameters", "load", {"parameters": {"LogicalId": "load"}}, "verify_parameters:load:001", "verify_parameters"),
        LccPlanOperation(8, "create_output", "vdc", {"path": "Main/VDC", "units": "kV"}, "create_outputs:vdc:000", "create_outputs"),
        LccPlanOperation(9, "save_and_validate", "executor", {}, "save_and_validate:executor:000", "save_and_validate"),
        LccPlanOperation(10, "compile", "executor", {}, "compile:executor:000", "compile"),
        LccPlanOperation(11, "simulate", "executor", {"duration_s": 1.0}, "simulate:executor:000", "simulate"),
        LccPlanOperation(12, "accept", "executor", {"required_checks": []}, "accept:executor:000", "accept"),
        LccPlanOperation(13, "publish", "executor", {"target_path": str(target)}, "publish:executor:000", "publish"),
    ]
    return LccBuildPlan(
        blueprint=blueprint,
        operations=tuple(operations),
        plan_hash="plan-hash",
        target_path=str(target),
        staging_path=str(staging),
        metadata={"project_name": "executor"},
    )


def test_execute_build_verifies_mutations_and_publishes_after_acceptance(tmp_path):
    service = RecordingPscadService()
    record = asyncio.run(execute_build(_plan(tmp_path), service, tmp_path, build_id="build-1", poll_interval_s=0))

    assert record.state.value == "published"
    states = [entry["state"] for entry in record.history if "state" in entry]
    assert states == [
        "validated",
        "staging_created",
        "components_placed",
        "parameters_verified",
        "structure_verified",
        "staging_saved",
        "compiled",
        "simulated",
        "acceptance_passed",
        "published",
    ]
    names = [call[0] for call in service.calls]
    assert names.index("add_canvas_component") < names.index("get_component_location")
    assert names.index("get_component_parameters") < names.index("save_project")
    assert names.index("get_project_output") < names.index("save_project_as")
    assert Path(_plan(tmp_path).target_path).exists()

    journal = tmp_path / ".pscad-mcp" / "lcc-builds" / "build-1" / "journal.json"
    assert json.loads(journal.read_text(encoding="utf-8"))["state"] == "published"


@pytest.mark.parametrize("failure", ["create_project", "get_component_parameters", "save_project", "build_project", "run_project", "get_project_output", "save_project_as"])
def test_execute_build_contains_failures_and_never_publishes(tmp_path, failure):
    service = RecordingPscadService(fail_on=failure)
    record = asyncio.run(execute_build(_plan(tmp_path), service, tmp_path, build_id=f"build-{failure}", poll_interval_s=0))

    assert record.state.value == "failed"
    assert not Path(_plan(tmp_path).target_path).exists()
    assert Path(record.workspace).exists()
    assert record.error["backend"] == "hvdc"
    calls = [call[0] for call in service.calls]
    if failure in calls:
        assert calls.index(failure) == max(index for index, name in enumerate(calls) if name == failure)
    journal = tmp_path / ".pscad-mcp" / "lcc-builds" / f"build-{failure}" / "journal.json"
    assert json.loads(journal.read_text(encoding="utf-8"))["state"] == "failed"


def test_execute_build_rejects_simulation_terminal_state_without_observed_run(tmp_path):
    service = RecordingPscadService(run_statuses=["completed"])
    record = asyncio.run(execute_build(_plan(tmp_path), service, tmp_path, build_id="build-no-run", poll_interval_s=0, timeout_s=0))

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_BUILD_TIMED_OUT"
