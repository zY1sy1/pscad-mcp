"""Run the complete native AVM normal/fault suite and an independent reload."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from pscad_mcp.hvdc.builders.mmc.native_faults import FAULT_KINDS
from scripts.run_mmc_native_probe_acceptance import _write_report


def verify_suite(reports: dict[str, dict], reload_report: dict) -> dict:
    required = {"normal", *FAULT_KINDS}
    checks = {"all_scenarios_present": set(reports) == required}
    normal = reports.get("normal", {})
    request = normal.get("request")
    children = normal.get("plan", {}).get("engine_plans", [])
    producers = children[0].get("capabilities", {}).get("native_producer_hashes") if len(children) == 1 else None
    parameters = children[0].get("candidates", [{}])[0].get("parameters") if len(children) == 1 else None
    for name in required:
        report = reports.get(name, {})
        checks[name + ":passed"] = report.get("status") == "PASS" and report.get("diagnostic_control_kind") == "dq_current"
        checks[name + ":required_gates"] = all(report.get(k) is True for k in (
            "assembly_accepted", "precharge_accepted", "steady_operating_accepted", "network_identities_accepted", "control_envelope_accepted", "dynamic_envelope_accepted"))
        if name != "normal":
            checks[name + ":fault_gate"] = report.get("fault_envelope_accepted") is True and report.get("fault_envelope", {}).get("status") == "PASS"
        checks[name + ":immutable_cleaned"] = (report.get("source_inputs_immutable") is True and report.get("source_code_immutable") is True
            and report.get("cleanup", {}).get("owned_process_cleaned") is True and not report.get("cleanup", {}).get("errors"))
        checks[name + ":declared_scenario"] = report.get("fault_kind") == (None if name == "normal" else name) and not report.get("timestep_diagnostic")
        child = report.get("plan", {}).get("engine_plans", [])
        checks[name + ":same_physical_design"] = bool(producers) and bool(parameters) and report.get("request") == request and len(child) == 1 and child[0].get("capabilities", {}).get("native_producer_hashes") == producers and child[0].get("candidates", [{}])[0].get("parameters") == parameters
        checks[name + ":same_revision"] = bool(normal.get("code_before", {}).get("commit")) and report.get("code_before", {}).get("commit") == normal.get("code_before", {}).get("commit")
    checks["independent_reload"] = (reload_report.get("status") == "PASS" and reload_report.get("scope") == "native_avm_independent_portable_reload"
        and reload_report.get("source_inputs_immutable") is True and reload_report.get("source_code_immutable") is True
        and reload_report.get("cleanup", {}).get("owned_process_cleaned") is True and not reload_report.get("cleanup", {}).get("errors")
        and reload_report.get("portable_copy", {}).get("compiled_artifacts_copied") is False)
    checks["reload_physical_gates"] = all(reload_report.get("analysis", {}).get(name, {}).get("status") == "PASS"
                                           for name in ("precharge", "steady", "network", "controls", "dynamics"))
    passed = all(checks.values())
    return {"status": "PASS" if passed else "FAIL", "model_accepted": passed, "checks": checks,
            "failed_checks": [k for k, value in checks.items() if not value], "request": request,
            "intrinsic_dc_fault_blocking": False,
            "limitations": ["individual_submodule_balance_not_modeled", "switching_stress_not_modeled", "switching_harmonics_not_modeled", "thermal_not_modeled"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--request-json", type=Path)
    args = parser.parse_args()
    for name in ("PSCAD_MCP_ACCEPTANCE", "PSCAD_MCP_NATIVE_AVM_FULL_ACCEPTANCE"):
        if os.environ.get(name) != "1":
            parser.error(name + "=1 is required before running the suite")
    if not args.workspace_root.is_absolute():
        parser.error("Workspace must be absolute")
    root = args.workspace_root / (time.strftime("suite-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
    root.mkdir(parents=True, exist_ok=False)
    report = {"scope": "native_avm_full_physical_suite", "status": "FAIL", "model_accepted": False, "reports": {}}
    records = {}
    environment = {**os.environ, "PSCAD_MCP_NATIVE_AVM_PUBLIC_ACCEPTANCE": "1", "PSCAD_MCP_NATIVE_AVM_RELOAD_ACCEPTANCE": "1", "PSCAD_MCP_ACCEPTANCE_CONCURRENT": "1"}

    def run(name, command):
        print("MMC_FULL_STAGE=" + name, flush=True)
        process = subprocess.run(command, cwd=REPOSITORY, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (root / (name + ".log")).write_text(process.stdout, encoding="utf-8")
        summaries = []
        for line in process.stdout.splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and "report" in value:
                summaries.append(value)
        if len(summaries) != 1:
            raise RuntimeError(name + " did not produce one durable acceptance report")
        path = Path(summaries[0]["report"]).resolve()
        if not path.is_relative_to(root.resolve()) or path.is_symlink() or not path.is_file():
            raise ValueError("Child acceptance report escaped its suite directory")
        payload = json.loads(path.read_text(encoding="utf-8"))
        report["reports"][name] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "exit_code": process.returncode, "status": payload.get("status")}
        _write_report(root / "report.json", report)
        if process.returncode or payload.get("status") != "PASS":
            raise RuntimeError(name + " failed; its evidence is preserved")
        return payload, path

    try:
        normal_path = None
        for name in ("normal", *FAULT_KINDS):
            command = [sys.executable, "scripts/run_mmc_native_avm_public_acceptance.py", "--workspace-root", str(root / name), "--control-kind", "dq_current"]
            if args.request_json:
                command.extend(("--request-json", str(args.request_json.resolve())))
            if name != "normal":
                command.extend(("--fault-kind", name))
            records[name], path = run(name, command)
            if name == "normal":
                normal_path = path
        reloaded, _ = run("reload", [sys.executable, "scripts/run_mmc_native_avm_reload.py", "--workspace-root", str(root / "reload"), "--source-report", str(normal_path)])
        result = verify_suite(records, reloaded)
        result["checks"]["reload_matches_normal_report"] = reloaded.get("source_report_sha256") == report["reports"]["normal"]["sha256"]
        if not result["checks"]["reload_matches_normal_report"]:
            result.update(status="FAIL", model_accepted=False)
            result["failed_checks"].append("reload_matches_normal_report")
        report.update(result)
        if report["model_accepted"]:
            report["accepted_project"] = reloaded["portable_copy"]["project_path"]
            report["accepted_library"] = reloaded["portable_copy"]["library_path"]
            report["accepted_hashes"] = reloaded["finalized_hashes_after_run"]
    except BaseException as error:
        report.update(status="FAIL", model_accepted=False, error={"type": type(error).__name__, "message": str(error)})
    _write_report(root / "report.json", report)
    print(json.dumps({"status": report["status"], "model_accepted": report["model_accepted"], "report": str(root / "report.json")}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
