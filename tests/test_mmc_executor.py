from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc import executor as executor_module
from pscad_mcp.hvdc.builders.mmc.executor import MmcExecutor, execute_build
from pscad_mcp.hvdc.builders.mmc.models import MmcBuildPlan, MmcPlanOperation

from tests.mmc_builder_fakes import RecordingMmcService
from tests.test_mmc_planner import BLUEPRINT


def _plan(tmp_path: Path) -> MmcBuildPlan:
    staging = tmp_path / ".pscad-mcp" / "mmc-builds" / "executor.staging"
    target = tmp_path / "final.pscx"
    operations = [
        MmcPlanOperation(1, "materialize_library", "library/cigre_mmc.pslx", {}, "materialize:library:000", "materialize_library"),
        MmcPlanOperation(2, "create_staging", "MMC_TEST", {"target_path": str(target), "staging_path": str(staging)}, "create_staging:MMC_TEST:000", "create_staging"),
        MmcPlanOperation(3, "set_project_settings", "MMC_TEST", {"settings": {"simulation_duration_s": 0.01}}, "set_settings:MMC_TEST:000", "set_settings"),
        MmcPlanOperation(4, "place_component", "source", {"definition": "master:source3", "location": [10, 20], "orientation": 0, "parameters": {"LogicalId": "source"}, "ports": []}, "place_power:source:000", "place_power"),
        MmcPlanOperation(5, "verify_parameters", "source", {"parameters": {"LogicalId": "source"}}, "verify_parameters:source:000", "verify_parameters"),
        MmcPlanOperation(6, "create_output", "vdc", {"path": "Main/VDC", "units": "kV", "call_id": None}, "create_outputs:vdc:000", "create_outputs"),
        MmcPlanOperation(7, "save_and_validate", "MMC_TEST", {}, "save_and_validate:MMC_TEST:000", "save_and_validate"),
        MmcPlanOperation(8, "compile", "MMC_TEST", {}, "compile:MMC_TEST:000", "compile"),
        MmcPlanOperation(9, "simulate_phase", "startup", {"duration_s": 0.01, "state": "startup_simulated"}, "startup_simulate:startup:000", "startup_simulate"),
        MmcPlanOperation(10, "simulate_phase", "forward", {"duration_s": 0.01, "state": "forward_simulated"}, "forward_simulate:forward:000", "forward_simulate"),
        MmcPlanOperation(11, "simulate_phase", "reversal", {"duration_s": 0.01, "state": "reversal_simulated"}, "reversal_simulate:reversal:000", "reversal_simulate"),
        MmcPlanOperation(12, "simulate_phase", "reverse", {"duration_s": 0.01, "state": "reverse_simulated"}, "reverse_simulate:reverse:000", "reverse_simulate"),
        MmcPlanOperation(13, "accept", "MMC_TEST", {"required_checks": []}, "accept:MMC_TEST:000", "accept"),
        MmcPlanOperation(14, "publish", "MMC_TEST", {"target_path": str(target)}, "publish:MMC_TEST:000", "publish"),
    ]
    return MmcBuildPlan(
        blueprint=BLUEPRINT,
        operations=tuple(operations),
        plan_hash="mmc-plan-hash",
        target_path=str(target),
        staging_path=str(staging),
        metadata={"project_name": "MMC_TEST"},
    )


def _valid_graph(monkeypatch):
    monkeypatch.setattr(executor_module, "read_project_graph", lambda path: object())
    monkeypatch.setattr(executor_module, "validate_project_graph", lambda graph, blueprint: {"valid": True, "findings": [], "observed": {}})


