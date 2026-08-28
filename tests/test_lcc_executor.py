from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from pscad_mcp.hvdc.builders.lcc.executor import execute_build as _execute_build
from pscad_mcp.hvdc.builders.lcc.executor import LccExecutor
from pscad_mcp.hvdc.builders.lcc.assets import load_packaged_asset_set
from pscad_mcp.hvdc.builders.lcc.models import (
    LccBlueprint,
    LccBuildPlan,
    LccComponentSpec,
    LccPlanOperation,
)

from tests.lcc_builder_fakes import RecordingPscadService


def execute_build(*args, **kwargs):
    kwargs.setdefault("allow_test_double", True)
    return _execute_build(*args, **kwargs)


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
    assert record.error["code"] == "LCC_STRUCTURE_INVALID"
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
