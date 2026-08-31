from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc import fixed_acceptance
from pscad_mcp.hvdc.builders.lcc.companion_gate import FIXTURES
from pscad_mcp.hvdc.builders.lcc.fixed_acceptance import (
    FIXED_EXCLUSIONS,
    FixedLccAcceptanceRequest,
    promote_fixed_lcc_report,
    run_fixed_lcc_acceptance,
    validate_fixed_lcc_acceptance_report,
)
from pscad_mcp.hvdc.builders.lcc.journal import AtomicJournal

COMMIT = "a" * 40
HASH = "b" * 64
REGISTRY_HASH = "c" * 64
SUCCESS_HISTORY = [
    "validated",
    "staging_created",
    "components_placed",
    "parameters_verified",
    "connections_verified",
    "structure_verified",
    "staging_saved",
    "compiled",
    "simulated",
    "smoke_passed",
    "published",
]
SMOKE_CHANNELS = (
    "Main/IDC",
    "Main/VDC_RECT",
    "Main/VDC_INV",
    "Main/AO_RECT_Y",
    "Main/AO_RECT_D",
    "Main/AO_INV_Y",
    "Main/AO_INV_D",
    "Main/GAMMA_INV",
    "Main/ENABLE_RECT",
    "Main/ENABLE_INV",
)
PREFLIGHT_SNAPSHOT = {
    "status": "PASS",
    "compiler_configuration": "C:/PSCAD46/fortran_compilers.xml",
    "compiler_configuration_sha256": "d" * 64,
    "compiler_executable": "C:/GFortran/4.6/bin/gfortran.exe",
    "compiler_executable_sha256": "e" * 64,
    "master_path": "C:/PSCAD46/master.pslx",
    "master_sha256": HASH,
}
PREFLIGHT_HASH = hashlib.sha256(
    json.dumps(
        PREFLIGHT_SNAPSHOT,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
).hexdigest()


def _source(path: str, sha256: str = HASH) -> dict[str, str]:
    return {
        "path": path,
        "before": sha256,
        "after": sha256,
    }


def _path_hash(path: str, sha256: str = HASH) -> dict[str, str]:
    return {"path": path, "sha256": sha256}


def _snapshot(fixture) -> dict[str, object]:
    electrical = {
        "ACY_A",
        "ACY_B",
        "ACY_C",
        "ACD_A",
        "ACD_B",
        "ACD_C",
        "DC_POS",
        "DC_NEG",
    }
    return {
        "definition": fixture.definition,
        "parameters": {
            name: str(value) for name, value in fixture.parameters.items()
        },
        "ports": {
            name: {
                "kind": "electrical" if name in electrical else "data",
                "dimension": 1,
            }
            for name in fixture.expected_ports
        },
    }


def _component_gate() -> dict[str, object]:
    fixture_records = []
    for index, fixture in enumerate(FIXTURES, start=1):
        snapshot = _snapshot(fixture)
        fixture_records.append(
            {
                "fixture": fixture.name,
                "definition": fixture.definition,
                "project": {
                    "name": fixture.name,
                    "path": f"D:/run/fixtures/{fixture.name}.pscx",
                    "sha256_before_compile": HASH,
                    "sha256": HASH,
                },
                "component_id": index,
                "before_reload": copy.deepcopy(snapshot),
                "after_reload": copy.deepcopy(snapshot),
                "compile": {"success": True, "result_type": "str"},
            }
        )
    return {
        "schema_version": 1,
        "status": "PASS",
        "workspace": "D:/run/fixtures",
        "master_sha256": HASH,
        "registry_sha256": REGISTRY_HASH,
        "library": _path_hash("D:/run/fixtures/cigre_lcc_v1.pslx"),
        "fixtures": fixture_records,
        "failure": None,
    }


def _smoke_channel(name: str) -> dict[str, object]:
    if name.startswith("Main/AO_RECT_"):
        units, minimum, maximum = "rad", 0.2, 0.3
    elif name.startswith("Main/AO_INV_"):
        units, minimum, maximum = "rad", 1.0, 1.7
    elif name == "Main/GAMMA_INV":
        units, minimum, maximum = "rad", 0.2, 0.4
    elif name.startswith("Main/ENABLE_"):
        units, minimum, maximum = "state", 1.0, 1.0
    elif name == "Main/IDC":
        units, minimum, maximum = "kA", 0.9, 1.1
    else:
        units, minimum, maximum = "kV", -500.0, 500.0
    return {
        "units": units,
        "samples": 2001,
        "minimum": minimum,
        "maximum": maximum,
    }


def valid_fixed_report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": "fixed-run-1",
        "scope": "lcc.fixed_autonomous",
        "builder_path": "lcc.fixed_autonomous",
        "kind": "licensed_simulation",
        "capability_state": "simulated",
        "commit": COMMIT,
        "generated_at_utc": "2026-08-31T01:00:00Z",
        "status": "PASS",
        "repository": {
            "branch": "codex/lcc-wp1b",
            "commit": COMMIT,
            "clean": True,
        },
        "preflight": {
            "status": "PASS",
            "sha256": PREFLIGHT_HASH,
            "snapshot": copy.deepcopy(PREFLIGHT_SNAPSHOT),
        },
        "sources": {
            "master": _source("C:/PSCAD46/master.pslx"),
            "registry": {
                "path": "D:/repo/master-bindings.json",
                "before": HASH,
                "after": HASH,
                "registry_sha256": REGISTRY_HASH,
            },
            "asset_manifest": _source("D:/repo/manifest.json"),
            "catalog": _source("D:/repo/catalog.json"),
            "blueprint": _source("D:/repo/blueprint.json"),
            "library": _source("D:/repo/cigre_lcc_v1.pslx"),
            "smoke_contract": _source("D:/repo/smoke.json"),
            "provenance": _source("D:/repo/PROVENANCE.md"),
        },
        "component_gate": _component_gate(),
        "build": {
            "project_name": "WP1B_FIXED_LCC",
            "workspace": "D:/run/full",
            "build_id": "build-1",
            "plan_hash": HASH,
            "verification_profile": "wp1b_smoke",
            "journal_path": "D:/run/full/journal.json",
            "journal_sha256": HASH,
            "history": list(SUCCESS_HISTORY),
            "terminal_state": "published",
        },
        "artifacts": {
            "project": _path_hash("D:/run/full/WP1B_FIXED_LCC.pscx"),
            "library": _path_hash("D:/run/full/cigre_lcc_v1.pslx"),
            "selected_output": _path_hash(
                "D:/run/full/WP1B_FIXED_LCC_01.out"
            ),
            "output_parts": [
                _path_hash("D:/run/full/WP1B_FIXED_LCC_01.out")
            ],
            "output_metadata": [],
        },
        "smoke": {
            "verdict": "PASS",
            "checks": {
                "time_domain": True,
                "finite_outputs": True,
                "controls_enabled": True,
                "ao_within_limits": True,
            },
            "evidence": {
                "duration_s": 0.1,
                "output_step_s": 0.00005,
                "domain_start_s": 0.0,
                "domain_end_s": 0.1,
                "minimum_step_s": 0.00005,
                "maximum_step_s": 0.00005,
                "samples": 2001,
                "channels": {
                    name: _smoke_channel(name) for name in SMOKE_CHANNELS
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
        "explicit_exclusions": list(FIXED_EXCLUSIONS),
        "failure": None,
    }


def test_valid_fixed_report_is_simulated_pass_with_exact_exclusions():
    payload = valid_fixed_report()
    original = copy.deepcopy(payload)

    normalized = validate_fixed_lcc_acceptance_report(payload)

    assert normalized["scope"] == "lcc.fixed_autonomous"
    assert normalized["builder_path"] == "lcc.fixed_autonomous"
    assert normalized["capability_state"] == "simulated"
    assert normalized["status"] == "PASS"
    assert tuple(normalized["explicit_exclusions"]) == FIXED_EXCLUSIONS
    assert normalized["smoke"]["verdict"] == "PASS"
    assert normalized["component_gate"]["status"] == "PASS"
    assert payload == original


def test_pass_report_allows_ao_text_serialization_noise():
    payload = valid_fixed_report()
    payload["smoke"]["evidence"]["channels"]["Main/AO_RECT_Y"][
        "minimum"
    ] = fixed_acceptance._AO_LIMITS["Main/AO_RECT_Y"][0] - 1e-14

    normalized = validate_fixed_lcc_acceptance_report(payload)

    assert normalized["status"] == "PASS"


@pytest.mark.parametrize(
    ("start", "samples"),
    [(0.05, 1001), (0.0, 1001)],
)
def test_pass_report_rejects_incomplete_smoke_time_domain(start, samples):
    payload = valid_fixed_report()
    evidence = payload["smoke"]["evidence"]
    evidence["domain_start_s"] = start
    evidence["samples"] = samples
    for channel in evidence["channels"].values():
        channel["samples"] = samples

    with pytest.raises(BackendError) as failure:
        validate_fixed_lcc_acceptance_report(payload)

    assert failure.value.code == "LCC_FIXED_REPORT_INVALID"


@pytest.mark.parametrize(
    "field",
    [
        "component_gate",
        "smoke",
        "runtime",
        "explicit_exclusions",
        "sources",
    ],
)
def test_pass_report_rejects_missing_evidence(field):
    payload = valid_fixed_report()
    payload.pop(field)

    with pytest.raises(BackendError) as failure:
        validate_fixed_lcc_acceptance_report(payload)

    assert failure.value.code == "LCC_FIXED_REPORT_INVALID"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(extra=True),
        lambda value: value["build"].update(extra=True),
        lambda value: value["component_gate"]["fixtures"].reverse(),
        lambda value: value["smoke"]["checks"].update(finite_outputs=False),
        lambda value: value["smoke"]["evidence"].update(samples=0),
        lambda value: value["smoke"]["evidence"]["channels"][
            "Main/IDC"
        ].update(maximum=math.inf),
        lambda value: value["sources"]["library"].update(after="f" * 64),
        lambda value: value["runtime"].update(remaining_processes=[{"pid": 1}]),
    ],
)
def test_pass_report_rejects_nonexact_or_false_evidence(mutation):
    payload = valid_fixed_report()
    mutation(payload)

    with pytest.raises(BackendError) as failure:
        validate_fixed_lcc_acceptance_report(payload)

    assert failure.value.code == "LCC_FIXED_REPORT_INVALID"


def test_fail_report_is_durable_but_not_promotable(tmp_path):
    payload = valid_fixed_report()
    payload["status"] = "FAIL"
    payload["capability_state"] = "failed"
    payload["smoke"] = None
    payload["failure"] = {
        "stage": "full_compile",
        "code": "LCC_BUILD_FAILED",
        "message": "compile failed",
    }
    payload["build"]["terminal_state"] = "failed"
    payload["build"]["history"] = ["validated", "compiled", "failed"]
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")

    assert validate_fixed_lcc_acceptance_report(payload)["status"] == "FAIL"
    with pytest.raises(BackendError):
        promote_fixed_lcc_report(tmp_path / "baseline.json", report)


def test_promotion_revalidates_domain_before_generic_promotion(tmp_path):
    payload = valid_fixed_report()
    payload["smoke"]["checks"]["time_domain"] = False
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")
    calls = []

    with pytest.raises(BackendError):
        promote_fixed_lcc_report(
            tmp_path / "baseline.json",
            report,
            promotion_action=lambda *args, **kwargs: calls.append(
                (args, kwargs)
            ),
        )

    assert calls == []


def test_promotion_pins_report_hash_and_fixed_scope(monkeypatch, tmp_path):
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(valid_fixed_report(), sort_keys=True),
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(
        fixed_acceptance,
        "_verify_fixed_report_files",
        lambda payload: None,
    )
    monkeypatch.setattr(
        fixed_acceptance,
        "_validate_fixed_baseline_identities",
        lambda baseline, payload: None,
    )

    promote_fixed_lcc_report(
        tmp_path / "baseline.json",
        report,
        promotion_action=lambda *args, **kwargs: calls.append(
            (args, kwargs)
        )
        or {},
    )

    kwargs = calls[0][1]
    assert kwargs["expected_scope"] == "lcc.fixed_autonomous"
    assert kwargs["owner_work_package"] == "WP1"
    assert tuple(kwargs["explicit_exclusions"]) == FIXED_EXCLUSIONS
    assert kwargs["expected_repository_branch"] == "codex/lcc-wp1b"
    assert kwargs["asset_hash_updates"] == {
        "asset.lcc.fixed.manifest": valid_fixed_report()["sources"][
            "asset_manifest"
        ]["after"]
    }
    assert kwargs["expected_report_sha256"] == hashlib.sha256(
        report.read_bytes()
    ).hexdigest()


def test_report_load_rejects_more_than_16_mib(tmp_path):
    report = tmp_path / "oversized.json"
    report.write_bytes(b" " * (16 * 1024 * 1024 + 1))

    with pytest.raises(BackendError) as failure:
        fixed_acceptance.load_fixed_lcc_acceptance_report(report)

    assert failure.value.code == "LCC_FIXED_REPORT_INVALID"


def _manifest_bound_report(
    root: Path,
    *,
    companion_library: str,
) -> dict[str, object]:
    payload = valid_fixed_report()
    relative_sources = {
        "registry": "master-bindings-pscad-4.6.2.json",
        "catalog": "catalog-pscad-4.6.2.json",
        "blueprint": "blueprint.json",
        "library": "library/cigre_lcc_v1.pslx",
        "smoke_contract": "smoke.json",
        "provenance": "PROVENANCE.md",
    }
    hashes = {}
    for source_name, relative in relative_sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source_name.encode("ascii"))
        sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes[relative] = sha256
        if source_name == "registry":
            payload["sources"][source_name].update(
                path=str(path),
                before=sha256,
                after=sha256,
            )
        else:
            payload["sources"][source_name] = _source(str(path), sha256)
    manifest = {
        "schema_version": 1,
        "name": "cigre_lcc_monopole_v1",
        "pscad_version": "4.6.2",
        "companion_library": companion_library,
        "hashes": hashes,
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    payload["sources"]["asset_manifest"] = _source(
        str(manifest_path),
        manifest_sha256,
    )
    return payload


def test_manifest_revalidation_rejects_wrong_companion_identity(tmp_path):
    payload = _manifest_bound_report(
        tmp_path,
        companion_library="library/not-the-fixed-companion.pslx",
    )

    with pytest.raises(BackendError) as failure:
        fixed_acceptance._verify_manifest_sources(payload)

    assert failure.value.code == "LCC_FIXED_REPORT_INVALID"
    assert failure.value.details["field"] == "sources.asset_manifest"


def test_preflight_file_revalidation_rejects_compiler_drift(tmp_path):
    compiler_configuration = tmp_path / "fortran_compilers.xml"
    compiler_executable = tmp_path / "gfortran.exe"
    master = tmp_path / "master.pslx"
    compiler_configuration.write_bytes(b"compiler-before")
    compiler_executable.write_bytes(b"executable")
    master.write_bytes(b"master")
    preflight = {
        "snapshot": {
            "compiler_configuration": str(compiler_configuration),
            "compiler_configuration_sha256": hashlib.sha256(
                compiler_configuration.read_bytes()
            ).hexdigest(),
            "compiler_executable": str(compiler_executable),
            "compiler_executable_sha256": hashlib.sha256(
                compiler_executable.read_bytes()
            ).hexdigest(),
            "master_path": str(master),
            "master_sha256": hashlib.sha256(master.read_bytes()).hexdigest(),
        }
    }
    compiler_configuration.write_bytes(b"compiler-after")

    with pytest.raises(BackendError) as failure:
        fixed_acceptance._verify_preflight_files(preflight)

    assert failure.value.code == "LCC_FIXED_REPORT_INVALID"
    assert failure.value.details["field"] == "preflight.compiler_configuration"


def fixed_request(tmp_path: Path) -> FixedLccAcceptanceRequest:
    root = Path(__file__).parents[1]
    asset_root = (
        root
        / "pscad_mcp"
        / "assets"
        / "lcc"
        / "cigre_lcc_monopole_v1"
    )
    workspace = tmp_path / "fixed-run"
    workspace.mkdir()
    master = tmp_path / "master.pslx"
    compiler_configuration = tmp_path / "fortran_compilers.xml"
    compiler_executable = tmp_path / "gfortran.exe"
    master.write_bytes(b"master")
    compiler_configuration.write_bytes(b"compiler configuration")
    compiler_executable.write_bytes(b"compiler executable")
    snapshot = {
        "status": "PASS",
        "master_path": str(master),
        "master_sha256": hashlib.sha256(master.read_bytes()).hexdigest(),
        "compiler_configuration": str(compiler_configuration),
        "compiler_configuration_sha256": hashlib.sha256(
            compiler_configuration.read_bytes()
        ).hexdigest(),
        "compiler_executable": str(compiler_executable),
        "compiler_executable_sha256": hashlib.sha256(
            compiler_executable.read_bytes()
        ).hexdigest(),
    }
    preflight_hash = hashlib.sha256(
        json.dumps(
            snapshot,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    baseline = tmp_path / "baseline.json"
    baseline.write_bytes(b"unchanged baseline")
    return FixedLccAcceptanceRequest(
        repository_root=root,
        workspace_root=workspace,
        master_path=master,
        registry_path=asset_root / "master-bindings-pscad-4.6.2.json",
        asset_manifest_path=asset_root / "manifest.json",
        report_path=workspace / "fixed-lcc-acceptance-report.json",
        baseline_path=baseline,
        project_name="WP1B_FIXED_LCC",
        commit=COMMIT,
        branch="codex/lcc-wp1b",
        preflight={
            "status": "PASS",
            "sha256": preflight_hash,
            "snapshot": snapshot,
        },
    )


def _fake_master_audit(master_path: Path, registry):
    return SimpleNamespace(
        master_sha256=hashlib.sha256(master_path.read_bytes()).hexdigest(),
        registry=registry,
    )


def _component_gate_for_run(request: FixedLccAcceptanceRequest):
    from pscad_mcp.hvdc.builders.lcc.assets import load_packaged_asset_set

    assets = load_packaged_asset_set()
    gate = _component_gate()
    gate_root = request.workspace_root / "component-fixtures"
    gate_root.mkdir(parents=True, exist_ok=True)
    source_library = request.asset_manifest_path.parent / assets.companion_library
    gate_library = gate_root / Path(assets.companion_library).name
    shutil.copyfile(source_library, gate_library)
    library_hash = hashlib.sha256(gate_library.read_bytes()).hexdigest()
    gate.update(
        workspace=str(gate_root),
        master_sha256=hashlib.sha256(request.master_path.read_bytes()).hexdigest(),
        registry_sha256=assets.master_bindings.sha256,
        library=_path_hash(str(gate_library), library_hash),
    )
    for item in gate["fixtures"]:
        fixture_root = gate_root / item["fixture"]
        fixture_root.mkdir()
        project = fixture_root / f"{item['fixture']}.pscx"
        project.write_bytes(item["fixture"].encode("ascii"))
        project_hash = hashlib.sha256(project.read_bytes()).hexdigest()
        item["project"].update(
            path=str(project),
            sha256_before_compile=project_hash,
            sha256=project_hash,
        )
    return gate


class FakePscadService:
    def __init__(self, failure_stage: str | None = None) -> None:
        self.failure_stage = failure_stage
        self.calls: list[Any] = []

    async def attach_local(self):
        self.calls.append("attach_local")
        if self.failure_stage == "attach":
            raise RuntimeError("attach failed")

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
        if self.failure_stage == "cleanup":
            raise RuntimeError("quit failed")

    def processes(self):
        if self.failure_stage == "cleanup":
            return [{"pid": 42, "name": "Pscad.exe", "exe": "Pscad.exe"}]
        return []


class FakeFixedBuilder:
    def __init__(
        self,
        workspace: Path,
        failure_stage: str | None = None,
    ) -> None:
        self.workspace = workspace
        self.failure_stage = failure_stage
        self.plan_calls: list[dict[str, Any]] = []
        self.build_calls: list[dict[str, Any]] = []
        self.record: dict[str, Any] | None = None

    def plan_model(
        self,
        project_name,
        folder,
        simulation_duration_s,
        verification_profile,
    ):
        self.plan_calls.append(
            {
                "project_name": project_name,
                "folder": folder,
                "simulation_duration_s": simulation_duration_s,
                "verification_profile": verification_profile,
            }
        )
        if self.failure_stage == "plan":
            raise RuntimeError("plan failed")
        return {"plan_hash": HASH}

    async def build_model(
        self,
        project_name,
        expected_plan_hash,
        folder,
        simulation_duration_s,
        verification_profile,
        confirm,
    ):
        self.build_calls.append(
            {
                "project_name": project_name,
                "expected_plan_hash": expected_plan_hash,
                "folder": folder,
                "simulation_duration_s": simulation_duration_s,
                "verification_profile": verification_profile,
                "confirm": confirm,
            }
        )
        if self.failure_stage == "build":
            raise RuntimeError("build failed")
        self.record = self._published_record(project_name, Path(folder))
        return {"build_id": self.record["build_id"]}

    def _published_record(self, project_name: str, folder: Path):
        from pscad_mcp.hvdc.builders.lcc.assets import load_packaged_asset_set

        assets = load_packaged_asset_set()
        folder.mkdir(parents=True, exist_ok=True)
        project = folder / f"{project_name}.pscx"
        output = folder / f"{project_name}_01.out"
        output_metadata = folder / f"{project_name}.inf"
        library = self.workspace / ".pscad-mcp" / "libraries" / Path(
            assets.companion_library
        ).name
        library.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            Path(__file__).parents[1]
            / "pscad_mcp"
            / "assets"
            / "lcc"
            / "cigre_lcc_monopole_v1"
            / assets.companion_library,
            library,
        )
        project.write_bytes(b"project")
        output.write_bytes(b"output")
        output_metadata.write_bytes(b"metadata")
        smoke = copy.deepcopy(valid_fixed_report()["smoke"])
        if self.failure_stage == "report":
            smoke["checks"]["time_domain"] = False
        history = []
        for state in SUCCESS_HISTORY:
            history.append({"operation": f"operation:{state}"})
            history.append({"state": state})
        record = {
            "build_id": "build-1",
            "state": "published",
            "target_path": str(project),
            "history": history,
            "error": None,
            "result": {
                "smoke": smoke,
                "output_file": str(output),
                "output_parts": [str(output)],
            },
        }
        journal = AtomicJournal(self.workspace, "build-1").path
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(json.dumps(record), encoding="utf-8")
        return record

    def get_build_status(self, build_id):
        assert build_id == "build-1"
        return copy.deepcopy(self.record)

    async def shutdown(self, timeout_s=5.0):
        return None


def test_orchestrator_runs_component_gate_then_production_smoke(tmp_path):
    request = fixed_request(tmp_path)
    service = FakePscadService()
    builder = FakeFixedBuilder(request.workspace_root)
    calls = []

    result = asyncio.run(
        run_fixed_lcc_acceptance(
            request,
            service=service,
            builder=builder,
            companion_gate_action=lambda *args, **kwargs: calls.append(
                "component_gate"
            )
            or _component_gate_for_run(request),
            master_audit_action=_fake_master_audit,
            process_reader=list,
            poll_interval_s=0,
        )
    )

    assert result["status"] == "PASS"
    assert calls == ["component_gate"]
    assert builder.plan_calls[0]["verification_profile"] == "wp1b_smoke"
    assert builder.plan_calls[0]["simulation_duration_s"] == pytest.approx(0.1)
    assert request.report_path.is_file()
    assert service.calls == ["attach_local", ("quit_pscad", True)]


def test_orchestrator_persists_setup_fail_when_source_validation_drifts(
    tmp_path,
):
    request = fixed_request(tmp_path)
    request.master_path.write_bytes(b"master changed after preflight")
    service = FakePscadService()
    builder = FakeFixedBuilder(request.workspace_root)

    result = asyncio.run(
        run_fixed_lcc_acceptance(
            request,
            service=service,
            builder=builder,
            companion_gate_action=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("component gate must not run")
            ),
            master_audit_action=_fake_master_audit,
            process_reader=service.processes,
            poll_interval_s=0,
        )
    )

    assert result["status"] == "FAIL"
    assert result["failure"]["stage"] == "setup"
    assert request.report_path.is_file()
    assert request.baseline_path.read_bytes() == b"unchanged baseline"
    assert service.calls == [("quit_pscad", True)]


def test_orchestrator_persists_setup_fail_when_asset_loading_fails(
    monkeypatch,
    tmp_path,
):
    request = fixed_request(tmp_path)
    service = FakePscadService()
    builder = FakeFixedBuilder(request.workspace_root)

    def fail_asset_load():
        raise BackendError(
            "LCC_ASSET_MISMATCH",
            "asset loading failed",
            "hvdc",
            "load_lcc_asset_set",
        )

    monkeypatch.setattr(
        fixed_acceptance,
        "load_packaged_asset_set",
        fail_asset_load,
    )

    result = asyncio.run(
        run_fixed_lcc_acceptance(
            request,
            service=service,
            builder=builder,
            process_reader=service.processes,
            poll_interval_s=0,
        )
    )

    assert result["status"] == "FAIL"
    assert result["failure"]["stage"] == "setup"
    assert result["failure"]["code"] == "LCC_ASSET_MISMATCH"
    assert request.report_path.is_file()
    assert service.calls == [("quit_pscad", True)]


def test_orchestrator_persists_cleanup_fail_when_journal_hashing_fails(
    monkeypatch,
    tmp_path,
):
    request = fixed_request(tmp_path)
    service = FakePscadService()
    builder = FakeFixedBuilder(request.workspace_root)
    original_cleanup_hash = fixed_acceptance._cleanup_hash

    def fail_journal_hash(path):
        if path.name == "journal.json":
            return None, OSError("journal became unreadable")
        return original_cleanup_hash(path)

    monkeypatch.setattr(
        fixed_acceptance,
        "_cleanup_hash",
        fail_journal_hash,
    )

    result = asyncio.run(
        run_fixed_lcc_acceptance(
            request,
            service=service,
            builder=builder,
            companion_gate_action=lambda *_args, **_kwargs: (
                _component_gate_for_run(request)
            ),
            master_audit_action=_fake_master_audit,
            process_reader=service.processes,
            poll_interval_s=0,
        )
    )

    assert result["status"] == "FAIL"
    assert result["failure"]["stage"] == "cleanup"
    assert result["build"]["journal_path"].endswith("journal.json")
    assert result["build"]["journal_sha256"] is None
    assert request.report_path.is_file()


def failing_orchestrator_inputs(tmp_path: Path, failure_stage: str):
    request = fixed_request(tmp_path)
    service = FakePscadService(failure_stage)
    builder = FakeFixedBuilder(request.workspace_root, failure_stage)

    def gate(*_args, **_kwargs):
        if failure_stage != "component_gate":
            return _component_gate_for_run(request)
        result = _component_gate_for_run(request)
        result.update(
            status="FAIL",
            fixtures=[],
            failure={
                "fixture": "bridge_rectifier",
                "operation": "build_project",
                "code": "LCC_COMPANION_COMPILE_FAILED",
                "message": "fixture failed",
            },
        )
        return result

    return request, service, builder, gate


@pytest.mark.parametrize(
    ("failure_stage", "expected_stage"),
    [
        ("attach", "attach"),
        ("component_gate", "component_gate"),
        ("plan", "plan"),
        ("build", "build"),
        ("cleanup", "cleanup"),
        ("report", "report"),
    ],
)
def test_orchestrator_persists_fail_and_never_promotes(
    failure_stage,
    expected_stage,
    tmp_path,
):
    request, service, builder, gate = failing_orchestrator_inputs(
        tmp_path,
        failure_stage,
    )

    result = asyncio.run(
        run_fixed_lcc_acceptance(
            request,
            service=service,
            builder=builder,
            companion_gate_action=gate,
            master_audit_action=_fake_master_audit,
            process_reader=service.processes,
            poll_interval_s=0,
        )
    )

    assert result["status"] == "FAIL"
    assert result["failure"]["stage"] == expected_stage
    assert request.report_path.is_file()
    assert request.baseline_path.read_bytes() == b"unchanged baseline"
