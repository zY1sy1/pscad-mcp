from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError

COMMIT = "a" * 40
HASH = "b" * 64
PREFLIGHT_SNAPSHOT = {"status": "PASS", "checks": {"repository": "PASS"}}
PREFLIGHT_HASH = hashlib.sha256(
    json.dumps(
        PREFLIGHT_SNAPSHOT,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
).hexdigest()
SUCCESS_HISTORY = [
    "validated",
    "staging_created",
    "compiled",
    "simulated",
    "acceptance_passed",
    "published",
]


def valid_report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": "native-run-1",
        "scope": "lcc.blank_native",
        "builder_path": "lcc.blank_native",
        "kind": "licensed_simulation",
        "capability_state": "simulated",
        "commit": COMMIT,
        "generated_at_utc": "2026-08-30T01:00:00Z",
        "status": "PASS",
        "repository": {
            "branch": "codex/lcc-wp1a",
            "commit": COMMIT,
            "clean": True,
        },
        "preflight": {
            "status": "PASS",
            "sha256": PREFLIGHT_HASH,
            "snapshot": PREFLIGHT_SNAPSHOT,
        },
        "sources": {
            "template": {
                "path": "D:/official.pscx",
                "before": HASH,
                "after": HASH,
            },
            "master": {
                "path": "C:/PSCAD46/master.pslx",
                "before": HASH,
                "after": HASH,
            },
            "registry": {
                "path": "D:/repo/master-bindings.json",
                "file_sha256": HASH,
                "registry_sha256": "c" * 64,
            },
            "asset_manifest": {"path": "D:/repo/manifest.json", "sha256": HASH},
        },
        "build": {
            "project_name": "WP1A_NATIVE_LCC",
            "workspace": "D:/PSCAD-Workspace/lcc-wp1a/run-1",
            "build_id": "build-1",
            "plan_hash": HASH,
            "journal_path": "D:/run/journal.json",
            "journal_sha256": HASH,
            "history": SUCCESS_HISTORY,
            "terminal_state": "published",
        },
        "artifacts": {
            "project": {"path": "D:/run/case.pscx", "sha256": HASH},
            "library": {"path": "D:/run/cigre_lcc_v1.pslx", "sha256": HASH},
            "scenario": {
                "path": "D:/run/case_scenario_source.pscx",
                "sha256": HASH,
            },
            "selected_output": {"path": "D:/run/case_01.out", "sha256": HASH},
            "output_parts": [{"path": "D:/run/case_01.out", "sha256": HASH}],
            "output_metadata": [],
        },
        "acceptance": {
            "verdict": "PASS",
            "checks": {
                "disturbance": True,
                "failure_indication": True,
                "bounded_dc_response": True,
                "recovered": True,
            },
            "evidence": {
                "fault_time_s": 0.8,
                "fault_duration_s": 0.1,
                "current_limit_pu": 3.0,
                "dc_current_peak_pu": 2.5,
                "recovery_window_s": 0.5,
                "channels": {
                    "fault_active": {
                        "path": "Fault/LCC Fault Active",
                        "units": "state",
                        "samples": 5,
                        "domain_start_s": 0.0,
                        "domain_end_s": 2.0,
                    },
                    "dc_current": {
                        "path": "Inverter/DC Current",
                        "units": "pu",
                        "samples": 5,
                        "domain_start_s": 0.0,
                        "domain_end_s": 2.0,
                    },
                    "failure_indicator": {
                        "path": "Inverter/Gamma",
                        "units": "deg",
                        "samples": 5,
                        "domain_start_s": 0.0,
                        "domain_end_s": 2.0,
                    },
                },
            },
        },
        "runtime": {
            "backend": "legacy",
            "version": "4.6.2",
            "x64": True,
            "licensed": True,
            "managed_pid": 1234,
            "quit_error": None,
            "remaining_processes": [],
        },
        "explicit_exclusions": [
            "fixed_autonomous",
            "parametric_lcc",
            "independent_golden",
            "final_accepted",
        ],
        "failure": None,
    }


