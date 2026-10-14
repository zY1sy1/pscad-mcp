"""Retry publication defects only after rechecking an immutable electrical matrix."""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from copy import deepcopy
from pathlib import Path

from ....core.backend.base import BackendError
from .engines.pwm import PwmTemplateEngine, _source_files, _verify_sources
from .pwm_output import digest, read_routed_pwm_run
from .pwm_physical import evaluate_routed_pwm_samples
from .pwm_runtime import complete_output_paths, write_report
from .pwm_validation import SCENARIOS


def read_recoverable_matrix(report_file):
    report = json.loads(Path(report_file).read_text())
    if (
        report.get("stage") != "finished"
        or report.get("sources_immutable") is not True
        or report.get("remaining_owned_processes") != []
    ):
        raise RuntimeError(
            "Only a finished, immutable, cleaned-up matrix can be republished"
        )
    engines = report.get("parent_status", {}).get("engines", [])
    candidate = engines[0].get("candidate_result") if len(engines) == 1 else None
    if (
        not candidate
        or candidate.get("model_accepted") is not True
        or candidate.get("routed_physical_acceptance") is not True
        or [s["name"] for s in candidate.get("scenario_results", [])] != list(SCENARIOS)
        or candidate.get("independent_reload_accepted") is not True
    ):
        raise RuntimeError(
            "A complete accepted eleven-scenario electrical matrix and independent reload are required"
        )
    return report, candidate


class FrozenPwmPublicationEngine(PwmTemplateEngine):
    def __init__(self, report_file, progress):
        self.report_file = Path(report_file).resolve()
        self.report_hash = digest(self.report_file)
        self.report, self.candidate = read_recoverable_matrix(self.report_file)
        self.progress = progress

    async def execute_candidate(
        self, plan, service, *, candidate_id=None, scenario_service=None, scenarios=None
    ):
        if candidate_id not in (None, "pwm-0") or [
            s["name"] for s in scenarios or []
        ] != list(SCENARIOS):
            raise RuntimeError(
                "Publication recovery cannot alter or truncate the scenario matrix"
            )
        old_plan = self.report["plan"]["engine_plans"][0]
        if (
            dict(plan.source_hashes) != old_plan["source_hashes"]
            or dict(plan.asset_hashes) != old_plan["asset_hashes"]
            or plan.capabilities["routed_pwm_preparation"]["request"]
            != self.report["plan"]["request"]
        ):
            raise RuntimeError(
                "Publication recovery requires the exact measured request and source/compiler identities"
            )
        _verify_sources(plan, _source_files(plan))
        manifest_file = Path(self.candidate["validation"]["physical_evidence"])
        manifest = json.loads(manifest_file.read_text())
        if manifest["model_accepted"] is not True or [
            s["name"] for s in manifest["scenario_results"]
        ] != list(SCENARIOS):
            raise RuntimeError(
                "The frozen electrical acceptance manifest is incomplete"
            )
        for path, expected in manifest["evidence_files"].items():
            if digest(path) != expected:
                raise RuntimeError("A frozen electrical evidence file changed")
        for path, expected in manifest["original_inputs"].items():
            if digest(path) != expected:
                raise RuntimeError("An original electrical input changed")
        baseline = json.loads(Path(manifest["baseline_channel_contract"]).read_text())
        delivery = manifest["delivery"]
        reload = manifest["independent_reload"]
        parent_report = json.loads(
            (Path(delivery["project"]).parent / "report.json").read_text()
        )
        reload_report = json.loads(Path(reload["report"]).read_text())
        if (
            reload_report.get("remaining_owned_processes") != []
            or reload_report["runtime"]["session"]["managed_pid"]
            == parent_report["runtime"]["session"]["managed_pid"]
            or reload_report["original_inputs"].get(delivery["project"])
            != manifest["project_sha256"]
        ):
            raise RuntimeError("The frozen independent reload is not valid")
        scenes = [
            *manifest["scenario_results"],
            delivery,
            {"name": "independent_reload", "project": reload["project"]},
        ]
        root = Path(__file__).resolve().parents[4]
        results = []
        for scene in scenes:
            directory = Path(scene["project"]).parent
            report = json.loads((directory / "report.json").read_text())
            for path, expected in report["producer_hashes"].items():
                if digest(root / path) != expected:
                    raise RuntimeError(
                        "Electrical producer code changed; fresh electrical runs are required"
                    )
            scenario_directory = (
                Path(delivery["project"]).parent
                if scene["name"] == "independent_reload"
                else directory
            )
            scenario = json.loads((scenario_directory / "scenario.json").read_text())
            samples, contract = await read_routed_pwm_run(
                report, scene["project"], scenario, baseline
            )
            physical = evaluate_routed_pwm_samples(samples, contract, scenario)
            del samples
            if physical["status"] != "PASS":
                raise BackendError(
                    "MMC_PHYSICAL_ACCEPTANCE_FAILED",
                    "Publication recovery has no complete passing physical matrix.",
                    "hvdc",
                    "recover_pwm_publication",
                    {
                        "scenario": scene["name"],
                        "checks": [c for c in physical["checks"] if not c["passed"]],
                    },
                )
            results.append(
                {
                    "scenario": scene["name"],
                    "checks": len(physical["checks"]),
                    "status": "PASS",
                }
            )
            self.progress(results)
        source = Path(delivery["project"])
        if (
            source.stem != plan.target_name
            or digest(source) != manifest["project_sha256"]
        ):
            raise RuntimeError(
                "Publication recovery cannot rename or change the measured model"
            )
        if digest(self.report_file) != self.report_hash:
            raise RuntimeError("The completed matrix report changed during recovery")
        directory = Path(plan.workspace) / ".verified-pwm-matrix"
        directory.mkdir(exist_ok=False)
        project = directory / source.name
        shutil.copy2(source, project)
        library = source.parent / "intermediate.pslx"
        # Keep the loaded input's saved file intact during the publisher's move.
        if digest(project) != manifest["project_sha256"]:
            raise RuntimeError(
                "Loading the publication input changed its frozen identity"
            )
        result = deepcopy(self.candidate)
        result.update(
            project_path=str(project),
            candidate_path=str(directory),
            library_path=str(library),
            recovered_matrix={
                "report": str(self.report_file),
                "report_sha256": self.report_hash,
                "matrix_plan_hash": manifest["plan_hash"],
                "physical_revalidation": results,
            },
        )
        return result


