import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.service import ConfirmationRequired
from pscad_mcp.hvdc.builders.lcc.journal import WorkspaceBuildLease as LccLease
from pscad_mcp.hvdc.builders.mmc import parametric_service as parametric_service_module
from tests.mmc_parametric_fakes import (
    make_parametric_service,
    valid_request,
    wait_for_terminal,
)


def _build(service, tmp_path: Path, request: dict):
    plan = service.plan_model(request, project_name="MMC_CASE", folder=str(tmp_path))
    started = asyncio.run(
        service.build_model(
            request,
            plan["plan_hash"],
            "MMC_CASE",
            str(tmp_path),
            confirm=True,
        )
    )
    return plan, wait_for_terminal(service, started["build_id"])


def test_both_engines_publish_only_after_independent_acceptance(tmp_path: Path) -> None:
    service = make_parametric_service(tmp_path, pwm_verdict="PASS", avm_verdict="PASS")
    request = valid_request(model_fidelity="both")

    plan, terminal = _build(service, tmp_path, request)

    assert terminal["state"] == "published"
    assert terminal["plan_hash"] == plan["plan_hash"]
    assert [item["capability_level"] for item in terminal["engines"]] == [
        "accepted",
        "accepted",
    ]
    assert (tmp_path / "MMC_CASE_pwm.pscx").is_file()
    assert (tmp_path / "MMC_CASE_avm.pscx").is_file()
    assert (tmp_path / "MMC_CASE_pwm_scenario_source.pscx").read_bytes() == (
        tmp_path / "MMC_CASE_pwm.pscx"
    ).read_bytes()
    assert (tmp_path / "MMC_CASE_avm_scenario_source.pscx").read_bytes() == (
        tmp_path / "MMC_CASE_avm.pscx"
    ).read_bytes()
    published_library = tmp_path / "intermediate.pslx"
    assert published_library.is_file()
    assert (
        published_library.read_bytes()
        == (Path(plan["engine_plans"][0]["source_paths"]["library"])).read_bytes()
    )
    assert terminal["engines"][0]["final_library_path"] == str(published_library)
    Path(terminal["engines"][0]["candidate_result"]["library_path"]).write_text(
        "candidate changed after publication", encoding="utf-8"
    )
    assert (
        published_library.read_bytes()
        == (Path(plan["engine_plans"][0]["source_paths"]["library"])).read_bytes()
    )
    assert service.recorded_engine_calls == [
        ("detailed_pwm", "pwm-0"),
        ("average_value", "avm-0"),
    ]


def test_legacy_pwm_parent_supplies_hash_verified_embedded_timing(
    tmp_path: Path,
) -> None:
    service = make_parametric_service(tmp_path)
    master = tmp_path / "master.pslx"
    master.write_bytes(b"installed Master fixture")
    identity = {
        "pscad_version": "4.6.2",
        "master_path": str(master),
        "master_sha256": hashlib.sha256(master.read_bytes()).hexdigest(),
    }

    async def installed_master():
        return dict(identity)

    captured = []
    execute = service.pwm_engine.execute_candidate

    async def capture(*args, **kwargs):
        captured.extend(kwargs["scenarios"])
        return await execute(*args, **kwargs)

    service.pscad_service.get_master_library_identity = installed_master
    service.pwm_engine.execute_candidate = capture
    _, terminal = _build(
        service, tmp_path, valid_request(model_fidelity="detailed_pwm")
    )

    assert terminal["state"] == "published"
    assert len(captured) == 11
    assert all(item["events"] for item in captured)
    for scenario in captured:
        assert scenario["timed_control_options"] == {
            "master_path": str(master.resolve()),
            "max_timing_error_s": scenario["time_step_s"] + scenario["output_step_s"],
        }


def test_legacy_pwm_parent_rejects_changed_installed_master(tmp_path: Path) -> None:
    service = make_parametric_service(tmp_path)
    master = tmp_path / "master.pslx"
    master.write_bytes(b"different installed Master")

    async def installed_master():
        return {
            "pscad_version": "4.6.2",
            "master_path": str(master),
            "master_sha256": "0" * 64,
        }

    service.pscad_service.get_master_library_identity = installed_master
    _, terminal = _build(
        service, tmp_path, valid_request(model_fidelity="detailed_pwm")
    )
    assert terminal["state"] == "failed"
    assert service.recorded_engine_calls == []
    assert (
        terminal["engines"][0]["attempts"][0]["error"]["code"]
        == "MASTER_SOURCE_CHANGED"
    )


