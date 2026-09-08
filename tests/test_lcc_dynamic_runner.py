from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.dynamic_runner import (
    DynamicLccRunRequest,
    run_fixed_lcc_dynamic_acceptance,
)
from tests.lcc_dynamic_fakes import PassingDynamicBuilder, PassingDynamicService


def valid_request(tmp_path: Path) -> tuple[DynamicLccRunRequest, Path]:
    repo = tmp_path / "repo"
    workspace = tmp_path / "workspace"
    staging = workspace / "staging"
    repo.mkdir()
    staging.mkdir(parents=True)
    asset_root = repo / "pscad_mcp" / "assets" / "lcc" / "cigre_lcc_monopole_v1"
    (asset_root / "library").mkdir(parents=True)
    for name in ("blueprint.json", "catalog-pscad-4.6.2.json", "dynamic.json", "master-bindings-pscad-4.6.2.json", "manifest.json", "cigre_lcc_v1.pslx"):
        path = asset_root / ("library" if name.endswith(".pslx") else "") / name
        path.write_text((Path(__file__).parents[1] / "pscad_mcp" / "assets" / "lcc" / "cigre_lcc_monopole_v1" / name).read_text(encoding="utf-8") if name == "dynamic.json" else "{}", encoding="utf-8")
    master = repo / "Master.psdx"
    compiler_cfg = repo / "compiler.cfg"
    compiler_exe = repo / "compiler.exe"
    for path in (master, compiler_cfg, compiler_exe):
        path.write_text("x", encoding="utf-8")
    source_paths = {
        "blueprint": asset_root / "blueprint.json", "catalog": asset_root / "catalog-pscad-4.6.2.json", "dynamic": asset_root / "dynamic.json", "registry": asset_root / "master-bindings-pscad-4.6.2.json", "manifest": asset_root / "manifest.json", "companion": asset_root / "library" / "cigre_lcc_v1.pslx", "master": master, "compiler_configuration": compiler_cfg, "compiler_executable": compiler_exe,
    }
    snapshot = {name: {"path": str(path.absolute()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for name, path in source_paths.items()}
    preflight_hash = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    (staging / "run_01.out").write_text("out", encoding="utf-8")
    (staging / "run.inf").write_text("inf", encoding="utf-8")
    report = workspace / "report.json"
    request = DynamicLccRunRequest(
        repository_root=repo,
        workspace_root=workspace,
        master_path=master,
        compiler_configuration=compiler_cfg,
        compiler_executable=compiler_exe,
        report_path=report,
        commit="a" * 40,
        branch="codex/wp1c",
        preflight={"status": "PASS", "sha256": preflight_hash, "snapshot": snapshot},
    )
    return request, staging


@pytest.mark.parametrize("record_shape", ["plan", "journal", "started", "outside"])
def test_runner_resolves_real_published_artifact_records(tmp_path, record_shape):
    request, staging = valid_request(tmp_path)

    class NativeRecordBuilder(PassingDynamicBuilder):
        async def build_model(self, **kwargs):
            result = await super().build_model(**kwargs)
            original = Path(result["project_path"])
            self.final = (tmp_path if record_shape == "outside" else original.parent) / "WP1C_FIXED_LCC_PUBLISHED.pscx"
            original.rename(self.final)
            self.library = request.workspace_root / ".pscad-mcp" / "libraries" / "cigre_lcc_v1.pslx"
            self.library.parent.mkdir(parents=True)
            Path(result["library_path"]).rename(self.library)
            return {"build_id": "build-1", **({"target_path": str(self.final)} if record_shape == "started" else {})}

        def get_build_status(self, build_id):
            record = super().get_build_status(build_id)
            if record_shape in {"plan", "outside"}:
                record["plan"] = {"target_path": str(self.final)}
            elif record_shape == "journal":
                record["target_path"] = str(self.final)
            return record

    report = asyncio.run(run_fixed_lcc_dynamic_acceptance(
        request, service=PassingDynamicService(staging), builder=NativeRecordBuilder(staging),
        process_reader=list, poll_interval_s=0,
    ))
    if record_shape == "outside":
        assert report["status"] == "FAIL"
        assert "contained regular file" in report["failure"]["message"]
    else:
        assert report["engineering_verdict"] == "PASS"
        assert Path(report["artifacts"]["project"]["path"]).name == "WP1C_FIXED_LCC_PUBLISHED.pscx"
        assert Path(report["artifacts"]["library"]["path"]) == request.workspace_root / ".pscad-mcp" / "libraries" / "cigre_lcc_v1.pslx"


def test_runner_rederives_output_and_persists_incomplete_success(tmp_path: Path):
    request, staging = valid_request(tmp_path)
    service = PassingDynamicService(staging)
    report = asyncio.run(
        run_fixed_lcc_dynamic_acceptance(
            request,
            service=service,
            builder=PassingDynamicBuilder(staging),
            process_reader=list,
            poll_interval_s=0,
        )
    )
    assert report["engineering_verdict"] == "PASS"
    assert report["golden_verdict"] == "INCOMPLETE_ANALYSIS"
    assert report["status"] == "INCOMPLETE_ANALYSIS"
    assert report["dynamic"]["evidence_source"] == "raw_pscad_output"
    assert report["runtime"]["remaining_processes"] == []
    assert report["artifacts"]["project"]["sha256"]
    assert report["artifacts"]["library"]["sha256"]
    assert ("output", True) in service.calls


@pytest.mark.parametrize("artifact_case", ["published", "hash_drift", "staging_hash"])
def test_runner_binds_final_project_path_to_its_publication_hash(tmp_path, artifact_case):
    request, staging = valid_request(tmp_path)

    class PublishedBuilder(PassingDynamicBuilder):
        async def build_model(self, **kwargs):
            started = await super().build_model(**kwargs)
            self.final = request.workspace_root / "WP1C_FIXED_LCC_PUBLISHED.pscx"
            Path(started["project_path"]).rename(self.final)
            self.final.write_text("published project", encoding="utf-8")
            if artifact_case != "staging_hash":
                started.pop("project_path")
                started.pop("project_sha256")
            return started

        def get_build_status(self, build_id):
            record = super().get_build_status(build_id)
            record["plan"] = {"target_path": str(self.final)}
            if artifact_case != "staging_hash":
                record["history"][-1].update({
                    "target_path": str(self.final),
                    "final_project_sha256": hashlib.sha256(self.final.read_bytes()).hexdigest(),
                })
            if artifact_case == "hash_drift":
                self.final.write_text("changed after publication", encoding="utf-8")
            return record

    report = asyncio.run(run_fixed_lcc_dynamic_acceptance(
        request, service=PassingDynamicService(staging), builder=PublishedBuilder(staging),
        process_reader=list, poll_interval_s=0,
    ))
    if artifact_case == "hash_drift":
        assert report["status"] == "FAIL"
        assert "project artifact hash mismatch" in report["failure"]["message"]
    else:
        assert report["engineering_verdict"] == "PASS"
        final = request.workspace_root / "WP1C_FIXED_LCC_PUBLISHED.pscx"
        assert report["artifacts"]["project"] == {
            "path": str(final), "sha256": hashlib.sha256(final.read_bytes()).hexdigest(),
        }


def test_runner_rediscovers_outputs_from_the_actual_staging_project(tmp_path):
    from pscad_mcp.core.path_policy import PathPolicy
    from pscad_mcp.core.service import PscadService

    request, staging = valid_request(tmp_path)
    native_staging = request.workspace_root / ".pscad-mcp" / "lcc-builds" / f"{request.project_name}.staging"
    generated = native_staging / f"{request.project_name}.gf42"
    discovery = PscadService(
        lambda: object(), path_policy=PathPolicy(workspace_root=str(request.workspace_root)),
    )

    class NativeBuilder(PassingDynamicBuilder):
        async def build_model(self, **kwargs):
            started = await super().build_model(**kwargs)
            generated.mkdir(parents=True)
            (native_staging / f"{request.project_name}.pscx").write_text("staging project", encoding="utf-8")
            for name in ("run_01.out", "run.inf"):
                (staging / name).rename(generated / name)
            self.final = request.workspace_root / f"{request.project_name}_PUBLISHED.pscx"
            Path(started["project_path"]).rename(self.final)
            return started

        def get_build_status(self, build_id):
            record = super().get_build_status(build_id)
            record["plan"] = {"target_path": str(self.final), "staging_path": str(native_staging)}
            return record

    class NativeDiscoveryService(PassingDynamicService):
        async def discover_output_files(self, project_name, **kwargs):
            return await discovery.discover_output_files(project_name, **kwargs)

        async def read_output_file(self, file_path, **kwargs):
            output = await self.get_project_output(request.project_name, summary_only=False)
            return {**output, "output_file": file_path}

    report = asyncio.run(run_fixed_lcc_dynamic_acceptance(
        request, service=NativeDiscoveryService(staging), builder=NativeBuilder(staging),
        process_reader=list, poll_interval_s=0,
    ))
    assert report["engineering_verdict"] == "PASS", report["failure"]
    assert Path(report["artifacts"]["selected_output"]["path"]) == generated / "run_01.out"


@pytest.mark.parametrize("artifact_case", ["valid", "valid_two_parts", "hash_drift", "outside_workspace", "stale", "pass_only", "metadata_drift", "new_part"])
def test_runner_preserves_failed_engineering_checks_with_verified_output(
    tmp_path: Path, artifact_case: str,
):
    from pscad_mcp.hvdc.builders.lcc.dynamic_evidence import derive_fixed_lcc_dynamic_evidence
    from tests.lcc_dynamic_fakes import dynamic_contract, passing_raw_channels

    request, staging = valid_request(tmp_path)
    raw = passing_raw_channels()
    current = next(channel for channel in raw["channels"] if channel["path"] == "Main/IDC")
    current["values"] = [4.0 if 0.8 <= t < 0.9 else 1.0 for t in current["domain"]]
    dynamic = derive_fixed_lcc_dynamic_evidence(raw, dynamic_contract())
    assert dynamic["checks"]["bounded_dc_response"]["outcome"] == "FAIL"
    if artifact_case == "pass_only":
        dynamic = derive_fixed_lcc_dynamic_evidence(passing_raw_channels(), dynamic_contract())
    physical = {"verdict": "PASS", "physical_checks": [
        {"name": "polarity", "kind": "physical", "required": True, "status": "observed", "outcome": "PASS"},
    ]}

    class FailedEngineeringBuilder(PassingDynamicBuilder):
        def get_build_status(self, build_id: str):
            output = staging / "run_01.out"
            if artifact_case == "stale":
                os.utime(output, (1, 1))
            if artifact_case == "outside_workspace":
                output = tmp_path / "outside_01.out"
                output.write_text("outside", encoding="utf-8")
            digest = hashlib.sha256(output.read_bytes()).hexdigest()
            metadata = staging / "run.inf"
            metadata_hash = hashlib.sha256(metadata.read_bytes()).hexdigest()
            if artifact_case == "metadata_drift":
                metadata.write_text("different channel selectors", encoding="utf-8")
            if artifact_case == "new_part":
                (staging / "run_02.out").write_text("unbound extra part", encoding="utf-8")
            acceptance = {
                "dynamic": dynamic, "physical": physical,
                "output_file": str(output),
                "output_artifacts": [{
                    "path": str(output),
                    "sha256": "0" * 64 if artifact_case == "hash_drift" else digest,
                }],
                "output_metadata_artifacts": [{"path": str(metadata), "sha256": metadata_hash}],
            }
            if artifact_case == "valid_two_parts":
                second = staging / "run_02.out"
                second.write_text("second part", encoding="utf-8")
                acceptance["output_artifacts"].append({
                    "path": str(second), "sha256": hashlib.sha256(second.read_bytes()).hexdigest(),
                })
            return {
                "state": "failed",
                "history": [{"state": state} for state in ("compiled", "simulated", "failed")],
                "error": {
                    "code": "LCC_DYNAMIC_ACCEPTANCE_FAILED",
                    "message": "The dynamic engineering contract did not pass.",
                    "details": {"acceptance": acceptance},
                },
            }

    report = asyncio.run(run_fixed_lcc_dynamic_acceptance(
        request, service=PassingDynamicService(staging),
        builder=FailedEngineeringBuilder(staging), process_reader=list, poll_interval_s=0,
    ))
    assert report["status"] == "FAIL"
    assert report["failure"]["code"] == "LCC_DYNAMIC_ACCEPTANCE_FAILED"
    assert report["build"]["terminal_state"] == "failed"
    if artifact_case not in {"valid", "valid_two_parts"}:
        assert report["dynamic"]["checks"] == {}
        assert report["artifacts"]["output_parts"] == []
        return
    assert report["dynamic"]["checks"] == dynamic["checks"]
    assert report["physical"]["checks"] == physical["physical_checks"]
    assert report["artifacts"]["selected_output"]["path"] == str((staging / "run_01.out").absolute())
    assert report["artifacts"]["output_metadata"][0]["sha256"] == hashlib.sha256((staging / "run.inf").read_bytes()).hexdigest()
    assert json.loads(request.report_path.read_text())["dynamic"] == report["dynamic"]


def test_runner_static_preflight_failure_writes_fail_without_build(tmp_path: Path):
    request, staging = valid_request(tmp_path)
    request = DynamicLccRunRequest(**{**request.__dict__, "preflight": {"status": "FAIL", "sha256": "a" * 64, "snapshot": {}}})
    builder = PassingDynamicBuilder(staging)
    report = asyncio.run(run_fixed_lcc_dynamic_acceptance(request, service=PassingDynamicService(staging), builder=builder, process_reader=list, poll_interval_s=0))
    assert report["status"] == "FAIL"
    assert report["failure"]["stage"] == "setup"
    assert report["failure"]["code"] == "LCC_DYNAMIC_PREFLIGHT_FAILED"
    assert builder.plan_calls == []
    assert builder.build_calls == []
    assert report["runtime"]["managed_pid"] is None


def test_runner_preflight_snapshot_mismatch_stops_before_attach(tmp_path: Path):
    request, staging = valid_request(tmp_path)
    snapshot = {name: {"path": str(path), "sha256": "a" * 64} for name, path in []}
    snapshot = {"dynamic": {"path": str(request.repository_root / "pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/dynamic.json"), "sha256": "0" * 64}}
    request = DynamicLccRunRequest(**{**request.__dict__, "preflight": {"status": "PASS", "sha256": "a" * 64, "snapshot": snapshot}})
    service = PassingDynamicService(staging)
    builder = PassingDynamicBuilder(staging)
    report = asyncio.run(run_fixed_lcc_dynamic_acceptance(request, service=service, builder=builder, process_reader=list, poll_interval_s=0))
    assert report["status"] == "FAIL"
    assert service.attached is False
    assert builder.plan_calls == []


def test_runner_preserves_existing_report_sentinel(tmp_path: Path):
    request, staging = valid_request(tmp_path)
    request.report_path.write_bytes(b"sentinel")
    service = PassingDynamicService(staging)
    builder = PassingDynamicBuilder(staging)
    report = asyncio.run(run_fixed_lcc_dynamic_acceptance(request, service=service, builder=builder, process_reader=list, poll_interval_s=0))
    assert report["status"] == "FAIL"
    assert request.report_path.read_bytes() == b"sentinel"
    assert not service.attached and builder.plan_calls == []


def test_runner_process_reader_exception_fails_before_attach(tmp_path: Path):
    request, staging = valid_request(tmp_path)
    service = PassingDynamicService(staging)
    builder = PassingDynamicBuilder(staging)
    def broken_reader():
        raise RuntimeError("probe failed")
    report = asyncio.run(run_fixed_lcc_dynamic_acceptance(request, service=service, builder=builder, process_reader=broken_reader, poll_interval_s=0))
    assert report["status"] == "FAIL"
    assert report["failure"]["stage"] == "setup"
    assert not service.attached and builder.plan_calls == []


class _ConfigurableService(PassingDynamicService):
    def __init__(self, staging: Path, *, failure: str | None = None, managed_pid: int | None = None):
        super().__init__(staging)
        self.failure = failure
        self.managed_pid = managed_pid

    async def attach_local(self):
        if self.failure == "attach":
            raise BackendError("ATTACH_FAILED", "attach failed", "fake", "attach_local")
        await super().attach_local()

    async def status(self):
        status = await super().status()
        status["session"]["managed_pid"] = self.managed_pid
        return status

    async def get_project_output(self, project_name: str, *, summary_only: bool = True):
        output = await super().get_project_output(project_name, summary_only=summary_only)
        if self.failure == "output_missing":
            output.pop("output_file", None)
        elif self.failure == "output_stale":
            stale = self.staging / "run_01.out"
            os.utime(stale, (1, 1))
        elif self.failure == "output_symlink":
            # The symlink is installed by the test before the runner starts;
            # this branch only documents the scenario under test.
            pass
        return output

    async def quit_pscad(self, *, confirm: bool = False):
        if self.failure == "quit":
            raise RuntimeError("quit failed")
        await super().quit_pscad(confirm=confirm)


class _ConfigurableBuilder(PassingDynamicBuilder):
    def __init__(self, staging: Path, *, failure: str | None = None, published_result: dict | None = None):
        super().__init__(staging)
        self.failure = failure
        self.published_result = published_result

    def plan_model(self, **kwargs):
        if self.failure == "plan":
            raise BackendError("PLAN_FAILED", "plan failed", "fake", "plan_model")
        return super().plan_model(**kwargs)

    async def build_model(self, **kwargs):
        if self.failure == "build":
            raise BackendError("BUILD_FAILED", "build failed", "fake", "build_model")
        result = await super().build_model(**kwargs)
        if self.failure == "build_timeout":
            for output in (self.staging / "run_01.out", self.staging / "run.inf"):
                os.utime(output, (1, 1))
        if self.failure == "source_drift":
            (self.staging.parent.parent / "repo" / "Master.psdx").write_text("drift", encoding="utf-8")
        return result

    def get_build_status(self, build_id: str):
        if self.failure == "build_timeout":
            return {"state": "running", "history": [{"state": "validated"}]}
        record = super().get_build_status(build_id)
        if self.published_result is not None:
            record["result"] = self.published_result
        return record

    async def shutdown(self, *, timeout_s: float = 5.0):
        if self.failure == "shutdown":
            raise RuntimeError("shutdown failed")
        await super().shutdown(timeout_s=timeout_s)


def _assert_failure(report: dict, *, stage: str, code: str) -> None:
    assert report["status"] == "FAIL"
    assert report["failure"] == {
        "stage": stage,
        "code": code,
        "message": report["failure"]["message"],
    }


@pytest.mark.parametrize(
    ("service_failure", "builder_failure", "stage", "code"),
    [
        ("attach", None, "attach", "ATTACH_FAILED"),
        (None, "plan", "plan", "PLAN_FAILED"),
        (None, "build", "build", "BUILD_FAILED"),
        (None, "build_timeout", "poll", "LCC_BUILD_TIMED_OUT"),
    ],
)
def test_runner_lifecycle_failures_are_persisted_without_pscad(
    tmp_path: Path, service_failure: str | None, builder_failure: str | None, stage: str, code: str
):
    request, staging = valid_request(tmp_path)
    service = _ConfigurableService(staging, failure=service_failure)
    builder = _ConfigurableBuilder(staging, failure=builder_failure)
    report = asyncio.run(
        run_fixed_lcc_dynamic_acceptance(
            request, service=service, builder=builder, process_reader=list, poll_interval_s=0, timeout_s=0
        )
    )
    _assert_failure(report, stage=stage, code=code)
    assert request.report_path.exists()
    if stage == "attach":
        assert builder.plan_calls == []
    elif stage == "plan":
        assert builder.build_calls == []


def test_runner_filters_operation_history_and_preserves_terminal_build_error(
    tmp_path: Path,
):
    request, staging = valid_request(tmp_path)

    class FailedBuilder(_ConfigurableBuilder):
        def get_build_status(self, build_id: str):
            return {
                "state": "failed",
                "history": [
                    {"state": "validated"},
                    {"kind": "place_component", "target": "source"},
                    {"state": "failed", "reason": "LCC_OUTPUT_INCOMPLETE"},
                ],
                "error": {
                    "backend": "hvdc",
                    "code": "LCC_OUTPUT_INCOMPLETE",
                    "details": {"selector": "Main/VDC_RECT"},
                    "message": "The PSCAD output-channel metadata could not be verified.",
                    "operation": "verify_lcc_output_channel",
                },
            }

    report = asyncio.run(
        run_fixed_lcc_dynamic_acceptance(
            request,
            service=_ConfigurableService(staging),
            builder=FailedBuilder(staging),
            process_reader=list,
            poll_interval_s=0,
        )
    )

    _assert_failure(report, stage="poll", code="LCC_OUTPUT_INCOMPLETE")
    assert report["build"]["history"] == ["validated", "failed"]
    assert request.report_path.is_file()


@pytest.mark.parametrize(
    ("service_failure", "stage", "code"),
    [
        ("output_missing", "output", "LCC_DYNAMIC_RUN_FAILED"),
        ("output_stale", "output", "LCC_DYNAMIC_RUN_FAILED"),
        ("output_symlink", "output", "LCC_DYNAMIC_RUN_FAILED"),
    ],
)
def test_runner_rejects_missing_stale_or_symlinked_output(
    tmp_path: Path, service_failure: str, stage: str, code: str, monkeypatch: pytest.MonkeyPatch
):
    request, staging = valid_request(tmp_path)
    if service_failure == "output_symlink":
        original_is_symlink = Path.is_symlink

        def fake_is_symlink(path: Path) -> bool:
            return path.name == "run.inf" or original_is_symlink(path)

        monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)
    report = asyncio.run(
        run_fixed_lcc_dynamic_acceptance(
            request,
            service=_ConfigurableService(staging, failure=service_failure),
            builder=_ConfigurableBuilder(staging),
            process_reader=list,
            poll_interval_s=0,
        )
    )
    _assert_failure(report, stage=stage, code=code)


@pytest.mark.parametrize("published_failure", ["dynamic_missing", "dynamic_mismatch", "physical_missing", "physical_malformed"])
def test_runner_rejects_untrusted_published_results(tmp_path: Path, published_failure: str):
    request, staging = valid_request(tmp_path)
    passing = _ConfigurableBuilder(staging).get_build_status("build-1")["result"]
    if published_failure == "dynamic_missing":
        passing.pop("dynamic")
    elif published_failure == "dynamic_mismatch":
        passing["dynamic"] = {"engineering_verdict": "PASS", "checks": {}}
    elif published_failure == "physical_missing":
        passing.pop("physical")
    else:
        passing["physical"] = {"verdict": "PASS", "physical_checks": {}}
    report = asyncio.run(
        run_fixed_lcc_dynamic_acceptance(
            request,
            service=_ConfigurableService(staging),
            builder=_ConfigurableBuilder(staging, published_result=passing),
            process_reader=list,
            poll_interval_s=0,
        )
    )
    _assert_failure(report, stage="derive", code="LCC_DYNAMIC_EVIDENCE_MISMATCH")


def test_runner_cleanup_errors_and_source_drift_are_failures(tmp_path: Path):
    request, staging = valid_request(tmp_path)
    report = asyncio.run(
        run_fixed_lcc_dynamic_acceptance(
            request,
            service=_ConfigurableService(staging, failure="quit"),
            builder=_ConfigurableBuilder(staging, failure="shutdown"),
            process_reader=list,
            poll_interval_s=0,
        )
    )
    _assert_failure(report, stage="cleanup", code="RuntimeError")
    assert report["runtime"]["quit_error"] == "shutdown failed"

    drift_root = tmp_path / "drift"
    drift_root.mkdir()
    request, staging = valid_request(drift_root)
    report = asyncio.run(
        run_fixed_lcc_dynamic_acceptance(
            request,
            service=_ConfigurableService(staging),
            builder=_ConfigurableBuilder(staging, failure="source_drift"),
            process_reader=list,
            poll_interval_s=0,
        )
    )
    _assert_failure(report, stage="cleanup", code="RuntimeError")
    assert report["sources"]["master"]["before"] != report["sources"]["master"]["after"]


def test_runner_terminates_only_managed_pid_and_ignores_spoofed_ownership(tmp_path: Path):
    request, staging = valid_request(tmp_path)
    terminated: list[int] = []
    snapshots = [
        [],
        [
            {"pid": 123, "runner_owned": False, "run_id": "spoof"},
            {"pid": 456, "runner_owned": True, "run_id": "spoof"},
        ],
        [{"pid": 456, "runner_owned": True, "run_id": "spoof"}],
    ]

    def process_reader():
        return snapshots.pop(0) if snapshots else []

    def process_terminator(pid: int):
        terminated.append(pid)

    report = asyncio.run(
        run_fixed_lcc_dynamic_acceptance(
            request,
            service=_ConfigurableService(staging, managed_pid=123),
            builder=_ConfigurableBuilder(staging),
            process_reader=process_reader,
            process_terminator=process_terminator,
            poll_interval_s=0,
        )
    )
    assert report["status"] == "INCOMPLETE_ANALYSIS"
    assert terminated == [123]
    assert report["runtime"]["remaining_processes"] == []