async def verify_publication_in_worker(
    service, project, library, manifest_file, configured_root, support
):
    """A fresh owned process avoids resetting any unsaved waveform session."""
    import sys

    from ....acceptance.process_scope import require_acceptance_ownership

    runtime = await service.status()
    require_acceptance_ownership(runtime)
    manifest = json.loads(manifest_file.read_text())
    directory = project.parent / ".publication-check"
    directory.mkdir(exist_ok=False)
    inputs = {
        str(project): manifest["project_sha256"],
        str(library): digest(library),
        **{item["path"]: item["sha256"] for item in support},
    }
    inputs[str(manifest_file)] = digest(manifest_file)
    job = {
        "project": str(project),
        "library": str(library),
        "manifest": str(manifest_file),
        "configured_root": str(configured_root),
        "directory": str(directory),
        "parent_managed_pid": runtime["session"]["managed_pid"],
        "inputs": inputs,
    }
    job_file = directory / "job.json"
    job_file.write_text(json.dumps(job, indent=2))
    worker = await asyncio.create_subprocess_exec(
        sys.executable,
        "-B",
        "-m",
        "pscad_mcp.hvdc.builders.mmc.publication_recovery",
        "--publication-job",
        str(job_file),
        cwd=Path(__file__).resolve().parents[4],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await worker.communicate()
    (directory / "worker.json").write_text(
        json.dumps(
            {
                "returncode": worker.returncode,
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
            },
            indent=2,
        )
    )
    report_file = directory / "report.json"
    if worker.returncode != 0:
        raise BackendError(
            "MMC_PUBLICATION_ACCEPTANCE_FAILED",
            "The independent publication worker failed.",
            "hvdc",
            "publish_pwm_model",
            {"report": str(report_file), "worker": str(directory / "worker.json")},
        )
    report = json.loads(report_file.read_text())
    if (
        report["status"] != "PASS"
        or report["stage"] != "finished"
        or report["sources_immutable"] is not True
        or report["remaining_owned_processes"] != []
        or report["runtime"]["session"]["managed_pid"] == job["parent_managed_pid"]
    ):
        raise RuntimeError(
            "No immutable, cleaned-up independent publication was established"
        )
    return {
        "status": "PASS",
        "report": str(report_file),
        "report_sha256": digest(report_file),
        "managed_pid": report["runtime"]["session"]["managed_pid"],
        "parent_managed_pid": job["parent_managed_pid"],
        "normal": report["normal"],
        "build_messages": report["build_messages"],
    }


async def publication_job(job):
    from ....acceptance.preflight_cli import _service
    from ....acceptance.process_scope import require_acceptance_ownership
    from .pwm_runtime import cleanup_owned

    directory = Path(job["directory"])
    project = Path(job["project"])
    report = {
        "schema_version": 1,
        "scope": "mmc.detailed_pwm.independent_publication",
        "status": "FAIL",
        "stage": "prepare",
        "model_accepted": False,
        "original_inputs": job["inputs"],
        "parent_managed_pid": job["parent_managed_pid"],
    }

    def checkpoint():
        write_report(directory / "report.json", report)

    service = _service(Path(job["configured_root"]))
    runtime = None
    try:
        if any(digest(p) != h for p, h in job["inputs"].items()):
            raise RuntimeError(
                "The published input or compiler support changed before loading"
            )
        await service.attach_local()
        runtime = await service.status()
        require_acceptance_ownership(runtime)
        report["runtime"] = runtime
        if (
            runtime["licensed"] is not True
            or runtime["session"]["managed_pid"] == job["parent_managed_pid"]
        ):
            raise RuntimeError(
                "Publication requires a distinct licensed owned instance"
            )
        report["stage"] = "load"
        checkpoint()
        await service.load_projects([job["library"], job["project"]])
        report["build_result"] = await service.build_project(project.stem)
        report["build_messages"] = await service.get_project_output(
            project.stem, structured=True
        )
        if any(
            str(m.get("severity", "")).casefold() in {"error", "fatal"}
            for m in report["build_messages"]
        ):
            raise RuntimeError(
                "The actual published file did not compile with its delivered libraries"
            )
        manifest = json.loads(Path(job["manifest"]).read_text())
        report["normal"] = await verify_published_normal(
            service,
            project,
            manifest,
            directory,
            lambda state: publication_progress(report, checkpoint, state),
        )
        report["status"] = "PASS"
    except Exception as error:  # noqa: BLE001 - preserve the isolated attempt
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        report["status"] = "FAIL"
    finally:
        await cleanup_owned(
            service, project.stem, runtime, job["inputs"], report, checkpoint, False
        )
        report["stage"] = "finished"
        checkpoint()
    return 0 if report["status"] == "PASS" else 1


def publication_progress(report, checkpoint, state):
    report["normal_progress"] = {
        k: state.get(k) for k in ("stage", "status", "run_state", "error")
    }
    checkpoint()


async def verify_published_normal(service, project, manifest, workspace, progress):
    """Run the actual published file against its copied libraries, then freeze it."""
    project = Path(project)
    directory = Path(workspace) / "published-normal-evidence"
    directory.mkdir(exist_ok=False)
    scene = json.loads(
        (Path(manifest["delivery"]["project"]).parent / "scenario.json").read_text()
    )
    baseline = json.loads(Path(manifest["baseline_channel_contract"]).read_text())
    library = project.parent / "intermediate.pslx"
    report = {
        "schema_version": 1,
        "scope": "mmc.detailed_pwm.published_normal",
        "status": "FAIL",
        "stage": "run",
        "model_accepted": False,
        "runtime": await service.status(),
        "saved_project_sha256": digest(project),
        "original_inputs": {
            str(project): digest(project),
            str(library): digest(library),
        },
        "cleanup_mode": "caller_retains_owned_instance",
    }

    def checkpoint():
        write_report(directory / "report.json", report)
        progress(report)

    pending = False
    try:
        checkpoint()
        report["run_started_after"] = time.time()
        pending = True
        report["run_result"] = await service.run_project(project.stem)
        deadline = time.monotonic() + 900
        while True:
            state = await service.get_run_status(project.stem)
            report["run_state"] = state
            checkpoint()
            status = str(state.get("status", "")).casefold()
            if status in {"idle", "complete", "completed"}:
                paths = complete_output_paths(
                    project.parent,
                    project.stem,
                    started_after=report["run_started_after"],
                    duration_s=scene["duration_s"],
                    output_step_s=scene["output_step_s"],
                )
                if paths:
                    pending = False
                    break
            if (
                status in {"failed", "interrupted", "stopped"}
                or time.monotonic() > deadline
            ):
                raise RuntimeError(
                    "The actual published model did not finish its normal run"
                )
            await asyncio.sleep(0.5)
        report["output_files"] = {str(p): digest(p) for p in paths}
        report["sources_immutable"] = all(
            digest(p) == h for p, h in report["original_inputs"].items()
        )
        report["status"], report["stage"] = "PASS", "finished"
        checkpoint()
        samples, contract = await read_routed_pwm_run(report, project, scene, baseline)
        physical = evaluate_routed_pwm_samples(samples, contract, scene)
        (directory / "physical.json").write_text(
            json.dumps(
                {
                    "physical": physical,
                    "channel_contract": contract,
                    "dataset": samples["identity"],
                    "run_report_sha256": digest(directory / "report.json"),
                },
                indent=2,
            )
        )
        if physical["status"] != "PASS":
            raise RuntimeError(
                "The actual published model did not pass normal physical acceptance"
            )
        return {
            "status": "PASS",
            "checks": len(physical["checks"]),
            "report": str(directory / "report.json"),
            "physical_report": str(directory / "physical.json"),
            "project_sha256": digest(project),
        }
    except Exception as error:
        report["status"], report["stage"] = "FAIL", "finished"
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        checkpoint()
        raise
    finally:
        if pending:
            await service.stop_simulation(project.stem)


def main():
    import argparse
    import os

    from ....core.executor import robust_executor

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication-job", type=Path, required=True)
    args = parser.parse_args()
    for key in ("PSCAD_MCP_ACCEPTANCE", "PSCAD_MCP_MMC_ACCEPTANCE"):
        if os.getenv(key) != "1":
            raise SystemExit(key + "=1 is required")
    try:
        return asyncio.run(
            publication_job(json.loads(args.publication_job.read_text()))
        )
    finally:
        robust_executor.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
