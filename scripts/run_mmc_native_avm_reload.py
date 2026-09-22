"""Independently reload and rerun a frozen, passing native AVM bundle."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
import time
import uuid
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from pscad_mcp.acceptance.project_finalization import GENERATED_MODULE_POLICY, snapshot_project_semantics, compare_project_finalization
from pscad_mcp.acceptance.executable_finalization import verify_executable_relink
from pscad_mcp.core.process_inventory import list_pscad_processes
from pscad_mcp.hvdc.builders.mmc.engines.avm import _native_producer_hashes
from pscad_mcp.hvdc.builders.mmc.native_bundle import audit_native_avm_fixture
from pscad_mcp.hvdc.builders.mmc.native_portable import copy_native_bundle
from pscad_mcp.hvdc.builders.mmc.native_startup import analyze_precharge_trace
from pscad_mcp.hvdc.builders.mmc.native_envelope import evaluate_native_steady_envelope
from pscad_mcp.hvdc.builders.mmc.native_physical import evaluate_native_network_identities
from pscad_mcp.hvdc.builders.mmc.native_control_checks import evaluate_native_dq_controls
from pscad_mcp.hvdc.builders.mmc.native_dynamic_checks import evaluate_native_dynamic_envelope
from pscad_mcp.hvdc.builders.mmc.native_faults import evaluate_native_fault_trace
from scripts.run_mmc_native_avm_public_acceptance import _require_complete_trace, _code_snapshot
from scripts.run_mmc_average_arm_acceptance import _probe_owners, _require_no_errors, fresh_project_executable, read_arm_trace, require_finalized_hashes
from scripts.run_mmc_native_probe_acceptance import _service, _sha256, _stamp, _write_report, _error, require_runtime, cleanup_owned_session, discover_run_outputs


def _evaluate(trace: dict, fixture: dict) -> dict:
    p = fixture["parameters"]
    _require_complete_trace(trace, p)
    prefix = trace
    result = {}
    if p.get("fault_kind") is not None:
        result["fault"] = evaluate_native_fault_trace(trace, p)
        start = next((v for v in trace["FAULT_START"] if v >= 0), None)
        if start is None:
            raise ValueError("Replay did not reproduce its declared fault")
        count = sum(t < start for t in trace["time"])
        prefix = {name: values[:count] for name, values in trace.items()}
    result["precharge"] = precharge = analyze_precharge_trace(prefix, p)
    if precharge["status"] != "PASS":
        return result
    windows = precharge["operating_windows"]
    result["steady"] = evaluate_native_steady_envelope(trace, power_mw=p["active_power_order_mw"], voltage_kv=p["vdc_order_kv"],
        reactive_mvar=p["reactive_power_order_mvar"], forward_window_s=windows["forward"], reverse_window_s=windows["reverse"])
    result["network"] = evaluate_native_network_identities(trace, capacitance_f=p["arm"]["C_eq_F"],
        grounding_resistance_ohm=p["dc_grounding_resistance_ohm"], valve_grounding_resistance_ohm=p["valve_grounding_resistance_ohm"],
        voltage_kv=p["vdc_order_kv"], frequency_hz=p["frequency_hz"], windows=windows,
        neutral_grounded=p.get("neutral_grounded", False), neutral_resistance_ohm=p.get("neutral_resistance_ohm", 350.0))
    result["controls"] = evaluate_native_dq_controls(trace, p, windows)
    result["dynamics"] = evaluate_native_dynamic_envelope(prefix, p, precharge)
    return result


async def run_attempt(args, directory: Path) -> dict:
    for variable in ("PSCAD_MCP_ACCEPTANCE", "PSCAD_MCP_NATIVE_AVM_RELOAD_ACCEPTANCE"):
        if os.environ.get(variable) != "1":
            raise PermissionError(variable + "=1 is required")
    report = {"scope": "native_avm_independent_portable_reload", "status": "FAIL", "model_accepted": False,
              "started_at": _stamp(), "source_report": str(args.source_report.resolve())}
    service = None
    runtime = {}
    project_name = None
    run_pending = False
    original = {}
    report_path = directory / "report.json"
    try:
        source = json.loads(args.source_report.read_text(encoding="utf-8"))
        report["source_report_sha256"] = _sha256(args.source_report)
        if (source.get("status") != "PASS" or source.get("source_inputs_immutable") is not True
                or source.get("source_code_immutable") is not True or source.get("cleanup", {}).get("owned_process_cleaned") is not True
                or source.get("diagnostic_control_kind") != "dq_current" or source.get("timestep_diagnostic")):
            raise ValueError("Independent reload requires a frozen passing dq source without diagnostic overrides")
        producers = source["plan"]["engine_plans"][0]["capabilities"]["native_producer_hashes"]
        if producers != _native_producer_hashes():
            raise ValueError("The native producer changed after source acceptance")
        before = _code_snapshot()
        before["source_code_hashes"][str(Path(__file__).resolve())] = _sha256(Path(__file__))
        helper = REPOSITORY / "pscad_mcp/hvdc/builders/mmc/native_portable.py"
        before["source_code_hashes"][str(helper)] = _sha256(helper)
        report["code_before"] = before
        if before["working_tree_status"]:
            raise ValueError("Independent reload requires a clean frozen checkout")
        candidate = source["build_terminal"]["engines"][0]["candidate_result"]
        original = source["finalized_hashes_after_run"]
        report["portable_copy"] = copied = copy_native_bundle(Path(candidate["project_path"]), Path(candidate["library_path"]), original, directory / "model")
        project, library = Path(copied["project_path"]), Path(copied["library_path"])
        project_name = project.stem
        fixture = copy.deepcopy(candidate["fixture"])
        fixture["project_path"] = str(project)
        fixture["library"]["library_path"] = str(library)
        fixture["library"]["library_sha256"] = _sha256(library)
        report["fixture"] = fixture
        report["processes_before"] = list_pscad_processes()
        service = _service(directory)
        report["attach_result"] = await asyncio.wait_for(service.attach_local(), 180)
        runtime = await service.status()
        report["runtime"] = runtime
        require_runtime(runtime)
        snapshots = {str(path): snapshot_project_semantics(path, policy=GENERATED_MODULE_POLICY) for path in (project, library)}
        await service.load_projects([str(library), str(project)])
        for path in (library, project):
            await service.save_project(path.stem, confirm=True)
        native = await service.backend._project(project_name)
        await service.backend.executor.run_safe(native.clean, timeout=180)
        compile_started = time.time()
        report["compile_result"] = await asyncio.wait_for(service.build_project(project_name), 900)
        report["compile_messages"] = await service.get_project_output(project_name, structured=True)
        _require_no_errors(report["compile_messages"])
        for path in (library, project):
            await service.save_project(path.stem, confirm=True)
        report["finalization"] = {str(path): compare_project_finalization(snapshots[str(path)], snapshot_project_semantics(path, policy=GENERATED_MODULE_POLICY)) for path in (project, library)}
        report["topology"] = audit_native_avm_fixture(project, fixture, finalized_library_sha256=_sha256(library))
        inputs = {name: _sha256(Path(name)) for name in copied["copied_hashes"]}
        executable = fresh_project_executable(project, compile_started)
        report["fresh_executable"] = executable
        executable_before = {**inputs, executable["path"]: executable["sha256"]}
        owners = _probe_owners(project, channel_units=fixture["channels"])
        run_started = time.time()
        run_pending = True
        await service.run_project(project_name)
        deadline = time.monotonic() + 300
        while True:
            state = await service.get_run_status(project_name)
            status = str(state.get("status", "")).lower()
            if status in {"completed", "complete", "idle"}:
                run_pending = False
                break
            if status in {"failed", "stopped", "interrupted"} or time.monotonic() > deadline:
                raise RuntimeError("Independent native replay did not complete: " + status)
            await asyncio.sleep(0.5)
        report["run_messages"] = await service.get_project_output(project_name, structured=True)
        _require_no_errors(report["run_messages"])
        report["executable_relink"] = verify_executable_relink(executable_before, executable["path"])
        files = discover_run_outputs(project, run_started, metadata_started_after=compile_started)
        output_hashes = {str(path): _sha256(Path(path)) for path in (*files["parts"], files["inf"], files["infx"])}
        report["outputs"] = {key: [str(p) for p in value] if isinstance(value, list) else str(value) for key, value in files.items()}
        observed = read_arm_trace(files, owners, channel_units=fixture["channels"])
        report["output_hashes_after_read"] = require_finalized_hashes(output_hashes)
        report["channel_sources"] = observed["channel_sources"]
        _write_report(directory / "trace.json", observed["samples"])
        report["trace"] = {"path": str(directory / "trace.json"), "sha256": _sha256(directory / "trace.json")}
        report["analysis"] = _evaluate(observed["samples"], fixture)
        report["finalized_hashes_after_run"] = require_finalized_hashes(inputs)
        report["status"] = "PASS" if all(item.get("status") == "PASS" for item in report["analysis"].values()) else "FAIL"
    except BaseException as error:
        report["error"] = _error(error)
    finally:
        if service is not None:
            try:
                report["cleanup"] = await cleanup_owned_session(service, runtime or await service.status(), project_name=project_name, run_pending=run_pending, timeout=30)
                if not report["cleanup"].get("owned_process_cleaned") or report["cleanup"].get("errors"):
                    report["status"] = "FAIL"
            except BaseException as error:
                report.update(status="FAIL", cleanup_error=_error(error))
        try:
            report["source_hashes_after"] = require_finalized_hashes(original)
            report["source_inputs_immutable"] = _sha256(args.source_report) == report["source_report_sha256"]
            report["source_code_immutable"] = (_code_snapshot()["commit"] == report["code_before"]["commit"]
                and all(_sha256(Path(p)) == digest for p, digest in report["code_before"]["source_code_hashes"].items()))
            if not report["source_inputs_immutable"] or not report["source_code_immutable"]:
                report["status"] = "FAIL"
        except BaseException as error:
            report.update(status="FAIL", finalization_error=_error(error))
        report["finished_at"] = _stamp()
        _write_report(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", required=True, type=Path)
    parser.add_argument("--workspace-root", required=True, type=Path)
    args = parser.parse_args()
    if not args.workspace_root.is_absolute():
        parser.error("Workspace must be absolute")
    for variable in ("PSCAD_MCP_ACCEPTANCE", "PSCAD_MCP_NATIVE_AVM_RELOAD_ACCEPTANCE"):
        if os.environ.get(variable) != "1":
            parser.error(variable + "=1 is required before creating a workspace")
    directory = args.workspace_root / (time.strftime("attempt-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    result = asyncio.run(run_attempt(args, directory))
    print(json.dumps({"status": result["status"], "model_accepted": False, "report": str(directory / "report.json")}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