def test_one_engine_failure_keeps_parent_unpublished_but_runs_other_child(
    tmp_path: Path,
) -> None:
    service = make_parametric_service(tmp_path, pwm_verdict="FAIL", avm_verdict="PASS")

    _, terminal = _build(service, tmp_path, valid_request(model_fidelity="both"))

    assert terminal["state"] == "failed"
    assert [item["state"] for item in terminal["engines"]] == ["failed", "accepted"]
    assert service.recorded_engine_calls == [
        ("detailed_pwm", "pwm-0"),
        ("average_value", "avm-0"),
    ]
    assert not (tmp_path / "MMC_CASE_pwm.pscx").exists()
    assert not (tmp_path / "MMC_CASE_avm.pscx").exists()


def test_retry_walks_only_preplanned_matching_candidate(tmp_path: Path) -> None:
    service = make_parametric_service(
        tmp_path, pwm_verdict="NUMERICAL_ONCE", avm_verdict="PASS"
    )

    _, terminal = _build(
        service, tmp_path, valid_request(model_fidelity="detailed_pwm")
    )

    assert terminal["state"] == "published"
    assert service.recorded_engine_calls == [
        ("detailed_pwm", "pwm-0"),
        ("detailed_pwm", "pwm-1"),
    ]
    attempts = terminal["engines"][0]["attempts"]
    assert [item["candidate_id"] for item in attempts] == ["pwm-0", "pwm-1"]
    assert attempts[0]["adjustment"]["category"] == "numerical_stability"


def test_build_requires_confirmation_and_exact_recomposed_hash(tmp_path: Path) -> None:
    service = make_parametric_service(tmp_path)
    request = valid_request(model_fidelity="average_value")
    plan = service.plan_model(request, project_name="MMC_CASE", folder=str(tmp_path))

    with pytest.raises(ConfirmationRequired):
        asyncio.run(
            service.build_model(
                request,
                plan["plan_hash"],
                "MMC_CASE",
                str(tmp_path),
                confirm=False,
            )
        )
    with pytest.raises(BackendError) as raised:
        asyncio.run(
            service.build_model(
                request,
                "0" * 64,
                "MMC_CASE",
                str(tmp_path),
                confirm=True,
            )
        )
    assert raised.value.code == "MMC_PLAN_STALE"


def test_mmc_parent_uses_shared_lcc_workspace_lease(tmp_path: Path) -> None:
    service = make_parametric_service(tmp_path)
    request = valid_request(model_fidelity="average_value")
    plan = service.plan_model(request, project_name="MMC_CASE", folder=str(tmp_path))
    lease = LccLease.acquire(tmp_path, "lcc-active")
    try:
        with pytest.raises(BackendError) as raised:
            asyncio.run(
                service.build_model(
                    request,
                    plan["plan_hash"],
                    "MMC_CASE",
                    str(tmp_path),
                    confirm=True,
                )
            )
        assert raised.value.code in {"MMC_BUILD_CONFLICT", "LCC_BUILD_CONFLICT"}
    finally:
        assert lease.release(lease.token) is True


def test_validation_without_outputs_cannot_claim_acceptance(tmp_path: Path) -> None:
    service = make_parametric_service(tmp_path)
    _, terminal = _build(
        service, tmp_path, valid_request(model_fidelity="average_value")
    )

    validation = service.validate_model(
        terminal["engines"][0]["final_path"],
        "average_value",
        output_files=None,
    )

    assert validation["capability_level"] == "built"
    assert validation["accepted"] is False
    assert validation["acceptance"]["status"] == "not_evaluated"


def test_pwm_reader_pass_without_bound_physical_evidence_is_incomplete(tmp_path):
    service = make_parametric_service(tmp_path)

    async def finite_reader(*args, **kwargs):
        return {"verdict": "PASS", "channels": [{"values": [640.0, 640.0]}]}

    service.pscad_service.read_output_file = finite_reader
    _, terminal = _build(
        service, tmp_path, valid_request(model_fidelity="detailed_pwm")
    )
    output = tmp_path / "unrelated.out"
    output.write_text("0 640\n0.1 640\n")
    result = service.validate_model(
        terminal["engines"][0]["final_path"], "detailed_pwm", output_files=[str(output)]
    )
    assert result["accepted"] is False
    assert result["acceptance"]["verdict"] == "INCOMPLETE_ANALYSIS"


