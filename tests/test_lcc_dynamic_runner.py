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