def native_baseline_for_report(report: dict[str, object]) -> dict[str, object]:
    from tests.test_lcc_mmc_program_baseline import valid_baseline

    baseline = valid_baseline()
    baseline["environment"]["master_path"] = report["sources"]["master"]["path"]
    baseline["environment"]["master_sha256"] = report["sources"]["master"][
        "after"
    ]
    baseline["sources"].append(
        {
            "source_id": "official.lcc.cigre_bidirectional.project",
            "kind": "official_template",
            "path": report["sources"]["template"]["path"],
            "sha256": report["sources"]["template"]["after"],
            "availability": "verified_local_read_only",
        }
    )
    baseline["assets"].append(
        {
            "asset_id": "asset.lcc.fixed.manifest",
            "scope": "lcc.fixed_autonomous",
            "path": "pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/manifest.json",
            "sha256": report["sources"]["asset_manifest"]["sha256"],
        }
    )
    baseline["scopes"].append(
        {
            "scope": "lcc.blank_native",
            "builder_path": "lcc.blank_native",
            "owner_work_package": "WP1",
            "capability_state": "simulated",
            "licensed_status": "NOT_RUN_ON_CURRENT_COMMIT",
            "evidence_run_id": None,
            "explicit_exclusions": ["current_commit_acceptance"],
        }
    )
    return baseline


def subject():
    from pscad_mcp.hvdc.builders.lcc.native_acceptance import (
        validate_native_lcc_acceptance_report,
    )

    return validate_native_lcc_acceptance_report


def test_valid_pass_report_is_normalized_without_mutation():
    payload = valid_report()
    original = copy.deepcopy(payload)
    assert subject()(payload)["status"] == "PASS"
    assert payload == original


def test_valid_pass_report_preserves_undeclared_observed_channel_units():
    payload = valid_report()
    channels = payload["acceptance"]["evidence"]["channels"]
    channels["dc_current"]["units"] = ""
    channels["failure_indicator"]["units"] = ""

    normalized = subject()(payload)

    observed = normalized["acceptance"]["evidence"]["channels"]
    assert observed["dc_current"]["units"] == ""
    assert observed["failure_indicator"]["units"] == ""


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(extra=True),
        lambda value: value["build"].update(extra=True),
        lambda value: value["acceptance"]["checks"].pop("recovered"),
        lambda value: value["artifacts"].update(project=None),
        lambda value: value.update(capability_state="accepted"),
        lambda value: value["runtime"].update(quit_error="quit failed"),
        lambda value: value["build"].update(
            history=list(reversed(SUCCESS_HISTORY))
        ),
    ],
)
def test_pass_report_rejects_unknown_missing_or_false_claims(mutation):
    payload = valid_report()
    mutation(payload)
    with pytest.raises(BackendError) as failure:
        subject()(payload)
    assert failure.value.code == "LCC_NATIVE_REPORT_INVALID"


def test_fail_report_requires_failure_and_rejects_pass_artifacts():
    payload = valid_report()
    payload["status"] = "FAIL"
    payload["capability_state"] = "failed"
    payload["failure"] = {
        "stage": "compile",
        "code": "LCC_BUILD_FAILED",
        "message": "failed",
    }
    payload["build"]["terminal_state"] = "failed"
    payload["build"]["history"] = ["validated", "failed"]
    payload["artifacts"] = {
        "project": None,
        "library": None,
        "scenario": None,
        "selected_output": None,
        "output_parts": [],
        "output_metadata": [],
    }
    payload["acceptance"] = None

    assert subject()(payload)["failure"]["stage"] == "compile"


def test_native_promotion_revalidates_domain_report_before_generic_promotion(
    tmp_path,
):
    from pscad_mcp.hvdc.builders.lcc.native_acceptance import (
        promote_native_lcc_report,
    )

    payload = valid_report()
    payload["acceptance"]["checks"]["recovered"] = False
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")
    called = []

    with pytest.raises(BackendError):
        promote_native_lcc_report(
            tmp_path / "baseline.json",
            report,
            promotion_action=lambda *args, **kwargs: called.append((args, kwargs)),
        )

    assert called == []


def test_native_promotion_pins_validated_report_hash(monkeypatch, tmp_path):
    from pscad_mcp.hvdc.builders.lcc import native_acceptance

    report = tmp_path / "report.json"
    report.write_text(json.dumps(valid_report(), sort_keys=True), encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        native_acceptance,
        "_verify_native_report_files",
        lambda payload: None,
    )
    monkeypatch.setattr(
        native_acceptance,
        "_validate_native_baseline_identities",
        lambda baseline, payload: None,
    )

    native_acceptance.promote_native_lcc_report(
        tmp_path / "baseline.json",
        report,
        promotion_action=lambda *args, **kwargs: calls.append((args, kwargs)) or {},
    )

    assert calls[0][1]["expected_report_sha256"] == hashlib.sha256(
        report.read_bytes()
    ).hexdigest()