def test_routed_pwm_publication_reloads_the_final_file_and_keeps_its_identity(
    tmp_path, monkeypatch
):
    service = make_parametric_service(tmp_path)
    execute = service.pwm_engine.execute_candidate
    reloaded = []

    async def routed(*args, **kwargs):
        result = await execute(*args, **kwargs)
        manifest = Path(result["project_path"]).with_name("routed-acceptance.json")
        manifest.write_text(
            json.dumps(
                {
                    "project_sha256": hashlib.sha256(
                        Path(result["project_path"]).read_bytes()
                    ).hexdigest(),
                    "original_inputs": {},
                    "evidence_files": {},
                }
            )
        )
        result.update(
            routed_physical_acceptance=True,
            validation={"physical_evidence": str(manifest)},
        )
        return result

    async def reload(project, filename):
        raise AssertionError("The waveform session must not be reset")

    async def verify(service, project, library, manifest, root, support):
        assert project.is_file()
        reloaded.append((project.stem, str(project)))
        worker_report = tmp_path / "worker-report.json"
        worker_report.write_text('{"status":"PASS"}')
        return {
            "status": "PASS",
            "build_messages": [],
            "report": str(worker_report),
            "normal": {
                "status": "PASS",
                "report": str(worker_report),
                "physical_report": str(worker_report),
            },
        }

    from pscad_mcp.hvdc.builders.mmc import publication_recovery

    monkeypatch.setattr(publication_recovery, "verify_publication_in_worker", verify)

    async def messages(*args, **kwargs):
        return []

    service.pwm_engine.execute_candidate = routed
    service.pscad_service.reload_project = reload
    service.pscad_service.get_project_output = messages
    _, terminal = _build(
        service, tmp_path, valid_request(model_fidelity="detailed_pwm")
    )
    assert terminal["state"] == "published"
    record = terminal["engines"][0]
    assert reloaded == [("MMC_CASE_pwm", record["final_path"])]
    manifest = json.loads(Path(record["acceptance_manifest"]).read_text())
    assert (
        manifest["publication"]["project_sha256"]
        == hashlib.sha256(Path(record["final_path"]).read_bytes()).hexdigest()
    )


def test_pwm_publication_copies_the_librarys_referenced_compiler_inputs(tmp_path):
    service = make_parametric_service(tmp_path)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    project = candidate / "PWM.pscx"
    project.write_text('<project name="PWM"><definitions/></project>')
    library = candidate / "intermediate.pslx"
    library.write_text(
        '<library><paramlist name="Libs"><param name="1" value="lib/$(Compiler)/intermediate.lib"/></paramlist><definitions/></library>'
    )
    binary = candidate / "lib/gf42/intermediate.lib"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"immutable compiler input")
    plan = SimpleNamespace(
        engine="detailed_pwm",
        source_paths={"library": str(library)},
        source_hashes={"library": hashlib.sha256(library.read_bytes()).hexdigest()},
        asset_hashes={str(binary): hashlib.sha256(binary.read_bytes()).hexdigest()},
    )
    record = {
        "engine": "detailed_pwm",
        "final_path": str(tmp_path / "PWM.pscx"),
        "candidate_result": {
            "project_path": str(project),
            "library_path": str(library),
        },
    }
    asyncio.run(service._publish([record], [plan]))
    assert (tmp_path / "lib/gf42/intermediate.lib").read_bytes() == binary.read_bytes()
    assert (
        record["final_library_support"][0]["sha256"]
        == hashlib.sha256(binary.read_bytes()).hexdigest()
    )


