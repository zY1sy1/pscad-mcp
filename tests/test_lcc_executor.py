from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.assets import load_packaged_asset_set
from pscad_mcp.hvdc.builders.lcc.executor import (
    LccExecutor,
    _legacy_project_settings,
    _same_setting,
)
from pscad_mcp.hvdc.builders.lcc.executor import execute_build as _execute_build
from pscad_mcp.hvdc.builders.lcc.models import (
    LccBlueprint,
    LccBuildPlan,
    LccBuildState,
    LccComponentSpec,
    LccPlanOperation,
)
from tests.lcc_builder_fakes import RecordingPscadService
from tests.test_lcc_smoke import contract as smoke_contract
from tests.test_lcc_smoke import mutate_samples, valid_samples


def execute_build(*args, **kwargs):
    kwargs.setdefault("allow_test_double", True)
    return _execute_build(*args, **kwargs)


@pytest.mark.parametrize(
    ("expected", "observed", "matches"),
    [
        (50.0, 49.99999999999999, True),
        (50.0, 49.99, False),
        (0.0, 1e-8, False),
        (True, 1, False),
        ("Y-delta", "Y-delta", True),
        ("Y-delta", "Y-Y", False),
    ],
)
def test_parameter_readback_allows_only_numeric_serialization_noise(
    expected,
    observed,
    matches,
):
    assert _same_setting(expected, observed) is matches


