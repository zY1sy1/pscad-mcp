"""Public detailed-PWM execution with complete routed physical evidence."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

from ....core.backend.base import BackendError
from ...profiles import load_profile, register_profile
from .pwm_output import digest, read_routed_pwm_run
from .pwm_physical import evaluate_routed_pwm_samples
from .pwm_preparation import prepare_routed_pwm_case
from .pwm_runtime import run, write_report
from .pwm_scenarios import prepare_routed_scenario_source
from .scenarios import prepare_timed_scenario


def require_supported_request(request):
    expected = {
        "converter": "full_bridge",
        "dc_voltage_kv": 640.0,
        "active_power_mw": 1000.0,
        "reactive_power_mvar": 0.0,
        "frequency_hz": 60.0,
        "power_reversal_time_s": 0.5,
        "dc_link": {"kind": "overhead_line", "length_km": 200.0},
        "engineering_overrides": {},
    }
    for name in ("station_p", "station_vdc"):
        expected[name] = {
            "ac_voltage_kv": 230.0,
            "short_circuit_ratio": 5.0,
            "x_over_r": 10.0,
        }
    different = [key for key, value in expected.items() if request.get(key) != value]
    if different:
        raise BackendError(
            "MMC_PWM_PARAMETER_UNSUPPORTED",
            "The routed PWM producer supports the explicit audited reference point; these requested changes have no physical binding.",
            "hvdc",
            "plan_parametric_mmc_model",
            {"unsupported_fields": different, "supported_reference": expected},
        )


async def execute_routed_pwm_candidate(plan, service, candidate, scenarios):
    from .engines.pwm import (
        _source_files,
        _staging_paths,
        _verify_sources,
    )

    request = dict(plan.capabilities["routed_pwm_preparation"]["request"])
    require_supported_request(request)
    if candidate.purpose != "nominal":
        raise BackendError(
            "MMC_PWM_PARAMETER_UNSUPPORTED",
            "This PWM producer cannot partially apply a fallback candidate.",
            "hvdc",
            "execute_pwm_candidate",
        )
    if scenarios is None or [s["name"] for s in scenarios] != list(plan.scenarios):
        raise RuntimeError("All eleven immutable PWM scenarios are required")
    identity = await service.get_master_library_identity()
    master = Path(identity["master_path"])
    if (
        identity.get("pscad_version") != "4.6.2"
        or digest(master) != identity["master_sha256"]
    ):
        raise RuntimeError("The connected Master identity changed")
    sources = _source_files(plan)
    _verify_sources(plan, sources)
    stage, _, _ = _staging_paths(plan, candidate)
    stage.mkdir(parents=True)
    prepared = prepare_routed_pwm_case(
        sources["project"], sources["library"], master, stage / "prepared"
    )
    profile = load_profile("mmc_detailed_pwm_v2")
    profile.update(
        extends="mmc_detailed_pwm_v2",
        command_bindings=prepared["routing"]["command_bindings"],
    )
    profile["project_fingerprints"] = [
        {"project_stem": "H_MMC_Mono_DC", "pscad_version": "4.6.2"}
    ]
    profile_file = stage / "routed-profile.json"
    profile_file.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    profile_name = "mmc_pwm_routed_" + plan.plan_hash[:12]
    register_profile(profile_name, str(profile_file), workspace_root=stage)
    results, written = [], []

    async def execute(scenario, index, *, timed):
        scene = dict(scenario)
        scene["profile"] = profile_name
        source_dir = stage / "sources" / (scene["name"] if timed else "delivery")
        source_dir.mkdir(parents=True)
        scene = prepare_routed_scenario_source(
            prepared["project"], source_dir / "H_MMC_Mono_DC.pscx", scene
        )
        if timed:
            scene["timed_control_options"] = {
                "master_path": str(master),
                "max_timing_error_s": scene["time_step_s"] + scene["output_step_s"],
            }
            scene = prepare_timed_scenario(
                scene["project"], scene, workspace_root=stage
            )
        case_dir = stage / "runs" / (scene["name"] if timed else "delivery")
        case_dir.mkdir(parents=True)
        name = (
            "PWM_" + plan.plan_hash[:10] + "_" + str(index)
            if timed
            else plan.target_name
        )
        if len(name) > 30:
            raise RuntimeError(
                "The delivered EMTDC project namespace exceeds 30 characters"
            )
        scenario_file = case_dir / "scenario.json"
        scenario_file.write_text(json.dumps(scene, indent=2), encoding="utf-8")
        report = {
            "schema_version": 1,
            "status": "FAIL",
            "model_accepted": False,
            "stage": "prepare",
            "scope": "mmc.detailed_pwm.routed_scenario",
            "plan_hash": plan.plan_hash,
            "scenario": scene["name"],
            "duration_s": scene["duration_s"],
        }

        def checkpoint():
            write_report(case_dir / "report.json", report)

        args = SimpleNamespace(
            source=Path(scene["project"]),
            library=sources["library"],
            master=master,
            workspace=case_dir,
            case_name=name,
            duration=scene["duration_s"],
            scenario=scenario_file if timed else None,
            simulate=True,
            timeout=900,
            startup_timeout=30,
        )
        try:
            await run(args, report, checkpoint, service=service)
            report["stage"] = "finished"
            checkpoint()
        except BaseException as error:
            report["status"] = "FAIL"
            report["stage"] = "finished"
            report["error"] = (
                error.to_dict()
                if isinstance(error, BackendError)
                else {"type": type(error).__name__, "message": str(error)}
            )
            checkpoint()
            raise
        project = case_dir / (name + ".pscx")
        samples, contract = await read_routed_pwm_run(
            report, project, scene, prepared["channels"]
        )
        physical = evaluate_routed_pwm_samples(samples, contract, scene)
        evidence = {
            "physical": physical,
            "channel_contract": contract,
            "dataset": samples["identity"],
            "project_readback": samples["project_readback"],
            "run_report_sha256": digest(case_dir / "report.json"),
        }
        physical_file = case_dir / "physical.json"
        physical_file.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        if physical["status"] != "PASS":
            raise BackendError(
                "MMC_PHYSICAL_ACCEPTANCE_FAILED",
                "Routed PWM physical criteria were not satisfied.",
                "hvdc",
                "execute_pwm_candidate",
                {
                    "scenario": scene["name"],
                    "physical_report": str(physical_file),
                    "failed_checks": [c for c in physical["checks"] if not c["passed"]],
                },
            )
        written.extend(
            (
                str(project),
                str(scenario_file),
                str(physical_file),
                str(case_dir / "report.json"),
            )
        )
        return {
            "name": scene["name"],
            "status": "completed",
            "analysis": {"verdict": "PASS", "physical_evidence": str(physical_file)},
            "outputs": report["output_files"],
            "timing_evidence": report.get("timing_evidence"),
            "project": str(project),
        }

    for index, scene in enumerate(scenarios):
        results.append(await execute(scene, index, timed=True))
    forward = next(s for s in scenarios if s["name"] == "forward_steady")
    delivered = await execute(forward, 11, timed=False)
    reload_directory = stage / "independent-reload"
    reload_name = "PWM_RELOAD_" + plan.plan_hash[:10]
    delivery_directory = Path(delivered["project"]).parent
    delivery_report = json.loads((delivery_directory / "report.json").read_text())
    delivery_scene = json.loads((delivery_directory / "scenario.json").read_text())
    reload_job = {
        "source": delivered["project"],
        "source_sha256": digest(delivered["project"]),
        "library": str(sources["library"]),
        "master": str(master),
        "workspace": str(reload_directory),
        "case_name": reload_name,
        "scenario": delivery_scene,
        "channel_contract": prepared["channels"],
        "parent_managed_pid": delivery_report["runtime"]["session"]["managed_pid"],
    }
    job_file = stage / "independent-reload-job.json"
    job_file.write_text(json.dumps(reload_job, indent=2), encoding="utf-8")
    worker = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "pscad_mcp.hvdc.builders.mmc.pwm_reload",
        "--job",
        str(job_file),
        cwd=Path(__file__).resolve().parents[4],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await worker.communicate()
    (stage / "independent-reload-worker.json").write_text(
        json.dumps(
            {
                "returncode": worker.returncode,
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    reload_physical_file = reload_directory / "physical.json"
    if worker.returncode != 0:
        raise BackendError(
            "MMC_PHYSICAL_ACCEPTANCE_FAILED",
            "Independent PWM reload failed in its isolated worker.",
            "hvdc",
            "execute_pwm_candidate",
            {"report": str(reload_directory / "report.json")},
        )
    reload_physical = json.loads(reload_physical_file.read_text())["physical"]
    if reload_physical["status"] != "PASS":
        raise RuntimeError("Independent PWM reload has no passing physical evidence")
    _verify_sources(plan, sources)
    library = Path(delivered["project"]).parent / "intermediate.pslx"
    manifest = {
        "schema_version": 1,
        "scope": "mmc.detailed_pwm.routed_reference",
        "plan_hash": plan.plan_hash,
        "request": request,
        "model_accepted": True,
        "scenario_results": results,
        "delivery": delivered,
        "original_inputs": plan.source_hashes,
        "project_sha256": digest(delivered["project"]),
        "independent_reload": {
            "report": str(reload_directory / "report.json"),
            "physical_report": str(reload_physical_file),
            "status": "PASS",
        },
    }
    manifest_file = stage / "routed-acceptance.json"
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    publication_directory = stage / "publication"
    publication_directory.mkdir()
    publication_project = publication_directory / (plan.target_name + ".pscx")
    shutil.copy2(delivered["project"], publication_project)
    if digest(publication_project) != manifest["project_sha256"]:
        raise RuntimeError(
            "The publication copy differs from the frozen measured model"
        )
    return {
        "state": "accepted",
        "engine": "detailed_pwm",
        "candidate_id": candidate.candidate_id,
        "candidate_path": str(stage),
        "project_path": str(publication_project),
        "library_path": str(library),
        "library_support_path": str(library.parent / "Obj_Files_2016_03_25"),
        "model_accepted": True,
        "scenario_results": results,
        "written_paths": tuple(written),
        "validation": {
            "verdict": "PASS",
            "scenario_count": len(results),
            "physical_evidence": str(manifest_file),
        },
        "command_profile": profile_name,
        "independent_reload_accepted": True,
    }