def test_executor_publishes_only_after_four_phase_sequence_and_journals_history(tmp_path, monkeypatch):
    _valid_graph(monkeypatch)
    plan = _plan(tmp_path)
    service = RecordingMmcService()

    record = asyncio.run(execute_build(plan, service, tmp_path, build_id="build-1", poll_interval_s=0, allow_test_double=True))

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
        "startup_simulated",
        "forward_simulated",
        "reversal_simulated",
        "reverse_simulated",
        "acceptance_passed",
        "published",
    ]
    names = [call[0] for call in service.calls]
    assert names.index("get_project_output") < names.index("save_project_as")
    assert Path(plan.target_path).is_file()
    journal = tmp_path / ".pscad-mcp" / "mmc-builds" / "build-1" / "journal.json"
    assert json.loads(journal.read_text(encoding="utf-8"))["state"] == "published"


def test_executor_stops_at_first_failure_and_leaves_final_target_absent(tmp_path, monkeypatch):
    _valid_graph(monkeypatch)
    plan = _plan(tmp_path)
    service = RecordingMmcService(fail_on="set_project_settings")

    record = asyncio.run(execute_build(plan, service, tmp_path, build_id="build-failure", poll_interval_s=0, allow_test_double=True))

    assert record.state.value == "failed"
    assert record.error["code"] == "MMC_BUILD_FAILED"
    names = [call[0] for call in service.calls]
    assert "add_canvas_component" not in names
    assert "save_project_as" not in names
    assert not Path(plan.target_path).exists()
    assert any(entry.get("state") == "failed" for entry in record.history)


def test_executor_timeout_is_classified_and_requests_simulation_stop(tmp_path, monkeypatch):
    _valid_graph(monkeypatch)
    plan = _plan(tmp_path)
    service = RecordingMmcService(run_statuses=["running"])

    record = asyncio.run(execute_build(plan, service, tmp_path, build_id="build-timeout", poll_interval_s=0, timeout_s=0.001, allow_test_double=True))

    assert record.state.value == "timed_out"
    assert record.error["code"] == "MMC_BUILD_TIMED_OUT"
    assert "stop_simulation" in [call[0] for call in service.calls]
    assert not Path(plan.target_path).exists()


def test_executor_does_not_publish_when_independent_graph_validation_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(executor_module, "read_project_graph", lambda path: object())
    monkeypatch.setattr(executor_module, "validate_project_graph", lambda graph, blueprint: {"valid": False, "code": "MMC_STRUCTURE_INVALID", "findings": [{"code": "MMC_STRUCTURE_INVALID"}]})
    plan = _plan(tmp_path)
    service = RecordingMmcService()

    record = asyncio.run(execute_build(plan, service, tmp_path, build_id="build-invalid", poll_interval_s=0, allow_test_double=True))

    assert record.state.value == "failed"
    assert record.error["code"] == "MMC_STRUCTURE_INVALID"
    assert "save_project_as" not in [call[0] for call in service.calls]
    assert not Path(plan.target_path).exists()


def test_existing_unreadable_library_target_is_an_asset_mismatch(tmp_path, monkeypatch):
    plan = replace(
        _plan(tmp_path),
        asset_hashes={"library/cigre_mmc.pslx": hashlib.sha256(b"library").hexdigest()},
    )
    target = tmp_path / ".pscad-mcp" / "mmc-libraries" / "cigre_mmc.pslx"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"library")
    asset_set = SimpleNamespace(
        companion_library="library/cigre_mmc.pslx",
        library_bytes=b"library",
        files={},
    )
    original_hash = executor_module._sha256_file

    def unreadable(path: Path) -> str:
        if Path(path) == target:
            raise BackendError("MMC_OUTPUT_INCOMPLETE", "cannot read target", "hvdc", "hash_mmc_project", {})
        return original_hash(path)

    monkeypatch.setattr(executor_module, "_sha256_file", unreadable)
    executor = MmcExecutor(plan, RecordingMmcService(), tmp_path, asset_set=asset_set, build_id="asset-read-failure")

    with pytest.raises(BackendError) as raised:
        asyncio.run(executor._materialize_library(plan.operations[0]))

    assert raised.value.code == "MMC_ASSET_MISMATCH"