def test_compiled_native_candidate_stays_staged_until_dynamic_acceptance(tmp_path):
    service = make_parametric_service(tmp_path)
    execute = service.avm_engine.execute_candidate

    async def compiled_only(*args, **kwargs):
        result = await execute(*args, **kwargs)
        result.update(state="built", capability_level="built", model_accepted=False)
        return result

    service.avm_engine.execute_candidate = compiled_only
    _, terminal = _build(
        service, tmp_path, valid_request(model_fidelity="average_value")
    )
    assert terminal["state"] == "built"
    assert terminal["result"]["model_accepted"] is False
    assert (
        terminal["result"]["publication_pending"]
        == "required_dynamic_physical_acceptance"
    )
    assert not (tmp_path / "MMC_CASE_avm.pscx").exists()
    assert all(Path(path).is_file() for path in terminal["result"]["staged_projects"])
    assert not any(
        call[0] in {"load_projects", "save_project_as"}
        for call in service.pscad_service.calls
    )


def test_native_avm_publication_uses_pscad_save_as_for_distinct_candidate_name(
    tmp_path: Path,
) -> None:
    service = make_parametric_service(tmp_path)

    class NativeEngine:
        name = "average_value"

        async def execute_candidate(self, plan, _service, *, candidate_id=None):
            selected = candidate_id or plan.candidates[0].candidate_id
            candidate_name = (
                plan.target_name + "_candidate_" + selected.replace("-", "_")
            )
            root = tmp_path / ".native-candidate"
            root.mkdir()
            project = root / (candidate_name + ".pscx")
            project.write_text(
                f"<project name='{candidate_name}' version='4.6.2'><definitions/></project>",
                encoding="utf-8",
            )
            return {
                "state": "accepted",
                "engine": self.name,
                "candidate_id": selected,
                "project_path": str(project),
                "publication_project_name": candidate_name,
                "capability_level": "built",
                "assembly_accepted": False,
                "model_accepted": False,
            }

    service.avm_engine = NativeEngine()
    _, terminal = _build(
        service, tmp_path, valid_request(model_fidelity="average_value")
    )

    assert terminal["state"] == "published"
    engine = terminal["engines"][0]
    assert engine["publication_method"] == "pscad_save_as"
    assert engine["publication_settings"] == {"output_filename": "MMC_CASE_avm.out"}
    assert engine["capability_level"] == "built"
    final = tmp_path / "MMC_CASE_avm.pscx"
    assert final.is_file()
    assert "name='MMC_CASE_avm'" in final.read_text(encoding="utf-8")
    assert (
        tmp_path / ".native-candidate" / "MMC_CASE_avm_candidate_avm_0.pscx"
    ).is_file()
    save_as = [
        call for call in service.pscad_service.calls if call[0] == "save_project_as"
    ]
    assert len(save_as) == 1
    assert save_as[0][1][0] == "MMC_CASE_avm_candidate_avm_0"
    assert (
        "set_project_settings",
        ("MMC_CASE_avm", {"output_filename": "MMC_CASE_avm.out"}),
    ) in service.pscad_service.calls


def test_project_aware_recommendations_bind_cached_derived_project(
    tmp_path: Path,
) -> None:
    service = make_parametric_service(tmp_path)
    request = valid_request(model_fidelity="average_value")
    plan = service.plan_model(request, project_name="CUSTOM_CASE", folder=str(tmp_path))
    target = plan["engine_plans"][0]["target_path"]

    result = service.recommend_simulation(target)

    assert {item["engine"] for item in result["recommendations"]} == {"average_value"}
    assert all(
        item["scenario"]["derived_project"] == target
        for item in result["recommendations"]
    )
    assert all(
        item["scenario"]["project"] != target for item in result["recommendations"]
    )


def test_project_recommendations_use_the_plan_that_was_published(
    tmp_path: Path,
) -> None:
    service = make_parametric_service(tmp_path)
    published_request = valid_request(
        model_fidelity="average_value", active_power_mw=900.0
    )
    published_plan = service.plan_model(
        published_request, project_name="CUSTOM_CASE", folder=str(tmp_path)
    )
    service.plan_model(
        valid_request(model_fidelity="average_value", active_power_mw=1100.0),
        project_name="CUSTOM_CASE",
        folder=str(tmp_path),
    )

    started = asyncio.run(
        service.build_model(
            published_request,
            published_plan["plan_hash"],
            "CUSTOM_CASE",
            str(tmp_path),
            confirm=True,
        )
    )
    terminal = wait_for_terminal(service, started["build_id"])
    target = terminal["engines"][0]["final_path"]

    result = service.recommend_simulation(target)

    assert result["request"]["active_power_mw"] == 900.0


