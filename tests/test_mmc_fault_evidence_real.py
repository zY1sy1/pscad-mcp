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
    finalize_fault_instrumentation,
    instrument_fault_channels,
    materialize_voltage_control_headroom,
    read_fault_output_dataset,
)
from pscad_mcp.hvdc.builders.mmc.line_constants import (
    generate_public_line_constants,
    rebind_template_line_constants,
)
from pscad_mcp.hvdc.builders.mmc.template_audit import discover_official_mmc_template
from pscad_mcp.hvdc.builders.mmc.template_native import (
    evaluate_template_native_dc_fault,
    materialize_template_native_scenario,
)


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")


def _checks():
    return {
        "schema_version": 1, "time_basis": "EMTDC", "time_units": "s",
        "output_step_s": 250e-6, "max_timing_error_s": 500e-6,
        "frequency_hz": 60.0, "arm_rms_stability_relative_tolerance": 0.05,
        "nominal_target_relative_tolerance": 0.05,
        "arm_peak_limit_ka": 3.0,
        "maximum_power_loss_fraction": 0.1,
        "fault_window_s": [2.5, 2.7], "prefault_window_s": [2.0, 2.4], "recovery_window_s": [4.6, 5.0],
        "negative_voltage_max_kv": -1.0, "fault_current_limit_ka": 20.0,
        "voltage_recovery_relative_tolerance": 0.05, "power_recovery_relative_tolerance": 0.05,
        "arm_rms_recovery_relative_tolerance": 0.1, "capacitor_recovery_relative_tolerance": 0.05,
        "steady_relative_rms_tolerance": 0.05, "minimum_operating_fraction": 0.9, "arm_rms_floor_ka": 0.05,
        "basis": "New pre-run engineering contract: 640 kV, T1 +900 MW/T2 -900 MW, complete 60 Hz cycle windows; legacy 20 kA fault-current bound retained.",
    }


def _steady(samples, contract):
    rows = []
    for binding in contract["channels"]:
        traces = [item for item in samples["channels"] if item["channel_id"] == binding["channel_id"]]
        if len(traces) != 1:
            rows.append({"channel_id": binding["channel_id"], "passed": False, "reason": "missing"})
            continue
        trace = traces[0]
        values = [value for instant, value in zip(trace["domain"], trace["values"]) if 4.5 <= instant <= 5.0]
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
            nominal_ok = abs(mean - nominal) <= abs(nominal) * 0.05 if binding.get("nominal_role") != "power_balance_input" else mean >= nominal
            passed = nominal_ok and ripple <= abs(mean) * 0.05
        elif role == "i_arm":
            passed = 0.05 <= rms and max(abs(value) for value in values) < 3.0
        elif role == "i_dc_fault":
            passed = max(abs(value) for value in values) < 0.001
        rows.append({"channel_id": binding["channel_id"], "role": role, "passed": bool(passed), "mean": mean, "rms": rms, "min": min(values), "max": max(values), "source": trace["output_part"], "window_s": [4.5, 5.0]})
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
        project = case_root / f"MMC_{name}.pscx"
        contract = instrument_fault_channels(repaired, project, library=library, master=master)
        contract["required_checks"] = _checks()
        _write(case_root / "channels.json", contract)
        record.update({"native_binding": binding, "channel_contract_path": str(case_root / "channels.json"), "channel_contract_sha256": _hash(case_root / "channels.json"), "project": str(project), "project_instrumented_sha256": _hash(project)})
        stage("loading")
        await service.load_projects([str(library), str(project)])
        settings = {"time_duration": "5.0", "time_step": "50", "sample_step": "250", "PlotType": "1", "output_filename": project.stem + ".out", "StartType": "0", "startup_filename": ""}
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
        samples = await read_fault_output_dataset(service.read_output_file, primary, contract, started_after=started)
        _write(case_root / "output-index.json", samples["identity"])
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
    service = PscadService(lambda: LegacyBackend(robust_executor, version="4.6.2", x64=True, process_probe=list_pscad_processes, legacy_existing_policy=acceptance_launch_policy()), executor=robust_executor, path_policy=PathPolicy(workspace_root=str(root)))
    async def execute():
        try:
            artifacts = generate_public_line_constants(project, root / "line-constants")
            source = rebind_template_line_constants(project, artifacts, root / "source.pscx")
            library = root / original_library.name
            shutil.copy2(original_library, library)
            for name in ("lib", "Obj_Files_2016_03_25"):
                if (original_library.parent / name).is_dir():
                    shutil.copytree(original_library.parent / name, root / name)
            report["line_constants"] = [item.to_dict() for item in artifacts]
            report["library_support_hashes"] = {str(path.relative_to(original_library.parent)): _hash(path) for path in original_library.parent.joinpath("lib").rglob("*") if path.is_file()}
            await service.attach_local()
            report["runtime"] = await service.status()
            require_acceptance_ownership(report["runtime"])
            _write(root / "acceptance-report.json", report)
            for name, fault in (("steady", False), ("fault", True)):
                report["cases"].append(await _run_case(service, root, source, library, master, name, fault))
                _write(root / "acceptance-report.json", report)
        except BaseException as error:  # noqa: BLE001 - preserve every licensed attempt before cleanup
            report["error"] = error.to_dict() if isinstance(error, BackendError) else {"type": type(error).__name__, "message": str(error)}
            report["traceback"] = traceback.format_exc()
        finally:
            if report["runtime"]:
                try:
                    await service.quit_pscad(confirm=True)
                    for _ in range(40):
                        if not remaining_acceptance_processes(report["runtime"], list_pscad_processes):
                            report["owned_process_cleaned"] = True
                            break
                        await asyncio.sleep(0.25)
                except BaseException as error:  # noqa: BLE001 - cleanup errors belong in durable evidence
                    report["cleanup_error"] = str(error)
            report["source_hashes_after"] = {key: {"path": str(value), "sha256": _hash(value)} for key, value in originals.items()}
            report["status"] = "PASS" if len(report["cases"]) == 2 and all(item["status"] == "PASS" for item in report["cases"]) and report["owned_process_cleaned"] and source_hashes == report["source_hashes_after"] else "FAIL"
            _write(root / "acceptance-report.json", report)
    asyncio.run(execute())
    assert report["status"] == "PASS", str(root / "acceptance-report.json")