def test_native_promotion_rejects_report_from_different_official_source(
    monkeypatch, tmp_path
):
    from pscad_mcp.hvdc.builders.lcc import native_acceptance

    payload = valid_report()
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")
    baseline = native_baseline_for_report(payload)
    baseline["sources"][-1]["sha256"] = "d" * 64
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        native_acceptance,
        "_verify_native_report_files",
        lambda value: None,
    )

    with pytest.raises(BackendError) as failure:
        native_acceptance.promote_native_lcc_report(
            baseline_path,
            report,
            promotion_action=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

    assert failure.value.code == "LCC_NATIVE_REPORT_INVALID"
    assert failure.value.details["field"] == "sources.template"
    assert calls == []


def test_native_promotion_rejects_report_from_nonbaseline_compiler(
    monkeypatch, tmp_path
):
    from pscad_mcp.hvdc.builders.lcc import native_acceptance

    payload = valid_report()
    snapshot = payload["preflight"]["snapshot"]
    snapshot.update(
        {
            "compiler_configuration": (
                "C:/Program Files (x86)/PSCAD46/fortran_compilers.xml"
            ),
            "compiler_configuration_sha256": "e" * 64,
            "compiler_executable": (
                "C:/Program Files (x86)/GFortran/4.6/bin/gfortran.exe"
            ),
            "compiler_executable_sha256": "3" * 64,
        }
    )
    payload["preflight"]["sha256"] = hashlib.sha256(
        json.dumps(
            snapshot,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(native_baseline_for_report(payload)),
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(
        native_acceptance,
        "_verify_native_report_files",
        lambda value: None,
    )

    with pytest.raises(BackendError) as failure:
        native_acceptance.promote_native_lcc_report(
            baseline_path,
            report,
            promotion_action=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

    assert failure.value.code == "LCC_NATIVE_REPORT_INVALID"
    assert failure.value.details["field"] == "preflight.compiler_configuration"
    assert calls == []


class FakePscadService:
    def __init__(self) -> None:
        self.calls = []

    async def attach_local(self):
        self.calls.append("attach_local")

    async def status(self):
        return {
            "backend": "legacy",
            "version": "4.6.2",
            "x64": True,
            "licensed": True,
            "session": {"managed_pid": 42},
        }

    async def quit_pscad(self, *, confirm=False):
        self.calls.append(("quit_pscad", confirm))


class WrongRuntimeService(FakePscadService):
    async def status(self):
        result = await super().status()
        result["version"] = "5.0.0"
        result["x64"] = False
        return result


class FakeBuilder:
    def __init__(self, workspace: Path, source: Path) -> None:
        self.workspace = workspace
        self.source = source
        self.build_id = "build-1"
        self.polls = 0

    def plan_model(
        self,
        project_name,
        folder,
        simulation_duration_s,
        template_path,
    ):
        return {
            "plan_hash": HASH,
            "native_template": {
                "source": str(self.source),
                "source_sha256": HASH,
            },
            "target_path": str(self.workspace / f"{project_name}.pscx"),
        }

    async def build_model(
        self,
        project_name,
        expected_plan_hash,
        folder,
        simulation_duration_s,
        confirm,
        template_path,
    ):
        return {"build_id": self.build_id}

    def get_build_status(self, build_id):
        self.polls += 1
        return self._published_record()

    def _published_record(self):
        project = self.workspace / "WP1A_NATIVE_LCC.pscx"
        library = self.workspace / "cigre_lcc_v1.pslx"
        scenario = self.workspace / "WP1A_NATIVE_LCC_scenario_source.pscx"
        output = (
            self.workspace
            / "WP1A_NATIVE_LCC.outputs"
            / "WP1A_NATIVE_LCC_01.out"
        )
        for path in (project, library, scenario, output):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"evidence")
        journal = (
            self.workspace
            / ".pscad-mcp"
            / "lcc-builds"
            / self.build_id
            / "journal.json"
        )
        journal.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "build_id": self.build_id,
            "state": "published",
            "plan_hash": HASH,
            "target_path": str(project),
            "history": [{"state": state} for state in SUCCESS_HISTORY],
            "error": None,
            "result": {
                "output_file": str(output),
                "output_parts": [str(output)],
                "acceptance": {
                    "verdict": "PASS",
                    "checks": {
                        name: True
                        for name in (
                            "disturbance",
                            "failure_indication",
                            "bounded_dc_response",
                            "recovered",
                        )
                    },
                    "evidence": {
                        "fault_time_s": 0.8,
                        "fault_duration_s": 0.1,
                        "current_limit_pu": 3.0,
                        "dc_current_peak_pu": 2.5,
                        "recovery_window_s": 0.5,
                        "channels": {
                            "fault_active": {
                                "path": "Fault/LCC Fault Active",
                                "units": "state",
                                "samples": 5,
                                "domain_start_s": 0.0,
                                "domain_end_s": 2.0,
                            },
                            "dc_current": {
                                "path": "Inverter/DC Current",
                                "units": "pu",
                                "samples": 5,
                                "domain_start_s": 0.0,
                                "domain_end_s": 2.0,
                            },
                            "failure_indicator": {
                                "path": "Inverter/Gamma",
                                "units": "deg",
                                "samples": 5,
                                "domain_start_s": 0.0,
                                "domain_end_s": 2.0,
                            },
                        },
                    },
                },
                "final_project_sha256": HASH,
                "final_library_path": str(library),
                "final_library_sha256": HASH,
                "scenario_source": str(scenario),
            },
        }
        journal.write_text(json.dumps(record), encoding="utf-8")
        return record

    async def shutdown(self, timeout_s=5.0):
        return None


class InvalidReportBuilder(FakeBuilder):
    def _published_record(self):
        record = super()._published_record()
        channels = record["result"]["acceptance"]["evidence"]["channels"]
        channels["dc_current"]["units"] = None
        return record


class CompilerMutatingBuilder(FakeBuilder):
    def __init__(self, workspace: Path, source: Path, compiler: Path) -> None:
        super().__init__(workspace, source)
        self.compiler = compiler

    def _published_record(self):
        record = super()._published_record()
        self.compiler.write_bytes(b"changed compiler configuration")
        return record


class SourceRemovingBuilder(FakeBuilder):
    def _published_record(self):
        record = super()._published_record()
        self.source.unlink()
        return record


def native_request(tmp_path):
    from pscad_mcp.hvdc.builders.lcc.native_acceptance import (
        NativeLccAcceptanceRequest,
    )

    source = tmp_path / "official.pscx"
    source.write_bytes(b"official")
    master = tmp_path / "master.pslx"
    master.write_bytes(b"master")
    compiler_configuration = tmp_path / "fortran_compilers.xml"
    compiler_configuration.write_bytes(b"compiler configuration")
    compiler_executable = tmp_path / "gfortran.exe"
    compiler_executable.write_bytes(b"compiler executable")
    snapshot = copy.deepcopy(PREFLIGHT_SNAPSHOT)
    snapshot.update(
        {
            "compiler_configuration": str(compiler_configuration),
            "compiler_configuration_sha256": hashlib.sha256(
                compiler_configuration.read_bytes()
            ).hexdigest(),
            "compiler_executable": str(compiler_executable),
            "compiler_executable_sha256": hashlib.sha256(
                compiler_executable.read_bytes()
            ).hexdigest(),
        }
    )
    preflight_hash = hashlib.sha256(
        json.dumps(
            snapshot,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    return NativeLccAcceptanceRequest(
        repository_root=tmp_path,
        workspace_root=tmp_path / "workspace",
        template_path=source,
        master_path=master,
        report_path=tmp_path / "report.json",
        project_name="WP1A_NATIVE_LCC",
        commit=COMMIT,
        branch="codex/lcc-wp1a",
        registry_sha256=HASH,
        registry_file_sha256=HASH,
        asset_manifest_sha256=HASH,
        preflight={
            "status": "PASS",
            "sha256": preflight_hash,
            "snapshot": snapshot,
        },
    )


def test_orchestrator_uses_builder_and_writes_indexable_pass_report(tmp_path):
    from pscad_mcp.hvdc.builders.lcc.native_acceptance import (
        run_native_lcc_acceptance,
    )

    request = native_request(tmp_path)
    service = FakePscadService()
    builder = FakeBuilder(request.workspace_root, request.template_path)

    result = asyncio.run(
        run_native_lcc_acceptance(
            request,
            service=service,
            builder=builder,
            process_reader=list,
            poll_interval_s=0,
        )
    )

    assert result["status"] == "PASS"
    assert request.report_path.is_file()
    assert service.calls == ["attach_local", ("quit_pscad", True)]


def test_orchestrator_writes_fail_report_and_never_claims_pass_on_cleanup_failure(
    tmp_path,
):
    from pscad_mcp.hvdc.builders.lcc.native_acceptance import (
        run_native_lcc_acceptance,
    )

    request = native_request(tmp_path)
    service = FakePscadService()

    async def fail_quit(*, confirm=False):
        raise RuntimeError("quit failed")

    service.quit_pscad = fail_quit
    result = asyncio.run(
        run_native_lcc_acceptance(
            request,
            service=service,
            builder=FakeBuilder(request.workspace_root, request.template_path),
            process_reader=lambda: [
                {"pid": 42, "name": "Pscad.exe", "exe": "Pscad.exe"}
            ],
            poll_interval_s=0,
        )
    )

    assert result["status"] == "FAIL"
    assert result["capability_state"] == "failed"
    assert result["failure"]["stage"] == "cleanup"


def test_orchestrator_persists_fail_when_pass_report_contract_is_invalid(tmp_path):
    from pscad_mcp.hvdc.builders.lcc.native_acceptance import (
        run_native_lcc_acceptance,
    )

    request = native_request(tmp_path)
    service = FakePscadService()
    result = asyncio.run(
        run_native_lcc_acceptance(
            request,
            service=service,
            builder=InvalidReportBuilder(
                request.workspace_root,
                request.template_path,
            ),
            process_reader=list,
            poll_interval_s=0,
        )
    )

    assert result["status"] == "FAIL"
    assert result["failure"]["stage"] == "report"
    assert request.report_path.is_file()
    assert service.calls == ["attach_local", ("quit_pscad", True)]


def test_orchestrator_rejects_compiler_change_during_run(tmp_path):
    from pscad_mcp.hvdc.builders.lcc.native_acceptance import (
        run_native_lcc_acceptance,
    )

    request = native_request(tmp_path)
    compiler = Path(request.preflight["snapshot"]["compiler_configuration"])
    result = asyncio.run(
        run_native_lcc_acceptance(
            request,
            service=FakePscadService(),
            builder=CompilerMutatingBuilder(
                request.workspace_root,
                request.template_path,
                compiler,
            ),
            process_reader=list,
            poll_interval_s=0,
        )
    )

    assert result["status"] == "FAIL"
    assert result["failure"]["stage"] == "cleanup"
    assert request.report_path.is_file()


def test_orchestrator_persists_fail_when_source_becomes_unreadable(tmp_path):
    from pscad_mcp.hvdc.builders.lcc.native_acceptance import (
        run_native_lcc_acceptance,
    )

    request = native_request(tmp_path)
    result = asyncio.run(
        run_native_lcc_acceptance(
            request,
            service=FakePscadService(),
            builder=SourceRemovingBuilder(
                request.workspace_root,
                request.template_path,
            ),
            process_reader=list,
            poll_interval_s=0,
        )
    )

    assert result["status"] == "FAIL"
    assert result["failure"]["stage"] == "cleanup"
    assert result["sources"]["template"]["after"] is None
    assert request.report_path.is_file()


def test_orchestrator_persists_fail_for_unexpected_runtime_identity(tmp_path):
    from pscad_mcp.hvdc.builders.lcc.native_acceptance import (
        run_native_lcc_acceptance,
    )

    request = native_request(tmp_path)
    result = asyncio.run(
        run_native_lcc_acceptance(
            request,
            service=WrongRuntimeService(),
            builder=FakeBuilder(request.workspace_root, request.template_path),
            process_reader=list,
            poll_interval_s=0,
        )
    )

    assert result["status"] == "FAIL"
    assert result["failure"]["stage"] == "attach"
    assert result["runtime"]["version"] == "5.0.0"
    assert result["runtime"]["x64"] is False
    assert request.report_path.is_file()