def test_absolute_project_lookup_does_not_alias_a_cached_basename(
    tmp_path: Path,
) -> None:
    service = make_parametric_service(tmp_path)
    plan = service.plan_model(
        valid_request(model_fidelity="average_value"),
        project_name="CUSTOM_CASE",
        folder=str(tmp_path),
    )
    target_name = Path(plan["engine_plans"][0]["target_path"]).name
    unrelated = tmp_path / "unrelated" / target_name

    with pytest.raises(BackendError) as raised:
        service.recommend_simulation(str(unrelated))

    assert raised.value.code == "MMC_REQUEST_INVALID"


def test_parent_rejects_pwm_library_that_differs_from_immutable_plan(
    tmp_path: Path,
) -> None:
    service = make_parametric_service(tmp_path, pwm_verdict="TAMPERED_LIBRARY")

    _, terminal = _build(
        service, tmp_path, valid_request(model_fidelity="detailed_pwm")
    )

    assert terminal["state"] == "failed"
    assert terminal["error"]["code"] == "MMC_POSTCONDITION_FAILED"
    assert not (tmp_path / "MMC_CASE_pwm.pscx").exists()
    assert not (tmp_path / "intermediate.pslx").exists()


def test_parent_rechecks_published_pwm_library_after_final_compile(
    tmp_path: Path,
) -> None:
    service = make_parametric_service(tmp_path)
    original_load = service.pscad_service.load_projects

    async def mutating_load(filenames: list[str]) -> str:
        result = await original_load(filenames)
        for filename in filenames:
            path = Path(filename)
            if path.name.casefold() == "intermediate.pslx" and path.parent == tmp_path:
                path.write_text("mutated during final reload", encoding="utf-8")
        return result

    service.pscad_service.load_projects = mutating_load

    _, terminal = _build(
        service, tmp_path, valid_request(model_fidelity="detailed_pwm")
    )

    assert terminal["state"] == "failed"
    assert terminal["error"]["code"] == "MMC_POSTCONDITION_FAILED"
    assert not (tmp_path / "MMC_CASE_pwm.pscx").exists()
    assert not (tmp_path / "intermediate.pslx").exists()


def test_parent_restores_preexisting_pwm_library_when_final_compile_mutates(
    tmp_path: Path,
) -> None:
    service = make_parametric_service(tmp_path)
    request = valid_request(model_fidelity="detailed_pwm")
    plan = service.plan_model(request, project_name="MMC_CASE", folder=str(tmp_path))
    source_library = Path(plan["engine_plans"][0]["source_paths"]["library"])
    target = tmp_path / "intermediate.pslx"
    original_contents = source_library.read_bytes()
    target.write_bytes(original_contents)
    original_load = service.pscad_service.load_projects

    async def mutating_load(filenames: list[str]) -> str:
        result = await original_load(filenames)
        for filename in filenames:
            path = Path(filename)
            if path.name.casefold() == "intermediate.pslx" and path.parent == tmp_path:
                path.write_text("mutated pre-existing library", encoding="utf-8")
        return result

    service.pscad_service.load_projects = mutating_load

    started = asyncio.run(
        service.build_model(
            request,
            plan["plan_hash"],
            "MMC_CASE",
            str(tmp_path),
            confirm=True,
        )
    )
    terminal = wait_for_terminal(service, started["build_id"])

    assert terminal["state"] == "failed"
    assert terminal["error"]["code"] == "MMC_POSTCONDITION_FAILED"
    assert target.read_bytes() == original_contents
    assert not (tmp_path / "MMC_CASE_pwm.pscx").exists()


def test_failed_postcopy_hash_read_removes_unverified_pwm_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_parametric_service(tmp_path)
    target = tmp_path / "intermediate.pslx"
    original_sha256 = parametric_service_module._sha256

    def failing_target_hash(path: Path) -> str:
        if Path(path).resolve() == target.resolve() and target.exists():
            raise PermissionError("injected final library hash failure")
        return original_sha256(path)

    monkeypatch.setattr(parametric_service_module, "_sha256", failing_target_hash)

    _, terminal = _build(
        service, tmp_path, valid_request(model_fidelity="detailed_pwm")
    )

    assert terminal["state"] == "failed"
    assert not target.exists()
