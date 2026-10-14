"""Recompute PWM acceptance from frozen models, schedules and complete traces."""

from __future__ import annotations

import json
from pathlib import Path

from .pwm_output import digest, read_routed_pwm_run
from .pwm_physical import evaluate_routed_pwm_samples
from .scenarios import _SCENARIOS
from .timed_control import read_event_evidence


def evidence_index_path(project):
    return Path(project).with_suffix(".pwm-acceptance.json")


def freeze_routed_manifest(manifest_path):
    """Include every input, model, metadata part and output in the evidence seal."""
    path = Path(manifest_path)
    manifest = json.loads(path.read_text())
    files = {}

    def add(filename, expected=None):
        filename = str(Path(filename).resolve())
        observed = digest(filename)
        if expected is not None and observed != expected:
            raise RuntimeError("PWM evidence changed before freezing: " + filename)
        files[filename] = observed

    add(path)
    add(manifest["channel_contract"])
    for item in manifest["runs"]:
        for key in ("project", "scenario", "report", "physical_report"):
            add(item[key])
        report = json.loads(Path(item["report"]).read_text())
        for filename, expected in report["original_inputs"].items():
            add(filename, expected)
        physical = json.loads(Path(item["physical_report"]).read_text())
        for metadata in physical["dataset"]["files"].values():
            add(metadata["path"], metadata["sha256"])
    return {
        "schema_version": 1,
        "manifest": str(path.resolve()),
        "project_sha256": manifest["project_sha256"],
        "tested_commit": manifest["tested_commit"],
        "files": files,
    }


async def validate_routed_pwm(project, output_files):
    """A reader PASS or a JSON PASS alone cannot establish converter acceptance."""
    index = json.loads(evidence_index_path(project).read_text())
    if digest(project) != index["project_sha256"]:
        raise RuntimeError("The delivered PWM project differs from its measured input")
    for filename, expected in index["files"].items():
        if digest(filename) != expected:
            raise RuntimeError("Frozen PWM evidence changed: " + filename)
    manifest = json.loads(Path(index["manifest"]).read_text())
    if (
        manifest["tested_commit"] != index["tested_commit"]
        or manifest["project_sha256"] != index["project_sha256"]
        or [item["name"] for item in manifest["runs"]]
        != [*_SCENARIOS, "delivery", "independent_reload"]
    ):
        raise RuntimeError("The full PWM scenario matrix or revision is incomplete")
    delivery = json.loads(Path(manifest["runs"][-2]["report"]).read_text())
    requested = {str(Path(p).resolve()) for p in output_files}
    if not requested or not requested <= set(delivery["output_files"]):
        raise RuntimeError("The supplied outputs do not belong to the measured delivery")
    baseline = json.loads(Path(manifest["channel_contract"]).read_text())
    results = []
    for item in manifest["runs"]:
        report = json.loads(Path(item["report"]).read_text())
        if report.get("tested_commit") != manifest["tested_commit"]:
            raise RuntimeError("PWM runs do not share the frozen producer revision")
        scenario = json.loads(Path(item["scenario"]).read_text())
        samples, contract = await read_routed_pwm_run(
            report, Path(item["project"]), scenario, baseline,
        )
        physical = evaluate_routed_pwm_samples(samples, contract, scenario)
        if physical["status"] != "PASS":
            raise RuntimeError("Independent PWM physical reevaluation failed: " + item["name"])
        if scenario.get("timed_control") and item["name"] in _SCENARIOS:
            read_event_evidence(
                scenario["timed_control"], Path(item["project"]),
                [Path(p) for p in report["output_files"]],
                started_after=report["run_started_after"],
            )
        results.append({"name": item["name"], "checks": len(physical["checks"]), "verdict": "PASS"})
    reload_report = json.loads(Path(manifest["runs"][-1]["report"]).read_text())
    if (
        reload_report["runtime"]["session"]["managed_pid"]
        == delivery["runtime"]["session"]["managed_pid"]
        or reload_report.get("remaining_owned_processes") != []
    ):
        raise RuntimeError("Independent PWM reload ownership or cleanup is incomplete")
    return {
        "status": "evaluated", "scope": "full", "verdict": "PASS",
        "tested_commit": manifest["tested_commit"], "scenario_results": results,
        "evidence_index": str(evidence_index_path(project)),
        "intrinsic_dc_fault_blocking": False,
    }
