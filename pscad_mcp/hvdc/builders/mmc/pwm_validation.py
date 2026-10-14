"""Re-evaluate the exact frozen public PWM evidence, never a finite-data verdict."""

from __future__ import annotations

import json
from pathlib import Path

from .pwm_output import digest, read_routed_pwm_run
from .pwm_physical import evaluate_routed_pwm_samples

SCENARIOS = (
    "startup",
    "forward_steady",
    "active_power_step",
    "reactive_power_step",
    "power_reversal",
    "reverse_steady",
    "ac_three_phase_fault",
    "ac_single_line_ground_fault",
    "dc_pole_to_pole_fault",
    "dc_pole_to_ground_fault",
    "post_fault_recovery",
)


async def validate_routed_pwm_evidence(project, output_files, scope, workspace):
    project, workspace = Path(project).resolve(), Path(workspace).resolve()
    incomplete = {
        "status": "evaluated",
        "scope": scope,
        "verdict": "INCOMPLETE_ANALYSIS",
    }
    manifest_file = project.with_name(project.stem + "_acceptance.json")
    if not manifest_file.is_file():
        return {
            **incomplete,
            "reason": "No frozen physical acceptance manifest binds this detailed PWM model.",
        }
    try:
        manifest = json.loads(manifest_file.read_text())
        if (
            manifest["scope"] != "mmc.detailed_pwm.routed_reference"
            or manifest["model_accepted"] is not True
            or manifest["project_sha256"] != digest(project)
            or manifest["publication"]["project_sha256"] != digest(project)
        ):
            raise RuntimeError(
                "The delivered model does not match its accepted identity"
            )
        for path, expected in manifest["evidence_files"].items():
            resolved = Path(path).resolve()
            if workspace not in resolved.parents or digest(resolved) != expected:
                raise RuntimeError(
                    "A frozen physical evidence file changed or escaped its workspace"
                )
        for path, expected in manifest["original_inputs"].items():
            if digest(path) != expected:
                raise RuntimeError("An original PWM input changed")
        scenes = manifest["scenario_results"]
        if [s["name"] for s in scenes] != list(SCENARIOS):
            raise RuntimeError("All eleven distinct PWM scenarios are required")
        baseline = json.loads(Path(manifest["baseline_channel_contract"]).read_text())
        delivery = manifest["delivery"]
        supplied = {str(Path(p).resolve()) for p in output_files}
        if not supplied or not supplied <= set(delivery["outputs"]):
            raise RuntimeError(
                "Supplied outputs do not belong to the measured delivery"
            )
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
            raise RuntimeError(
                "The independent reload has no distinct, cleaned-up owned process"
            )
        selected = (
            scenes
            if scope == "full"
            else [s for s in scenes if ("fault" in s["name"]) == (scope == "fault")]
        )
        selected = [
            *selected,
            delivery,
            {"name": "independent_reload", "project": reload["project"]},
        ]
        results = []
        root = Path(__file__).resolve().parents[4]
        for scene in selected:
            directory = Path(scene["project"]).parent
            report = json.loads((directory / "report.json").read_text())
            for path, expected in report["producer_hashes"].items():
                if digest(root / path) != expected:
                    raise RuntimeError(
                        "The PWM evidence producer changed after its measured run"
                    )
            scenario_path = (
                Path(delivery["project"]).parent
                if scene["name"] == "independent_reload"
                else directory
            ) / "scenario.json"
            scenario = json.loads(scenario_path.read_text())
            samples, contract = await read_routed_pwm_run(
                report, scene["project"], scenario, baseline
            )
            physical = evaluate_routed_pwm_samples(samples, contract, scenario)
            del samples
            if physical["status"] != "PASS":
                return {
                    **incomplete,
                    "verdict": physical["status"],
                    "scenario": scene["name"],
                    "failed_checks": [c for c in physical["checks"] if not c["passed"]],
                }
            results.append(
                {
                    "scenario": scene["name"],
                    "checks": len(physical["checks"]),
                    "verdict": "PASS",
                }
            )
        return {
            "status": "evaluated",
            "scope": scope,
            "verdict": "PASS",
            "physical_runs": results,
            "manifest": str(manifest_file),
            "manifest_sha256": digest(manifest_file),
        }
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        return {**incomplete, "reason": str(error)}
