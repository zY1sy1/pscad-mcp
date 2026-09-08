"""Opt-in, owned-instance licensed full-bridge fault evidence acceptance."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pscad_mcp.acceptance.process_scope import (
    acceptance_launch_policy,
    remaining_acceptance_processes,
    require_acceptance_ownership,
)
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.process_inventory import list_pscad_processes
from pscad_mcp.hvdc.builders.mmc.fault_channels import (
    default_fault_checks,
    finalize_fault_instrumentation,
    instrument_fault_channels,
    materialize_dc_feedback_filter,
    materialize_terminal_two_carrier,
    materialize_voltage_control_headroom,
    read_fault_output_dataset,
    snapshot_output_dataset,
)
from pscad_mcp.hvdc.builders.mmc.line_constants import (
    generate_public_line_constants,
    rebind_template_line_constants,
)
from pscad_mcp.hvdc.builders.mmc.template_audit import (
    _compiler_support,
    discover_official_mmc_template,
)
from pscad_mcp.hvdc.builders.mmc.template_native import (
    evaluate_template_native_dc_fault,
    materialize_template_native_scenario,
)


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")


async def _with_owned_connection(service, backend, report, operation, *, process_reader=list_pscad_processes):
    try:
        await service.attach_local()
        report["launch_ownership"] = {"owns_process": backend.owns_process, "session": dict(backend.session_details)}
        if backend.owns_process is not True:
            raise RuntimeError("The acceptance connection does not own a managed launch")
        require_acceptance_ownership(report["launch_ownership"])
        report["runtime"] = await service.status()
        require_acceptance_ownership(report["runtime"])
        return await operation()
    finally:
        if getattr(backend, "owns_process", False):
            ownership = {"owns_process": True, "session": dict(backend.session_details)}
            report.setdefault("launch_ownership", ownership)
            try:
                if getattr(service, "_backend", backend) is backend or getattr(service, "_pending_cleanup_backend", None) is backend:
                    await service.quit_pscad(confirm=True)
                else:
                    await backend.quit()
                for _ in range(40):
                    if not remaining_acceptance_processes(ownership, process_reader):
                        report["owned_process_cleaned"] = True
                        break
                    await asyncio.sleep(0.25)
            except BaseException as error:  # noqa: BLE001 - preserve cleanup evidence without hiding original failure
                report["cleanup_error"] = str(error)


def _checks():
    return default_fault_checks()


def _steady(samples, contract, checks=None):
    checks = checks or contract.get("required_checks", {})
    if not checks:
        return {"verdict": "INCOMPLETE_ANALYSIS", "checks": [], "reason": "frozen steady checks are missing"}
    window = checks["recovery_window_s"]
    frequency = checks["frequency_hz"]
    cycle_count = round((window[1] - window[0]) * frequency)
    rows = []
    power = {}
    for binding in contract["channels"]:
        traces = [item for item in samples["channels"] if item["channel_id"] == binding["channel_id"]]
        if len(traces) != 1:
            rows.append({"channel_id": binding["channel_id"], "passed": False, "reason": "missing"})
            continue
        trace = traces[0]
        values = [value for instant, value in zip(trace["domain"], trace["values"]) if window[0] <= instant <= window[1]]
        if not values or not all(math.isfinite(value) for value in values):
            rows.append({"channel_id": binding["channel_id"], "passed": False, "reason": "invalid_window"})
            continue
        role = binding["role"]
        mean = math.fsum(values) / len(values)
        rms = math.sqrt(math.fsum(value * value for value in values) / len(values))
        passed = True
        if role in ("fault_active", "blocking_state"):
            passed = all(value == binding["polarity"]["inactive"] for value in values)
        elif role == "recovery_enable":
            passed = all(value == binding["polarity"]["active"] for value in values)
        elif role in ("v_dc", "v_cap", "p_active"):
            nominal = binding["nominal"]
            ripple = math.sqrt(math.fsum((value - mean) ** 2 for value in values) / len(values))
            nominal_ok = abs(mean - nominal) <= abs(nominal) * checks["nominal_target_relative_tolerance"] if binding.get("nominal_role") != "power_balance_input" else mean >= nominal
            passed = nominal_ok and ripple <= abs(mean) * checks["steady_relative_rms_tolerance"]
            if role == "p_active":
                power[binding["model_scope"]] = mean
        elif role == "i_arm":
            bins = [[] for _ in range(cycle_count)]
            for instant, value in zip(trace["domain"], trace["values"]):
                if window[0] <= instant < window[1]:
                    index = math.floor((instant - window[0]) * frequency + 1e-8)
                    if 0 <= index < cycle_count:
                        bins[index].append(value)
            cycles = [math.sqrt(sum(value * value for value in values) / len(values)) for values in bins if len(values) >= 2]
            stable = len(cycles) == cycle_count and rms > 0 and max(abs(value - rms) / rms for value in cycles) <= checks["arm_rms_stability_relative_tolerance"]
            passed = checks["arm_rms_floor_ka"] <= rms and max(abs(value) for value in values) <= checks["arm_peak_limit_ka"] and stable
        elif role == "i_dc_fault":
            passed = max(abs(value) for value in values) < 0.001
        rows.append({"channel_id": binding["channel_id"], "role": role, "passed": bool(passed), "mean": mean, "rms": rms, "min": min(values), "max": max(values), "source": trace["output_part"], "window_s": window})
    if set(power) == {"T1", "T2"}:
        loss = power["T1"] + power["T2"]
        rows.append({"channel_id": "power_balance", "passed": power["T1"] > 0 > power["T2"] and 0 <= loss <= -power["T2"] * checks["maximum_power_loss_fraction"], "input_mw": power["T1"], "output_mw": -power["T2"], "loss_mw": loss})
    return {"verdict": "PASS" if rows and all(item["passed"] for item in rows) else "FAIL", "checks": rows}


async def _run_case(service, root, source, library, master, name, fault):
    case_root = root / name
    case_root.mkdir()
    record = {"case": name, "status": "FAIL", "history": [], "fault": fault}
    report_path = case_root / "report.json"
    def stage(value):
        record["history"].append(value)
        _write(report_path, record)
        print(f"MMC_FAULT_STAGE={name}:{value}", flush=True)
    try:
        stage("materializing")
        native = case_root / "native.pscx"
        binding = materialize_template_native_scenario(source, native, dc_fault_time_s=2.5 if fault else 10.0, fault_duration_s=0.2)
        repaired = case_root / "operating_point.pscx"
        record["operating_point_repair"] = materialize_voltage_control_headroom(native, repaired, current_limit_pu=1.1)
        filtered = case_root / "dc_feedback.pscx"
        record["feedback_filter"] = materialize_dc_feedback_filter(repaired, filtered, master=master)
        carrier = case_root / "carrier.pscx"
        record["carrier_diagnostic"] = materialize_terminal_two_carrier(filtered, carrier)
        project = case_root / f"MMC_{name}.pscx"
        contract = instrument_fault_channels(carrier, project, library=library, master=master)
        contract["required_checks"] = _checks()
        _write(case_root / "channels.json", contract)
        record.update({"native_binding": binding, "channel_contract_path": str(case_root / "channels.json"), "channel_contract_sha256": _hash(case_root / "channels.json"), "project": str(project), "project_instrumented_sha256": _hash(project)})
        stage("loading")
        await service.load_projects([str(library), str(project)])
        settings = {"time_duration": "5.0", "time_step": "25", "sample_step": "250", "PlotType": "1", "output_filename": project.stem + ".out", "StartType": "0", "startup_filename": ""}
        await service.set_project_settings(project.stem, settings)
        observed = await service.get_project_settings(project.stem)
        record["settings"] = observed
        if any(str(observed.get(key)) != value for key, value in settings.items()):
            raise RuntimeError("Settings readback changed")
        await service.save_project(project.stem, confirm=True)
        contract = finalize_fault_instrumentation(project, contract)
        _write(case_root / "channels.json", contract)
        record["channel_contract_sha256"] = _hash(case_root / "channels.json")
        record["readback"] = contract["readback"]
        stage("building")
        await service.build_project(project.stem)
        record["compiled_controls"] = []
        for compiled in sorted(project.parent.glob(project.stem + ".*/MFE_Control_*.f")):
            matched = bool(re.search(r"=\s*0\.99999\s*\*\s*Imax", compiled.read_text(encoding="utf-8"), re.IGNORECASE))
            record["compiled_controls"].append({"path": str(compiled), "sha256": _hash(compiled), "freeze_tracks_imax": matched})
        if len(record["compiled_controls"]) != 2 or not all(item["freeze_tracks_imax"] for item in record["compiled_controls"]):
            raise RuntimeError("Generated antiwindup does not track actual Imax")
        stage("running")
        started = time.time()
        record["started_after"] = started
        await service.run_project(project.stem)
        deadline = time.monotonic() + 900
        while True:
            state = await service.get_run_status(project.stem)
            status = str(state.get("status", state.get("state", ""))).casefold() if isinstance(state, dict) else str(state).casefold()
            if status in ("idle", "complete", "completed", "finished", "done", "success"):
                break
            if status in ("error", "failed", "stopped", "aborted") or time.monotonic() > deadline:
                raise RuntimeError(f"Simulation did not complete: {state}")
            await asyncio.sleep(0.25)
        record["run_status"] = state
        stage("reading")
        outputs = await service.discover_output_files(str(project), started_after=started, max_files=1000)
        record["discovered_outputs"] = outputs
        primary = next(path for path in outputs if Path(path).name.casefold() == (project.stem + "_01.out").casefold())
        frozen_dataset = snapshot_output_dataset(primary, started_after=started)
        _write(case_root / "output-index.json", frozen_dataset)
        record["output_index_path"] = str(case_root / "output-index.json")
        record["output_index_sha256"] = _hash(case_root / "output-index.json")
        _write(report_path, record)
        samples = await read_fault_output_dataset(service.read_output_file, primary, contract, started_after=started)
        if samples["identity"] != frozen_dataset:
            raise RuntimeError("Output identities changed after the pre-read freeze")
        _write(case_root / "samples.json", samples)
        record["samples_path"] = str(case_root / "samples.json")
        record["samples_sha256"] = _hash(case_root / "samples.json")
        record["output_index_path"] = str(case_root / "output-index.json")
        stage("evaluating")
        acceptance = evaluate_template_native_dc_fault(samples, fault_current_limit_ka=20.0, channel_contract=contract, checks_contract=_checks()) if fault else _steady(samples, contract)
        record["acceptance"] = acceptance
        record["diagnostic_channels"] = []
        for channel in samples["channels"]:
            if any(item["channel_id"] == channel["channel_id"] for item in contract.get("diagnostic_channels", [])):
                values = [value for instant, value in zip(channel["domain"], channel["values"]) if 4.6 <= instant <= 5.0]
                record["diagnostic_channels"].append({"channel_id": channel["channel_id"], "min": min(values), "max": max(values), "mean": sum(values) / len(values), "source": channel["output_part"]})
        record["status"] = acceptance["verdict"]
        stage("finished")
    except BaseException as error:  # noqa: BLE001 - preserve every licensed attempt before cleanup
        record["error"] = error.to_dict() if isinstance(error, BackendError) else {"type": type(error).__name__, "message": str(error)}
        record["traceback"] = traceback.format_exc()
        stage("failed")
    _write(report_path, record)
    return record


@pytest.mark.skipif(os.getenv("PSCAD_MCP_MMC_ACCEPTANCE") != "1", reason="Set PSCAD_MCP_MMC_ACCEPTANCE=1 for licensed full-bridge fault evidence.")
def test_real_full_bridge_fault_evidence():
    from pscad_mcp.core.backend.legacy import LegacyBackend
    from pscad_mcp.core.executor import robust_executor
    from pscad_mcp.core.path_policy import PathPolicy
    from pscad_mcp.core.service import PscadService
    workspace = Path(os.environ["PSCAD_MCP_WORKSPACE"])
    assert workspace.is_absolute()
    workspace.mkdir(parents=True, exist_ok=True)
    root = workspace / ("fault-evidence-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    root.mkdir()
    project, original_library = discover_official_mmc_template()
    master = Path("C:/Program Files (x86)/PSCAD46/master.pslx")
    originals = {"project": project, "library": original_library, "master": master}
    source_hashes = {key: {"path": str(value), "sha256": _hash(value)} for key, value in originals.items()}
    report = {"status": "FAIL", "root": str(root), "source_hashes": source_hashes, "runtime": {}, "cases": [], "owned_process_cleaned": False, "checks_contract": _checks()}
    report["commit"] = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parents[1], capture_output=True, text=True, check=True).stdout.strip()
    report["code_hashes"] = {str(path.relative_to(Path(__file__).parents[1])): _hash(path) for path in (Path(__file__), *Path(__file__).parents[1].joinpath("pscad_mcp/hvdc/builders/mmc").glob("*.py"))}
    _write(root / "acceptance-report.json", report)
    print(f"MMC_FAULT_REPORT={root / 'acceptance-report.json'}", flush=True)
    backend = LegacyBackend(robust_executor, version="4.6.2", x64=True, process_probe=list_pscad_processes, legacy_existing_policy=acceptance_launch_policy())
    service = PscadService(lambda: backend, executor=robust_executor, path_policy=PathPolicy(workspace_root=str(root)))
    selected_cases = (("steady", False),) if os.getenv("PSCAD_MCP_MMC_STEADY_ONLY") == "1" else (("steady", False), ("fault", True))
    report["scope"] = "steady_only_diagnostic" if len(selected_cases) == 1 else "steady_and_dc_fault_recovery"
    async def execute():
        try:
            artifacts = generate_public_line_constants(project, root / "line-constants")
            source = rebind_template_line_constants(project, artifacts, root / "source.pscx")
            library = root / original_library.name
            support_before = _compiler_support(original_library)
            if not support_before["link_libraries"]["present"]:
                raise RuntimeError("Declared compiler support is missing")
            report["compiler_support_before"] = support_before
            _write(root / "acceptance-report.json", report)
            shutil.copy2(original_library, library)
            report["compiler_support_copies"] = []
            for item in support_before["files"]:
                origin = Path(item["path"])
                if _hash(origin) != item["sha256"]:
                    raise RuntimeError("Compiler support changed before copy")
                copied = root / item["relative_path"]
                copied.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origin, copied)
                if _hash(copied) != item["sha256"] or _hash(origin) != item["sha256"]:
                    raise RuntimeError("Compiler support copy or source drifted")
                report["compiler_support_copies"].append({**item, "copied_path": str(copied), "copied_sha256": _hash(copied)})
            report["line_constants"] = [item.to_dict() for item in artifacts]
            async def run_cases():
                _write(root / "acceptance-report.json", report)
                for name, fault in selected_cases:
                    report["cases"].append(await _run_case(service, root, source, library, master, name, fault))
                    _write(root / "acceptance-report.json", report)
            await _with_owned_connection(service, backend, report, run_cases)
        except BaseException as error:  # noqa: BLE001 - preserve every licensed attempt before cleanup
            report["error"] = error.to_dict() if isinstance(error, BackendError) else {"type": type(error).__name__, "message": str(error)}
            report["traceback"] = traceback.format_exc()
        finally:
            report["compiler_support_after"] = _compiler_support(original_library)
            report["compiler_support_immutable"] = report.get("compiler_support_before", {}).get("files") == report["compiler_support_after"]["files"]
            report["source_hashes_after"] = {key: {"path": str(value), "sha256": _hash(value)} for key, value in originals.items()}
            report["status"] = "PASS" if len(report["cases"]) == len(selected_cases) and all(item["status"] == "PASS" for item in report["cases"]) and report["owned_process_cleaned"] and report["compiler_support_immutable"] and source_hashes == report["source_hashes_after"] else "FAIL"
            _write(root / "acceptance-report.json", report)
    asyncio.run(execute())
    assert report["status"] == "PASS", str(root / "acceptance-report.json")