class OutputFileRecordingService(RecordingPscadService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.discovered_project_name = None

    async def discover_output_files(self, project_name: str, *, started_after: float, max_files: int = 100) -> list[str]:
        self.discovered_project_name = project_name
        self._call("discover_output_files", project_name, started_after, max_files)
        output = Path(project_name).parent / "result.out"
        output.write_text("placeholder", encoding="utf-8")
        return [str(output)]

    async def read_output_file(self, file_path: str, max_samples: int = 10_000, channel: str | None = None, summary_only: bool = False) -> dict[str, object]:
        self._call("read_output_file", file_path, max_samples, channel, summary_only)
        return {"path": file_path, "verdict": "PASS"}


class FixedSmokeRecordingService(OutputFileRecordingService):
    def __init__(self, *, mutation: str | None = None):
        super().__init__()
        self.mutation = mutation

    async def read_output_file(
        self,
        file_path: str,
        max_samples: int = 10_000,
        channel: str | None = None,
        summary_only: bool = False,
    ) -> dict[str, object]:
        self._call(
            "read_output_file",
            file_path,
            max_samples,
            channel,
            summary_only,
        )
        payload = valid_samples()
        return (
            payload
            if self.mutation is None
            else mutate_samples(payload, self.mutation)
        )


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


def _plan_with_connection(tmp_path: Path) -> LccBuildPlan:
    plan = _plan(tmp_path)
    operations = []
    for operation in plan.operations:
        if operation.kind == "create_output":
            operations.append(
                LccPlanOperation(
                    operation.sequence,
                    "connect_net",
                    "source_to_load",
                    {"kind": "electrical", "vertices": [[10, 20], [40, 20]]},
                    "connect_electrical:source_to_load:000",
                    "connect_electrical",
                )
            )
        operations.append(operation)
    return replace(plan, operations=tuple(operations))


def _plan_with_profile(tmp_path: Path) -> LccBuildPlan:
    plan = _plan(tmp_path)
    operations = tuple(
        replace(
            operation,
            kind="smoke_validate",
            phase="smoke_validate",
            operation_id="smoke_validate:executor:000",
            arguments={
                "contract_sha256": "s" * 64,
                "required_channels": list(smoke_contract()["required_channels"]),
            },
        )
        if operation.kind == "accept"
        else operation
        for operation in plan.operations
    )
    return replace(
        plan,
        operations=operations,
        verification_profile="wp1b_smoke",
        asset_hashes={
            "library/cigre.pslx": "l" * 64,
            "smoke.json": "s" * 64,
        },
    )


def _fixed_smoke_assets(plan: LccBuildPlan):
    packaged = load_packaged_asset_set()
    library_hash = packaged.hashes[packaged.companion_library]
    catalog = {
        "schema_version": 1,
        "name": "executor_test",
        "pscad_version": "4.6.2",
        "identity": "executor_test/catalog",
        "definitions": [
            {
                "scoped_name": "master:source",
                "ports": [],
                "parameters": {"LogicalId": {"type": "string"}},
                "bounding_box": [-10, -10, 10, 10],
            },
            {
                "scoped_name": "master:load",
                "ports": [],
                "parameters": {"LogicalId": {"type": "string"}},
                "bounding_box": [-10, -10, 10, 10],
            },
        ],
    }
    return replace(
        packaged,
        name=plan.blueprint.name,
        companion_library="library/cigre.pslx",
        blueprint=plan.blueprint,
        catalog=catalog,
        smoke=smoke_contract(),
        hashes={
            "library/cigre.pslx": library_hash,
            "smoke.json": "s" * 64,
        },
    )


def test_executor_uses_smoke_evaluator_and_records_smoke_state(tmp_path):
    service = FixedSmokeRecordingService()
    plan = _plan_with_profile(tmp_path)

    record = asyncio.run(
        execute_build(
            plan,
            service,
            tmp_path,
            asset_set=_fixed_smoke_assets(plan),
            build_id="fixed-smoke",
            poll_interval_s=0,
        )
    )

    assert record.state == LccBuildState.PUBLISHED
    assert [item["state"] for item in record.history if "state" in item][
        -3:
    ] == ["simulated", "smoke_passed", "published"]
    assert record.result["smoke"]["verdict"] == "PASS"
    assert "golden_checks" not in record.result["smoke"]


def test_smoke_failure_never_publishes_or_calls_acceptance(tmp_path, monkeypatch):
    service = FixedSmokeRecordingService(mutation="disabled")
    plan = _plan_with_profile(tmp_path)
    called = []
    monkeypatch.setattr(
        "pscad_mcp.hvdc.builders.lcc.executor.evaluate_acceptance",
        lambda *args, **kwargs: called.append((args, kwargs)),
    )

    record = asyncio.run(
        execute_build(
            plan,
            service,
            tmp_path,
            asset_set=_fixed_smoke_assets(plan),
            build_id="fixed-smoke-fail",
            poll_interval_s=0,
        )
    )

    assert record.state == LccBuildState.FAILED
    assert record.error["code"] == "LCC_FIXED_SMOKE_FAILED"
    assert called == []
    assert not Path(plan.target_path).exists()


def test_smoke_contract_hash_drift_fails_before_output_read(tmp_path):
    service = FixedSmokeRecordingService()
    plan = _plan_with_profile(tmp_path)
    packaged = load_packaged_asset_set()
    assets = replace(
        _fixed_smoke_assets(plan),
        hashes={
            "library/cigre.pslx": packaged.hashes[
                packaged.companion_library
            ],
            "smoke.json": "x" * 64,
        },
    )

    record = asyncio.run(
        execute_build(
            plan,
            service,
            tmp_path,
            asset_set=assets,
            build_id="fixed-smoke-drift",
            poll_interval_s=0,
        )
    )

    assert record.state == LccBuildState.FAILED
    assert record.error["code"] == "LCC_ASSET_MISMATCH"
    assert "read_output_file" not in [call[0] for call in service.calls]


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
    journal_payload = json.loads(journal.read_text(encoding="utf-8"))
    assert journal_payload["state"] == "published"
    assert journal_payload["plan"]["plan_hash"] == "plan-hash"
    assert journal_payload["target_path"] == str(Path(_plan(tmp_path).target_path))


def test_executor_forwards_master_binding_evidence_to_service(tmp_path):
    plan = _plan(tmp_path)
    binding = {
        "logical_name": "master:source",
        "physical_definition": "source3",
        "physical_parameters": {"Vm": 230.0},
        "evidence_parameters": {},
        "instances": ["default"],
        "selected_ports": {},
        "registry_sha256": "a" * 64,
        "master_sha256": "b" * 64,
        "verification_state": "verified",
    }
    operations = []
    for operation in plan.operations:
        if operation.kind == "place_component" and operation.target == "source":
            arguments = dict(operation.arguments)
            arguments["binding"] = binding
            operation = replace(operation, arguments=arguments)
        operations.append(operation)
    plan = replace(
        plan,
        operations=tuple(operations),
        master_sha256="b" * 64,
        master_binding_registry_sha256="a" * 64,
    )
    service = RecordingPscadService()

    record = asyncio.run(
        execute_build(
            plan,
            service,
            tmp_path,
            build_id="build-binding-evidence",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "published"
    call = next(
        call
        for call in service.calls
        if call[0] == "add_canvas_component" and call[1][2] == "source"
    )
    planned_binding = next(
        operation.arguments["binding"]
        for operation in plan.operations
        if operation.kind == "place_component" and operation.target == "source"
    )
    assert call[2]["binding_evidence"] == planned_binding
    verification_calls = [
        item for item in service.calls if item[0] == "verify_master_binding_state"
    ]
    assert len(verification_calls) == 3
    assert [item[2]["refresh_components"] for item in verification_calls] == [
        True,
        True,
        False,
    ]


class MasterSourceChangedAfterPlacementService(RecordingPscadService):
    async def verify_master_binding_state(self, *args, **kwargs):
        await super().verify_master_binding_state(*args, **kwargs)
        raise BackendError(
            "MASTER_SOURCE_CHANGED",
            "Master changed after placement.",
            "legacy",
            "verify_master_binding_state",
        )


def test_executor_rechecks_master_source_before_compile(tmp_path):
    plan = _plan(tmp_path)
    binding = {
        "logical_name": "master:source",
        "physical_definition": "source3",
        "physical_parameters": {},
        "evidence_parameters": {},
        "instances": ["default"],
        "selected_ports": {},
        "registry_sha256": "a" * 64,
        "master_sha256": "b" * 64,
        "verification_state": "verified",
    }
    operations = []
    for operation in plan.operations:
        if operation.kind == "place_component" and operation.target == "source":
            arguments = dict(operation.arguments)
            arguments["binding"] = binding
            operation = replace(operation, arguments=arguments)
        operations.append(operation)
    plan = replace(
        plan,
        operations=tuple(operations),
        master_sha256="b" * 64,
        master_binding_registry_sha256="a" * 64,
    )
    service = MasterSourceChangedAfterPlacementService()

    record = asyncio.run(
        execute_build(
            plan,
            service,
            tmp_path,
            build_id="build-master-source-changed",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "MASTER_SOURCE_CHANGED"
    names = [call[0] for call in service.calls]
    assert "verify_master_binding_state" in names
    assert "build_project" not in names


def test_executor_forwards_trusted_threshold_registry_to_acceptance(tmp_path, monkeypatch):
    registry = {"review": {"review_id": "review"}}
    captured = {}

    def fake_evaluate(samples, golden, contract, trusted_threshold_sources=None):
        captured["samples"] = samples
        captured["trusted_threshold_sources"] = trusted_threshold_sources
        return {"verdict": "PASS"}

    monkeypatch.setattr("pscad_mcp.hvdc.builders.lcc.executor.evaluate_acceptance", fake_evaluate)
    asset_set = type("Asset", (), {"golden": {}, "acceptance": {}})()
    executor = LccExecutor(
        _plan(tmp_path),
        RecordingPscadService(),
        tmp_path,
        asset_set=asset_set,
        trusted_threshold_sources=registry,
    )

    async def acceptance_output():
        return {"time": [0.0], "channels": {}}

    executor._acceptance_output = acceptance_output
    operation = next(operation for operation in executor.plan.operations if operation.kind == "accept")
    asyncio.run(executor._accept(operation))

    assert captured["trusted_threshold_sources"] is registry


def test_execute_build_rejects_unverified_companion_library_before_loading(tmp_path):
    asset_set = load_packaged_asset_set()
    invalid_library = b"<pslx><definition name='unexpected' /></pslx>"
    hashes = dict(asset_set.hashes)
    hashes[asset_set.companion_library] = hashlib.sha256(invalid_library).hexdigest()
    asset_set = replace(asset_set, hashes=hashes, library_bytes=invalid_library)
    service = RecordingPscadService()

    record = asyncio.run(
        _execute_build(
            _plan(tmp_path),
            service,
            tmp_path,
            asset_set=asset_set,
            build_id="build-invalid-library",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_COMPANION_INVALID"
    assert "load_projects" not in [call[0] for call in service.calls]


def test_publish_reloads_final_identity_before_compile_smoke(tmp_path):
    service = RecordingPscadService()

    record = asyncio.run(execute_build(_plan(tmp_path), service, tmp_path, build_id="build-final-identity", poll_interval_s=0))

    assert record.state.value == "published"
    load_calls = [call for call in service.calls if call[0] == "load_projects"]
    assert load_calls[-1][1][0] == [str(Path(_plan(tmp_path).target_path).resolve())]
    build_calls = [call[1][0] for call in service.calls if call[0] == "build_project"]
    assert build_calls[-1] == "final"
    publication = next(entry for entry in record.history if entry.get("state") == "published")
    assert isinstance(publication.get("final_project_sha256"), str)
    assert len(publication["final_project_sha256"]) == 64


def test_execute_build_reads_waveforms_from_a_discovered_output_file(tmp_path):
    service = OutputFileRecordingService()

    record = asyncio.run(execute_build(_plan(tmp_path), service, tmp_path, build_id="build-output-file", poll_interval_s=0))

    assert record.state.value == "published"
    names = [call[0] for call in service.calls]
    assert names.index("discover_output_files") < names.index("read_output_file")
    assert "get_project_output" not in names
    assert service.discovered_project_name == str(service.project_file.resolve())
    assert record.result["output_file"] == str((service.project_file.parent / "result.out").resolve())


class GroupedOutputFileService(OutputFileRecordingService):
    async def discover_output_files(
        self,
        project_name: str,
        *,
        started_after: float,
        max_files: int = 100,
    ) -> list[str]:
        self.discovered_project_name = project_name
        self._call("discover_output_files", project_name, started_after, max_files)
        root = Path(project_name).parent
        outputs = []
        for index in range(1, 4):
            output = root / f"result_{index:02d}.out"
            output.write_text("placeholder", encoding="utf-8")
            outputs.append(str(output))
        return outputs


def test_execute_build_treats_legacy_output_parts_as_one_dataset(tmp_path):
    service = GroupedOutputFileService()

    record = asyncio.run(
        execute_build(
            _plan(tmp_path),
            service,
            tmp_path,
            build_id="build-output-parts",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "published"
    assert record.result["output_file"].endswith("result_01.out")
    read_calls = [call for call in service.calls if call[0] == "read_output_file"]
    assert len(read_calls) == 1
    assert read_calls[0][1][0].endswith("result_01.out")


class ExternalOutputFileService(OutputFileRecordingService):
    async def discover_output_files(self, project_name: str, *, started_after: float, max_files: int = 100) -> list[str]:
        self.discovered_project_name = project_name
        self._call("discover_output_files", project_name, started_after, max_files)
        output = Path(project_name).parent.parent / "external.out"
        output.write_text("external", encoding="utf-8")
        return [str(output)]


class InternalSymlinkOutputFileService(OutputFileRecordingService):
    async def discover_output_files(self, project_name: str, *, started_after: float, max_files: int = 100) -> list[str]:
        self.discovered_project_name = project_name
        self._call("discover_output_files", project_name, started_after, max_files)
        output = Path(project_name).parent / "result.out"
        output.write_text("placeholder", encoding="utf-8")
        alias = Path(project_name).parent / "alias.out"
        alias.symlink_to(output)
        return [str(alias)]


class AmbiguousOutputFileService(OutputFileRecordingService):
    async def discover_output_files(self, project_name: str, *, started_after: float, max_files: int = 100) -> list[str]:
        self.discovered_project_name = project_name
        self._call("discover_output_files", project_name, started_after, max_files)
        first = Path(project_name).parent / "first.out"
        second = Path(project_name).parent / "second.out"
        first.write_text("first", encoding="utf-8")
        second.write_text("second", encoding="utf-8")
        return [str(first), str(second)]


class BlockingRunStatusService(RecordingPscadService):
    def __init__(self):
        super().__init__(run_statuses=["running"])
        self.status_started = asyncio.Event()
        self.stopped = False

    async def stop_simulation(self, project_name: str) -> str:
        self._call("stop_simulation", project_name)
        self.stopped = True
        return "stopped"

    async def get_run_status(self, project_name: str) -> dict[str, str]:
        self._call("get_run_status", project_name)
        if self.stopped:
            return {"status": "stopped"}
        self.status_started.set()
        await asyncio.sleep(60)
        return {"status": "running"}


class RunCommandAcknowledgementLostService(RecordingPscadService):
    async def run_project(self, project_name: str) -> str:
        self._call("run_project", project_name)
        raise RuntimeError("run command acknowledgement lost after submission")


def test_execute_build_stops_when_run_command_acknowledgement_is_lost(tmp_path):
    service = RunCommandAcknowledgementLostService()

    record = asyncio.run(
        execute_build(
            _plan(tmp_path),
            service,
            tmp_path,
            build_id="build-run-ack-lost",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    names = [call[0] for call in service.calls]
    assert names.index("run_project") < names.index("stop_simulation")


def test_execute_build_stops_simulation_when_cancelled(tmp_path):
    service = BlockingRunStatusService()

    async def scenario():
        task = asyncio.create_task(
            execute_build(_plan(tmp_path), service, tmp_path, build_id="build-cancelled", poll_interval_s=0)
        )
        await service.status_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    names = [call[0] for call in service.calls]
    assert names.index("run_project") < names.index("stop_simulation")


def test_execute_build_rejects_waveform_outside_staging_ownership(tmp_path):
    record = asyncio.run(
        execute_build(
            _plan(tmp_path),
            ExternalOutputFileService(),
            tmp_path,
            build_id="build-external-output",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_OUTPUT_INCOMPLETE"
    assert record.error["details"]["reason"] == "output_outside_staging"


def test_execute_build_rejects_waveform_symlink_inside_staging(tmp_path):
    probe_target = tmp_path / "symlink-target"
    probe_alias = tmp_path / "symlink-alias"
    probe_target.write_text("probe", encoding="utf-8")
    try:
        probe_alias.symlink_to(probe_target)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    record = asyncio.run(
        execute_build(
            _plan(tmp_path),
            InternalSymlinkOutputFileService(),
            tmp_path,
            build_id="build-internal-symlink-output",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_OUTPUT_INCOMPLETE"
    assert record.error["details"]["reason"] == "output_not_regular"


def test_execute_build_rejects_ambiguous_waveform_candidates(tmp_path):
    record = asyncio.run(
        execute_build(
            _plan(tmp_path),
            AmbiguousOutputFileService(),
            tmp_path,
            build_id="build-ambiguous-output",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_OUTPUT_INCOMPLETE"
    assert record.error["details"]["reason"] == "output_ambiguous"


class MissingOutputSelectorService(RecordingPscadService):
    async def get_output_channels(self, project_name: str) -> list[dict[str, object]]:
        self._call("get_output_channels", project_name)
        return []


class DuplicateOutputSelectorService(RecordingPscadService):
    async def get_output_channels(self, project_name: str) -> list[dict[str, object]]:
        self._call("get_output_channels", project_name)
        return [
            {"path": "Main/VDC", "units": "kV", "call_id": None},
            {"path": "Main/VDC", "units": "kV", "call_id": None},
        ]


class NoOutputMutationService(RecordingPscadService):
    create_output_channel = None


def test_execute_build_rejects_missing_output_creation_capability(tmp_path):
    service = NoOutputMutationService()

    record = asyncio.run(execute_build(_plan(tmp_path), service, tmp_path, build_id="build-no-output-create", poll_interval_s=0))

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_OUTPUT_INCOMPLETE"
    assert record.error["details"]["reason"] == "output_channel_mutation_unavailable"
    assert "run_project" not in [call[0] for call in service.calls]


class EscapingStagingService(RecordingPscadService):
    async def create_project(self, kind: str, filename: str, folder: str, *, confirm: bool = False) -> dict[str, str]:
        self._call("create_project", kind, filename, folder, confirm=confirm)
        return {"name": "outside", "filename": str(Path(folder).parent / "outside.pscx")}


class ExternalReplacementAfterPublicationService(RecordingPscadService):
    async def load_projects(self, filenames: list[str]) -> str:
        result = await super().load_projects(filenames)
        if filenames and Path(filenames[0]).suffix == ".pscx" and Path(filenames[0]).name == "final.pscx":
            Path(filenames[0]).write_text("external replacement", encoding="utf-8")
        return result


def test_execute_build_rejects_backend_staging_path_escape(tmp_path):
    record = asyncio.run(execute_build(_plan(tmp_path), EscapingStagingService(), tmp_path, build_id="build-staging-escape", poll_interval_s=0))

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_POSTCONDITION_FAILED"
    assert not (tmp_path / "outside.pscx").exists()


def test_execute_build_rejects_missing_output_selector_before_simulation(tmp_path):
    service = MissingOutputSelectorService()

    record = asyncio.run(execute_build(_plan(tmp_path), service, tmp_path, build_id="build-missing-output", poll_interval_s=0))

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_OUTPUT_INCOMPLETE"
    names = [call[0] for call in service.calls]
    assert "get_output_channels" in names
    assert "run_project" not in names


def test_execute_build_rejects_ambiguous_output_selector_before_simulation(tmp_path):
    service = DuplicateOutputSelectorService()

    record = asyncio.run(execute_build(_plan(tmp_path), service, tmp_path, build_id="build-duplicate-output", poll_interval_s=0))

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_OUTPUT_INCOMPLETE"
    assert record.error["details"]["matches"] == 2
    assert "run_project" not in [call[0] for call in service.calls]


class MismatchedDefinitionService(RecordingPscadService):
    async def add_canvas_component(self, *args, **kwargs):
        created = await super().add_canvas_component(*args, **kwargs)
        created["definition"] = "master:unexpected"
        return created


class MismatchedTransformerConnectionService(RecordingPscadService):
    async def get_component_parameters(self, project_name, component_id):
        observed = await super().get_component_parameters(project_name, component_id)
        if component_id == 1:
            observed["Connection"] = "Y-Y"
        return observed


class MismatchedOrientationService(RecordingPscadService):
    async def add_canvas_component(self, *args, **kwargs):
        created = await super().add_canvas_component(*args, **kwargs)
        created["orientation"] = 7
        return created


class MismatchedConnectionService(RecordingPscadService):
    async def create_connection(self, *args, **kwargs):
        created = await super().create_connection(*args, **kwargs)
        created["p1"] = [999, 999]
        return created


class StrictConnectionArgumentService(RecordingPscadService):
    async def create_connection(
        self,
        project_name,
        p1,
        p2,
        label,
        electrical,
        *,
        canvas_name="Main",
    ):
        if (label is None) != (electrical is None):
            raise ValueError(
                "label and electrical must either both be provided or both omitted"
            )
        return await super().create_connection(
            project_name,
            p1,
            p2,
            label,
            electrical,
            canvas_name=canvas_name,
        )


def test_two_point_unlabeled_net_omits_electrical_flag(tmp_path):
    service = StrictConnectionArgumentService()

    record = asyncio.run(
        execute_build(
            _plan_with_connection(tmp_path),
            service,
            tmp_path,
            build_id="build-unlabeled-connection",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "published"
    connection = next(call for call in service.calls if call[0] == "create_connection")
    assert connection[1][3:5] == (None, None)


class SnappedCompanionPortService(RecordingPscadService):
    async def add_canvas_component(self, *args, **kwargs):
        created = await super().add_canvas_component(*args, **kwargs)
        component = self.components[created["id"]]
        component["x"] = round(component["x"] / 18) * 18
        component["y"] = round(component["y"] / 18) * 18
        created["location"] = {"x": component["x"], "y": component["y"]}
        return created

    async def get_component_ports(self, project_name, component_id):
        self._call("get_component_ports", project_name, component_id)
        component = self.components[component_id]
        return [
            {
                "name": "ACD_A",
                "x": component["x"] - 72,
                "y": component["y"] - 36,
                "dim": 1,
                "type": "electrical",
            }
        ]


class RealDataCompanionPortService(SnappedCompanionPortService):
    async def get_component_ports(self, project_name, component_id):
        self._call("get_component_ports", project_name, component_id)
        component = self.components[component_id]
        return [
            {
                "name": "AM_D",
                "x": component["x"] + 72,
                "y": component["y"] + 45,
                "dim": 1,
                "type": "Real",
            }
        ]


def test_companion_port_readback_uses_verified_snapped_component_origin(tmp_path):
    service = SnappedCompanionPortService()
    executor = LccExecutor(
        _plan(tmp_path),
        service,
        tmp_path,
        asset_set=load_packaged_asset_set(),
    )
    operation = LccPlanOperation(
        1,
        "place_component",
        "rectifier_bridge",
        {
            "definition": "cigre_lcc_v1:LCC12PulseBridge",
            "location": [800, 210],
            "orientation": 0,
            "parameters": {"UP": 1},
            "ports": ["ACD_A"],
            "canvas": "Main",
        },
        "place_power:rectifier_bridge:000",
        "place_power",
    )

    asyncio.run(executor._place_component(operation))

    assert executor.component_ids["rectifier_bridge"] == 1
    assert service.components[1]["x"] == 792
    assert service.components[1]["y"] == 216


def test_companion_real_port_readback_matches_data_contract(tmp_path):
    service = RealDataCompanionPortService()
    executor = LccExecutor(
        _plan(tmp_path),
        service,
        tmp_path,
        asset_set=load_packaged_asset_set(),
    )
    operation = LccPlanOperation(
        1,
        "place_component",
        "rectifier_bridge",
        {
            "definition": "cigre_lcc_v1:LCC12PulseBridge",
            "location": [800, 210],
            "orientation": 0,
            "parameters": {"UP": 1},
            "ports": ["AM_D"],
            "canvas": "Main",
        },
        "place_power:rectifier_bridge:000",
        "place_power",
    )

    asyncio.run(executor._place_component(operation))

    assert executor.component_ids["rectifier_bridge"] == 1


@pytest.mark.parametrize(
    ("service_type", "reason"),
    [
        (MismatchedDefinitionService, "definition"),
        (MismatchedOrientationService, "orientation"),
    ],
)
def test_execute_build_rejects_component_identity_drift(tmp_path, service_type, reason):
    service = service_type()

    record = asyncio.run(
        execute_build(
            _plan(tmp_path),
            service,
            tmp_path,
            build_id=f"build-component-{reason}",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_POSTCONDITION_FAILED"
    assert reason in record.error["details"]
    assert "run_project" not in [call[0] for call in service.calls]


def test_execute_build_verifies_transformer_connection_readback(tmp_path):
    plan = _plan(tmp_path)
    components = list(plan.blueprint.components)
    components[0] = replace(
        components[0],
        definition="master:converter_transformer",
        parameters={"LogicalId": "source", "Connection": "Y-delta"},
    )
    operations = []
    for operation in plan.operations:
        if operation.target == "source" and operation.kind in {
            "place_component",
            "verify_parameters",
        }:
            arguments = dict(operation.arguments)
            arguments["definition"] = "master:converter_transformer"
            arguments["parameters"] = {
                "LogicalId": "source",
                "Connection": "Y-delta",
            }
            operation = replace(operation, arguments=arguments)
        operations.append(operation)
    plan = replace(
        plan,
        blueprint=replace(plan.blueprint, components=tuple(components)),
        operations=tuple(operations),
    )
    service = MismatchedTransformerConnectionService()

    record = asyncio.run(
        execute_build(
            plan,
            service,
            tmp_path,
            build_id="build-transformer-connection",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_PARAMETER_MISMATCH"
    assert "run_project" not in [call[0] for call in service.calls]


def test_execute_build_rejects_connection_endpoint_drift(tmp_path):
    service = MismatchedConnectionService()

    record = asyncio.run(
        execute_build(
            _plan_with_connection(tmp_path),
            service,
            tmp_path,
            build_id="build-connection-endpoint",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_POSTCONDITION_FAILED"
    assert "run_project" not in [call[0] for call in service.calls]


def test_execute_build_fails_closed_when_staging_path_already_exists(tmp_path):
    plan = _plan(tmp_path)
    staging = Path(plan.staging_path)
    staging.mkdir(parents=True)

    record = asyncio.run(
        execute_build(plan, RecordingPscadService(), tmp_path, build_id="build-stale-staging", poll_interval_s=0)
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_BUILD_CONFLICT"
    assert not (tmp_path / "final.pscx").exists()


def test_execute_build_never_quarantines_a_preexisting_final_target(tmp_path):
    plan = _plan(tmp_path)
    target = Path(plan.target_path)
    target.write_text("external", encoding="utf-8")

    record = asyncio.run(
        execute_build(plan, RecordingPscadService(), tmp_path, build_id="build-external-target", poll_interval_s=0)
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_BUILD_CONFLICT"
    assert target.read_text(encoding="utf-8") == "external"


def test_execute_build_never_quarantines_a_replaced_published_target(tmp_path):
    plan = _plan(tmp_path)
    target = Path(plan.target_path)

    record = asyncio.run(
        execute_build(
            plan,
            ExternalReplacementAfterPublicationService(),
            tmp_path,
            build_id="build-replaced-final",
            poll_interval_s=0,
        )
    )

    assert record.state.value == "failed"
    assert target.read_text(encoding="utf-8") == "external replacement"
    cleanup = [entry for entry in record.history if "publication_cleanup" in entry]
    assert cleanup[-1]["publication_cleanup"]["action"] == "preserved_external_replacement"


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


def test_execute_build_stops_simulation_before_reporting_timeout(tmp_path):
    service = RecordingPscadService(run_statuses=["running", "running"])
    record = asyncio.run(
        execute_build(
            _plan(tmp_path),
            service,
            tmp_path,
            build_id="build-timeout-stop",
            poll_interval_s=0,
            timeout_s=0,
        )
    )

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_BUILD_TIMED_OUT"
    names = [call[0] for call in service.calls]
    assert names.index("run_project") < names.index("stop_simulation")


def test_execute_build_without_assets_cannot_fabricate_acceptance_pass(tmp_path):
    record = asyncio.run(_execute_build(_plan(tmp_path), RecordingPscadService(), tmp_path, build_id="build-no-assets"))

    assert record.state.value == "failed"
    assert record.error["code"] == "LCC_ACCEPTANCE_FAILED"
    assert record.result["verdict"] == "INCOMPLETE_ANALYSIS"


def test_legacy_project_settings_map_seconds_to_pscad_46_microseconds():
    mapped = _legacy_project_settings(
        {
            "simulation_duration_s": 1.0,
            "time_step_s": 0.00005,
            "output_step_s": 0.00025,
            "output_enabled": True,
            "compiler_target": "fortran",
        }
    )
    assert mapped == {
        "time_duration": 1.0,
        "time_step": 50,
        "sample_step": 250,
        "PlotType": 1,
    }
