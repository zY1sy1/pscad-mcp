"""Licensed isolated native average-arm acceptance, not complete-MMC acceptance."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import shutil
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from itertools import pairwise
from pathlib import Path
from statistics import fmean
from typing import Any

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from pscad_mcp.acceptance.process_scope import concurrent_acceptance_enabled
from pscad_mcp.acceptance.project_finalization import (
    GENERATED_MODULE_POLICY,
    compare_project_finalization,
    snapshot_project_semantics,
)
from pscad_mcp.core.process_inventory import list_pscad_processes
from pscad_mcp.core.pscad_adapter import (
    _legacy_first_numeric_row,
    _legacy_next_nonblank,
    _legacy_numeric_row,
)
from pscad_mcp.hvdc.builders.mmc.avm_companion import (
    LIBRARY_SCOPE,
    OPERATING_WINDOWS,
    OUTPUT_UNITS,
    AverageArmParameters,
    materialize_average_arm_fixture,
)
from scripts.run_mmc_native_probe_acceptance import (
    _category,
    _error,
    _service,
    _sha256,
    _stamp,
    _write_report,
    cleanup_owned_session,
    discover_run_outputs,
    read_infx,
    require_runtime,
)
from scripts.run_mmc_native_probe_acceptance import (
    _code_snapshot as _runtime_snapshot,
)

CHANNEL_UNITS = {**OUTPUT_UNITS, "M": "1", "BLOCK": "1", "CURRENT_COMMAND": "kA"}
SCOPE = "native_half_bridge_average_arm_physical_acceptance"


def _optins() -> None:
    for name in ("PSCAD_MCP_ACCEPTANCE", "PSCAD_MCP_AVERAGE_ARM_ACCEPTANCE"):
        if os.environ.get(name) != "1":
            raise PermissionError(f"{name}=1 is required before an attempt")


def _code_snapshot() -> dict:
    snapshot = _runtime_snapshot()
    for path in (
        Path(__file__).resolve(),
        REPOSITORY / "tests/test_mmc_average_arm_acceptance.py",
        REPOSITORY / "tests/test_mmc_avm_companion.py",
        REPOSITORY / "pscad_mcp/assets/templates/empty_library.pslx",
        REPOSITORY / "pscad_mcp/assets/templates/empty_case.pscx",
    ):
        snapshot["source_code_hashes"][str(path)] = _sha256(path)
    return snapshot


def _probe_owners(project: Path) -> dict[str, str]:
    owners = {}
    for component in ET.parse(project).findall(
        "./definitions/Definition[@name='Main']/schematic/User[@defn='master:pgb']"
    ):
        values = {
            p.get("name"): p.get("value")
            for p in component.findall("./paramlist/param")
        }
        name = values.get("Name")
        if (
            name in owners
            or name not in CHANNEL_UNITS
            or values.get("Units") != CHANNEL_UNITS[name]
        ):
            raise ValueError("Saved native channel ownership or units changed")
        owners[name] = component.attrib["id"]
    if set(owners) != set(CHANNEL_UNITS):
        raise ValueError("Saved fixture has missing physical output probes")
    return owners


def snapshot_model_inputs(paths) -> dict:
    return {
        str(path): snapshot_project_semantics(path, policy=GENERATED_MODULE_POLICY)
        for path in paths
    }


def verify_model_normalization(authored: dict) -> dict:
    return {
        path: compare_project_finalization(
            before, snapshot_project_semantics(path, policy=GENERATED_MODULE_POLICY)
        )
        for path, before in authored.items()
    }


def require_finalized_hashes(expected: dict[str, str]) -> dict[str, str]:
    observed = {path: _sha256(Path(path)) for path in expected}
    if not expected or observed != expected:
        raise ValueError("A finalized native input or executable changed")
    return observed


def fresh_project_executable(project: Path, started_after: float) -> dict:
    candidates = list(project.parent.rglob(project.stem + ".exe"))
    if len(candidates) != 1:
        raise ValueError("A unique fresh native project executable is required")
    path = candidates[0]
    if (
        path.is_symlink()
        or not path.is_file()
        or not path.resolve().is_relative_to(project.parent.resolve())
        or path.stat().st_size == 0
        or path.stat().st_mtime < started_after
    ):
        raise ValueError("A fresh nonempty owned native executable is required")
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "modified_at": path.stat().st_mtime,
        "build_started_after": started_after,
    }


def read_arm_trace(files: dict, owners: dict[str, str]) -> dict:
    """Read every numeric column and bind it to a saved native PGB owner."""
    infx = read_infx(Path(files["infx"]))
    pattern = re.compile(
        r'^PGB\((\d+)\).*?Desc="([^"]+)"\s+Group="([^"]*)".*?\bUnits="([^"]*)"'
    )
    records = {}
    for line in Path(files["inf"]).read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if not match:
            if line.lstrip().startswith("PGB("):
                raise ValueError("Unparseable INF channel")
            continue
        call_id, name, units = int(match[1]), match[2], match[4]
        source = infx.get(call_id, {})
        if (
            call_id in records
            or name not in CHANNEL_UNITS
            or units != CHANNEL_UNITS[name]
            or source.get("unit") != units
            or source.get("owner") != owners.get(name)
            or source.get("dimension") != 1
            or source.get("name", "").rsplit(":", 1)[-1] != name
        ):
            raise ValueError(
                "INF/INFX channel identity, owner, dimension or units differ"
            )
        records[call_id] = {
            "name": name,
            "unit": units,
            "infx": source,
            "source_part": str(files["parts"][(call_id - 1) // 10]),
            "source_column": (call_id - 1) % 10 + 1,
        }
    if (
        set(records) != set(range(1, len(CHANNEL_UNITS) + 1))
        or set(records) != set(infx)
        or {item["name"] for item in records.values()} != set(CHANNEL_UNITS)
        or len(files["parts"]) != (len(records) + 9) // 10
    ):
        raise ValueError("INF, INFX and OUT coverage must match every physical probe")
    trace = {name: [] for name in ("time", *CHANNEL_UNITS)}
    for part_index, part in enumerate(files["parts"]):
        width = min(10, len(records) - part_index * 10)
        row_index = 0
        with Path(part).open(encoding="utf-8") as stream:
            line = _legacy_first_numeric_row(stream)
            while line:
                values = _legacy_numeric_row(line)
                if values is None or len(values) != width + 1 or row_index >= 100_000:
                    raise ValueError(
                        "Invalid, missing or oversized native numeric output"
                    )
                if part_index == 0:
                    trace["time"].append(values[0])
                elif (
                    row_index >= len(trace["time"])
                    or values[0] != trace["time"][row_index]
                ):
                    raise ValueError("Native output parts have different time domains")
                for column in range(width):
                    trace[records[part_index * 10 + column + 1]["name"]].append(
                        values[column + 1]
                    )
                row_index += 1
                line = _legacy_next_nonblank(stream)
        if not row_index or row_index != len(trace["time"]):
            raise ValueError("Native output parts have different lengths")
    return {"samples": trace, "channel_sources": records}


def analyze_arm_trace(trace: dict, parameters: AverageArmParameters) -> dict:
    """Apply fixed physical tolerances to measured native quantities."""
    result: dict[str, Any] = {
        "status": "FAIL",
        "measurement_complete": False,
        "checks": {},
        "windows": {},
    }
    checks = result["checks"]
    required = {"time", *CHANNEL_UNITS}
    if not required <= set(trace):
        result["missing_channels"] = sorted(required - set(trace))
        return result
    domain = trace["time"]
    if len(domain) < 9500 or any(
        len(trace[name]) != len(domain)
        or any(
            not isinstance(v, (int, float)) or not math.isfinite(v) for v in trace[name]
        )
        for name in required
    ):
        result["error"] = "Incomplete or nonfinite native sample arrays"
        return result
    checks["time_coverage"] = (
        domain[0] <= 2e-5
        and domain[-1] >= 0.18998
        and all(0 < b - a <= 2.2e-5 for a, b in pairwise(domain))
    )
    if not checks["time_coverage"]:
        return result
    result["measurement_complete"] = True
    checks["bounded_arm_current"] = max(abs(value) for value in trace["I_ARM"]) <= 0.25
    checks["capacitor_nonnegative"] = min(trace["V_CAP_TOTAL"]) >= -1e-3
    checks["physical_precharge"] = (
        max(v for t, v in zip(domain, trace["V_CAP_TOTAL"]) if 0.025 <= t <= 0.055)
        > 1.0
    )
    energy_scale = max(1e-4, max(trace["ENERGY"]))
    checks["half_voltage_convention"] = max(
        abs(2 * equivalent - full)
        for equivalent, full in zip(trace["V_CAP_EQ"], trace["V_CAP_TOTAL"])
    ) <= 1e-3 * max(1.0, max(trace["V_CAP_TOTAL"]))
    checks["physical_energy_state"] = (
        max(
            abs(w - parameters.C_eq_F * voltage**2 / 8)
            for w, voltage in zip(trace["ENERGY"], trace["V_CAP_TOTAL"])
        )
        <= 1e-3 * energy_scale
    )
    inductance = []
    for index in range(1, len(domain) - 1):
        if 0.003 <= domain[index] <= 0.008:
            derivative = (trace["I_ARM"][index + 1] - trace["I_ARM"][index - 1]) / (
                domain[index + 1] - domain[index - 1]
            )
            if abs(derivative) < 10:
                continue
            inductance.append(
                (
                    trace["V_ARM"][index]
                    - trace["V_INSERTED"][index]
                    - parameters.R_arm_ohm * trace["I_ARM"][index]
                )
                / derivative
            )
    result["measured_arm_inductance_h"] = fmean(inductance) if inductance else None
    checks["physical_arm_inductance"] = (
        len(inductance) >= 200
        and abs(fmean(inductance) - parameters.L_arm_H) <= 0.05 * parameters.L_arm_H
    )
    for window, (start, stop) in OPERATING_WINDOWS.items():
        indexes = [
            index for index, instant in enumerate(domain) if start <= instant <= stop
        ]
        if len(indexes) < 400:
            checks[window + ":coverage"] = False
            continue
        positive = window in {"charge", "blocked_charge"}
        blocked = window.startswith("blocked_")
        ratio = (1.0 if positive else 0.0) if blocked else 0.5
        mean = lambda name, selected=indexes: fmean(
            trace[name][index] for index in selected
        )
        expected_current = 0.2 if positive else -0.2
        first, last = indexes[0], indexes[-1]
        change = trace["ENERGY"][last] - trace["ENERGY"][first]
        integrated = sum(
            0.5
            * (
                trace["V_CAP_TOTAL"][a] * trace["I_CAP"][a]
                + trace["V_CAP_TOTAL"][b] * trace["I_CAP"][b]
            )
            * (domain[b] - domain[a])
            for a, b in pairwise(indexes)
        )
        metrics = {
            "samples": len(indexes),
            "energy_change_mj": change,
            "integrated_capacitor_power_mj": integrated,
            "mean_arm_current_ka": mean("I_ARM"),
            "mean_capacitor_current_ka": mean("I_CAP"),
            "mean_normal_current_ka": mean("I_NORMAL"),
            "mean_clamp_current_ka": mean("I_CLAMP"),
            "mean_bypass_current_ka": mean("I_BYPASS"),
        }
        result["windows"][window] = metrics

        def check(name, value, selected_window=window):
            checks[selected_window + ":" + name] = bool(value)

        energized = (
            min(trace["V_CAP_TOTAL"][i] for i in indexes) > parameters.V_loss_floor_kV
        )
        check("energized_capacitor", energized)
        if not energized:
            continue
        check(
            "command_and_arm_current",
            abs(mean("I_ARM") - expected_current) <= 0.002
            and max(
                abs(trace["I_ARM"][i] - trace["CURRENT_COMMAND"][i]) for i in indexes
            )
            <= 0.002,
        )
        check(
            "modulation_and_block",
            max(abs(trace["M"][i] - 0.5) for i in indexes) <= 1e-6
            and max(abs(trace["BLOCK"][i] - float(blocked)) for i in indexes) <= 1e-6,
        )
        check(
            "capacitor_charge_direction",
            abs(
                mean("I_CAP")
                - ratio * expected_current
                + mean("P_NONOHMIC") / mean("V_CAP_TOTAL")
            )
            <= 0.002,
        )
        check(
            "energy_integral", abs(change - integrated) <= max(1e-5, 0.01 * abs(change))
        )
        check(
            "energy_direction",
            change > 1e-5
            if positive
            else change < -1e-5
            if not blocked
            else abs(change) <= max(1e-5, 0.005 * trace["ENERGY"][first]),
        )
        check(
            "inserted_voltage",
            max(
                abs(trace["V_INSERTED"][i] - ratio * trace["V_CAP_TOTAL"][i])
                for i in indexes
            )
            <= 0.01,
        )
        check(
            "arm_resistance",
            max(
                abs(
                    trace["V_ARM"][i]
                    - trace["V_INSERTED"][i]
                    - parameters.R_arm_ohm * trace["I_ARM"][i]
                )
                for i in indexes
            )
            <= 0.001,
        )
        check(
            "current_continuity",
            max(
                abs(
                    trace["I_ARM"][i]
                    - trace["I_NORMAL"][i]
                    - trace["I_CLAMP"][i]
                    + trace["I_BYPASS"][i]
                )
                for i in indexes
            )
            <= 0.002,
        )
        check(
            "signed_storage_coupling",
            max(
                abs(
                    trace["I_CAP"][i]
                    - 0.5 * trace["I_NORMAL"][i]
                    - trace["I_CLAMP"][i]
                    + trace["P_NONOHMIC"][i] / trace["V_CAP_TOTAL"][i]
                )
                for i in indexes
            )
            <= 0.002,
        )
        if blocked:
            check(
                "normal_branch_open",
                max(abs(trace["I_NORMAL"][i]) for i in indexes) <= 1e-4,
            )
            check(
                "diode_conduction",
                abs(mean("I_CLAMP") - (0.2 if positive else 0)) <= 0.002
                and abs(mean("I_BYPASS") - (0 if positive else 0.2)) <= 0.002,
            )
        else:
            check(
                "normal_branch_conduction",
                abs(mean("I_NORMAL") - expected_current) <= 0.002,
            )
        residuals = []
        for i in indexes:
            arm_current, normal, clamp, bypass = (
                trace[name][i] for name in ("I_ARM", "I_NORMAL", "I_CLAMP", "I_BYPASS")
            )
            semiconductor = (
                (parameters.R_off_ohm if blocked else parameters.R_on_ohm) * normal**2
                + parameters.R_on_ohm * (clamp**2 + bypass**2)
                + parameters.V_diode_kV * (max(clamp, 0) + max(bypass, 0))
            )
            residuals.append(
                trace["V_ARM"][i] * arm_current
                - parameters.R_arm_ohm * arm_current**2
                - semiconductor
                - trace["V_CAP_TOTAL"][i] * trace["I_CAP"][i]
                - trace["P_NONOHMIC"][i]
            )
        metrics["max_signed_power_residual_mw"] = max(abs(value) for value in residuals)
        check(
            "signed_power_balance",
            metrics["max_signed_power_residual_mw"]
            <= max(
                2e-4,
                0.005
                * max(abs(trace["V_ARM"][i] * trace["I_ARM"][i]) for i in indexes),
            ),
        )
    result["status"] = "PASS" if checks and all(checks.values()) else "FAIL"
    return result


def _require_no_errors(messages: Any) -> None:
    if not isinstance(messages, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("severity"), str)
        or not isinstance(item.get("text"), str)
        for item in messages
    ):
        raise ValueError("Structured native build/run messages are required")
    if any(
        any(word in item["severity"].casefold() for word in ("error", "fatal"))
        for item in messages
    ):
        raise ValueError("Native build/run reported an error")


async def run_attempt(args, run_dir: Path, *, service_factory=_service) -> dict:
    _optins()
    report_path = run_dir / "report.json"
    report: dict[str, Any] = {
        "schema_version": 1,
        "scope": SCOPE,
        "status": "FAIL",
        "component_accepted": False,
        "model_accepted": False,
        "started_at": _stamp(),
        "run_directory": str(run_dir),
        "concurrent": concurrent_acceptance_enabled(),
        "remaining_scope": [
            "Twelve-arm converter controls, station integration, full model acceptance and an independent golden baseline remain unverified."
        ],
        "stages": [],
    }
    service, runtime, project_name = None, {}, None
    attach_attempted = run_pending = False
    stage, source_hashes, code_before = "inputs", {}, {}
    finalized_inputs: dict[str, str] = {}

    def begin(name):
        nonlocal stage
        stage = name
        report["stages"].append({"name": name, "started_at": _stamp()})
        _write_report(report_path, report)
        print("MMC_AVERAGE_ARM_STAGE=" + name, flush=True)

    async def bounded(awaitable, timeout=None):
        return await asyncio.wait_for(awaitable, timeout or args.operation_timeout)

    try:
        begin("inputs")
        source_hashes = {
            str(path): _sha256(path)
            for path in (
                args.master,
                args.compiler_configuration,
                args.compiler_executable,
            )
        }
        report["source_hashes_before"] = source_hashes
        report["code_before"] = code_before = _code_snapshot()
        if code_before["working_tree_status"]:
            raise ValueError(
                "Licensed average-arm acceptance requires a frozen clean worktree"
            )
        report["processes_before"] = list_pscad_processes()
        begin("materialize")
        receipt = materialize_average_arm_fixture(
            run_dir / "authored", master_path=args.master
        )
        report["fixture"] = receipt
        model_dir = run_dir / "model"
        model_dir.mkdir()
        library = model_dir / Path(receipt["library_path"]).name
        project = model_dir / Path(receipt["project_path"]).name
        shutil.copy2(receipt["library_path"], library)
        shutil.copy2(receipt["project_path"], project)
        project_name = receipt["project_name"]
        report["project_path"], report["library_path"] = str(project), str(library)
        authored_model = snapshot_model_inputs((project, library))
        report["authored_model_snapshots"] = authored_model
        begin("attach")
        service = service_factory(run_dir)
        attach_attempted = True
        report["attach_result"] = await bounded(service.attach_local())
        runtime = await bounded(service.status())
        report["runtime"] = runtime
        require_runtime(runtime)
        begin("load_and_normalize")
        await bounded(service.load_projects([str(library), str(project)]))
        await bounded(service.save_project(LIBRARY_SCOPE, confirm=True))
        requested_settings = {
            "time_duration": "0.19",
            "time_step": "2",
            "sample_step": "20",
            "StartType": "0",
            "PlotType": "1",
            "output_filename": project.stem + ".out",
        }
        await bounded(service.set_project_settings(project_name, requested_settings))
        settings = await bounded(service.get_project_settings(project_name))
        report["settings"] = {"requested": requested_settings, "readback": settings}
        if any(
            (
                settings.get(key) != value
                if key == "output_filename"
                else float(settings[key]) != float(value)
            )
            for key, value in requested_settings.items()
        ):
            raise ValueError("Native simulation settings did not read back exactly")
        await bounded(service.save_project(project_name, confirm=True))
        begin("initial_compile_and_finalization")
        normalization_started = time.time()
        report["normalization_compile_result"] = await bounded(
            service.build_project(project_name), args.build_timeout
        )
        report["normalization_compile_messages"] = await bounded(
            service.get_project_output(project_name, structured=True)
        )
        _require_no_errors(report["normalization_compile_messages"])
        await bounded(service.save_project(LIBRARY_SCOPE, confirm=True))
        await bounded(service.save_project(project_name, confirm=True))
        report["model_finalization"] = verify_model_normalization(authored_model)
        report["probe_owners"] = _probe_owners(project)
        report["finalized_hashes_before_run"] = finalized_inputs = {
            str(path): _sha256(path) for path in (project, library)
        }
        initial_executable = fresh_project_executable(project, normalization_started)
        evidence_dir = run_dir / "canonicalization-evidence"
        evidence_dir.mkdir()
        evidence_binary = evidence_dir / Path(initial_executable["path"]).name
        shutil.copy2(initial_executable["path"], evidence_binary)
        if _sha256(evidence_binary) != initial_executable["sha256"]:
            raise ValueError("Canonicalization executable preservation failed")
        report["canonicalization_executable"] = {
            **initial_executable,
            "preserved_path": str(evidence_binary),
        }
        begin("clean_owned_build")
        native_project = await bounded(service.backend._project(project_name))
        await bounded(
            service.backend.executor.run_safe(
                native_project.clean, timeout=args.operation_timeout
            )
        )
        report["executables_before_fresh_build"] = [
            str(path) for path in project.parent.rglob(project.stem + ".exe")
        ]
        if report["executables_before_fresh_build"]:
            raise ValueError("Native project clean retained a project executable")
        require_finalized_hashes(finalized_inputs)
        begin("compile")
        compile_started = time.time()
        report["compile_result"] = await bounded(
            service.build_project(project_name), args.build_timeout
        )
        report["compile_messages"] = await bounded(
            service.get_project_output(project_name, structured=True)
        )
        _require_no_errors(report["compile_messages"])
        report["fresh_executable"] = fresh_project_executable(project, compile_started)
        require_finalized_hashes(finalized_inputs)
        finalized_inputs[report["fresh_executable"]["path"]] = report[
            "fresh_executable"
        ]["sha256"]
        report["finalized_hashes_before_run"] = dict(finalized_inputs)
        begin("run")
        started = time.time()
        run_pending = True
        report["run_result"] = await bounded(service.run_project(project_name))
        deadline = time.monotonic() + args.run_timeout
        report["run_states"] = []
        while True:
            state = await bounded(service.get_run_status(project_name))
            report["run_states"].append(state)
            status = str(state.get("status", "")).casefold()
            if status in {"completed", "complete", "idle"}:
                run_pending = False
                break
            if status in {"failed", "stopped", "interrupted"}:
                raise RuntimeError(f"Native arm simulation ended with {status}")
            if time.monotonic() >= deadline:
                raise TimeoutError("Native arm simulation exceeded its deadline")
            await asyncio.sleep(0.5)
        report["run_messages"] = await bounded(
            service.get_project_output(project_name, structured=True)
        )
        _require_no_errors(report["run_messages"])
        begin("read_and_analyze")
        files = discover_run_outputs(
            project, started, metadata_started_after=compile_started
        )
        report["outputs"] = files
        finalized_outputs = [*files["parts"], files["inf"], files["infx"]]
        hashes = {str(path): _sha256(path) for path in finalized_outputs}
        observed = read_arm_trace(files, report["probe_owners"])
        report["channel_sources"] = observed["channel_sources"]
        trace_path = run_dir / "trace.json"
        _write_report(trace_path, observed["samples"])
        report["trace"] = {"path": str(trace_path), "sha256": _sha256(trace_path)}
        report["analysis"] = analyze_arm_trace(
            observed["samples"], AverageArmParameters(**receipt["parameters"])
        )
        report["output_hashes_before_read"] = hashes
        report["output_hashes_after_read"] = {
            path: _sha256(Path(path)) for path in hashes
        }
        if report["output_hashes_before_read"] != report["output_hashes_after_read"]:
            raise ValueError("Native output evidence changed while being read")
        report["finalized_hashes_after_run"] = require_finalized_hashes(
            finalized_inputs
        )
        report["status"] = report["analysis"]["status"]
        if report["status"] == "FAIL":
            report["failure_category"] = (
                "model_physical"
                if report["analysis"]["measurement_complete"]
                else "implementation_or_measurement"
            )
    except BaseException as error:  # noqa: BLE001 - persist failed attempts and still clean the owned instance
        report.update(
            status="FAIL",
            error=_error(error),
            failed_stage=stage,
            failure_category=_category(stage, error),
        )
        if service is not None and project_name and runtime.get("owns_process"):
            try:
                report["failure_messages"] = await bounded(
                    service.get_project_output(project_name, structured=True)
                )
            except BaseException as message_error:  # noqa: BLE001 - diagnostics must not prevent cleanup
                report["failure_messages_error"] = _error(message_error)
    finally:
        try:
            if service is not None and attach_attempted:
                if not runtime:
                    runtime = await bounded(service.status())
                    report["runtime_after_error"] = runtime
                report["cleanup"] = await cleanup_owned_session(
                    service,
                    runtime,
                    project_name=project_name,
                    run_pending=run_pending,
                    timeout=args.cleanup_timeout,
                )
            else:
                report["cleanup"] = {
                    "owned_process_cleaned": True,
                    "runtime_started": False,
                    "remaining_owned_processes": [],
                }
            if not report["cleanup"].get("owned_process_cleaned") or report[
                "cleanup"
            ].get("errors"):
                report["status"] = "FAIL"
                report.setdefault("failure_category", "process_cleanup")
        except BaseException as error:  # noqa: BLE001 - persist cleanup failures
            report.update(status="FAIL", cleanup_error=_error(error))
        try:
            if finalized_inputs:
                report["finalized_hashes_after_cleanup"] = require_finalized_hashes(
                    finalized_inputs
                )
            report["source_hashes_after"] = {
                path: _sha256(Path(path)) for path in source_hashes
            }
            report["source_inputs_immutable"] = (
                bool(source_hashes) and report["source_hashes_after"] == source_hashes
            )
            report["code_after"] = _code_snapshot()
            report["source_code_immutable"] = (
                bool(code_before)
                and report["code_after"]["source_code_hashes"]
                == code_before["source_code_hashes"]
                and report["code_after"]["commit"] == code_before["commit"]
            )
            if (
                not report["source_inputs_immutable"]
                or not report["source_code_immutable"]
            ):
                report["status"] = "FAIL"
                report.setdefault("failure_category", "implementation_defect")
            if "fixture" in report:
                receipt = report["fixture"]
                report["authored_inputs_immutable"] = (
                    _sha256(Path(receipt["project_path"])) == receipt["project_sha256"]
                    and _sha256(Path(receipt["library_path"]))
                    == receipt["library_sha256"]
                )
                if not report["authored_inputs_immutable"]:
                    report["status"] = "FAIL"
            report["artifacts"] = {
                str(path): {"sha256": _sha256(path), "bytes": path.stat().st_size}
                for path in run_dir.rglob("*")
                if path.is_file()
                and path not in {report_path, report_path.with_suffix(".json.tmp")}
            }
        except BaseException as error:  # noqa: BLE001 - retain evidence finalization errors
            report.update(status="FAIL", finalization_error=_error(error))
        report["component_accepted"] = report["status"] == "PASS"
        report["finished_at"] = _stamp()
        _write_report(report_path, report)
    return report


def main(argv=None, *, service_factory=_service) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument(
        "--master",
        type=Path,
        default=Path("C:/Program Files (x86)/PSCAD46/master.pslx"),
    )
    parser.add_argument(
        "--compiler-configuration",
        type=Path,
        default=Path("C:/Program Files (x86)/PSCAD46/fortran_compilers.xml"),
    )
    parser.add_argument(
        "--compiler-executable",
        type=Path,
        default=Path("C:/Program Files (x86)/GFortran/4.6/bin/gfortran.exe"),
    )
    for name, default in (
        ("operation-timeout", 180),
        ("build-timeout", 600),
        ("run-timeout", 180),
        ("cleanup-timeout", 30),
    ):
        parser.add_argument("--" + name, type=float, default=default)
    args = parser.parse_args(argv)
    try:
        _optins()
    except PermissionError as error:
        print(str(error) + "; no runtime or workspace was created.", file=sys.stderr)
        return 2
    if not args.workspace_root.is_absolute() or any(
        not math.isfinite(getattr(args, name)) or getattr(args, name) <= 0
        for name in (
            "operation_timeout",
            "build_timeout",
            "run_timeout",
            "cleanup_timeout",
        )
    ):
        raise SystemExit(
            "Workspace must be absolute and timeout values finite and positive"
        )
    workspace = args.workspace_root.resolve()
    for directory in (
        REPOSITORY.resolve(),
        args.master.resolve().parent,
        args.compiler_executable.resolve().parent,
        args.compiler_configuration.resolve().parent,
    ):
        if workspace.is_relative_to(directory) or directory.is_relative_to(workspace):
            raise SystemExit(
                "Acceptance workspace must be disjoint from source and compiler directories"
            )
    run_dir = workspace / (
        time.strftime("attempt-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    )
    run_dir.mkdir(parents=True)
    report = asyncio.run(run_attempt(args, run_dir, service_factory=service_factory))
    print(
        json.dumps(
            {
                "status": report["status"],
                "component_accepted": report["component_accepted"],
                "model_accepted": False,
                "report": str(run_dir / "report.json"),
            }
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
