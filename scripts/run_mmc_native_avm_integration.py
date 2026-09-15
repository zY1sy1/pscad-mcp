"""Licensed native two-station AVM assembly acceptance, excluding power control."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import shutil
import sys
import time
import uuid
from itertools import pairwise
from pathlib import Path
from typing import Any

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from pscad_mcp.acceptance.executable_finalization import verify_executable_relink
from pscad_mcp.acceptance.process_scope import concurrent_acceptance_enabled
from pscad_mcp.acceptance.project_finalization import (
    GENERATED_MODULE_POLICY,
    compare_project_finalization,
    snapshot_project_semantics,
)
from pscad_mcp.core.process_inventory import list_pscad_processes
from pscad_mcp.hvdc.builders.mmc.cable_companion import DEFAULT_DONOR, DEFAULT_MASTER
from pscad_mcp.hvdc.builders.mmc.native_bundle import (
    FIXTURE_CHANNELS,
    audit_native_avm_fixture,
    materialize_native_avm_fixture,
)
from scripts.run_mmc_average_arm_acceptance import (
    _probe_owners,
    _require_no_errors,
    fresh_project_executable,
    read_arm_trace,
    require_finalized_hashes,
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
    require_runtime,
)
from scripts.run_mmc_native_probe_acceptance import (
    _code_snapshot as _runtime_snapshot,
)

SCOPE = "native_two_station_twelve_arm_avm_assembly"


def _optins() -> None:
    for name in (
        "PSCAD_MCP_ACCEPTANCE",
        "PSCAD_MCP_NATIVE_AVM_INTEGRATION_ACCEPTANCE",
    ):
        if os.environ.get(name) != "1":
            raise PermissionError(f"{name}=1 is required before an attempt")


def _code_snapshot() -> dict:
    snapshot = _runtime_snapshot()
    for path in (
        Path(__file__).resolve(),
        REPOSITORY / "tests/test_mmc_native_avm_integration.py",
        REPOSITORY / "tests/test_mmc_native_bundle.py",
    ):
        snapshot["source_code_hashes"][str(path)] = _sha256(path)
    return snapshot


def snapshot_models(paths) -> dict:
    return {
        str(path): snapshot_project_semantics(
            path, policy=GENERATED_MODULE_POLICY
        )
        for path in paths
    }


def verify_model_finalization(authored: dict) -> dict:
    return {
        path: compare_project_finalization(
            before,
            snapshot_project_semantics(path, policy=GENERATED_MODULE_POLICY),
        )
        for path, before in authored.items()
    }


def analyze_integration_trace(trace: dict) -> dict:
    result = {
        "status": "FAIL",
        "measurement_complete": False,
        "checks": {},
        "metrics": {},
    }
    required = {"time", *FIXTURE_CHANNELS}
    if set(trace) != required:
        result["missing_channels"] = sorted(required - set(trace))
        result["unexpected_channels"] = sorted(set(trace) - required)
        return result
    time_domain = trace["time"]
    if (
        len(time_domain) < 4000
        or any(len(trace[name]) != len(time_domain) for name in FIXTURE_CHANNELS)
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for values in trace.values()
            for value in values
        )
        or any(right <= left for left, right in pairwise(time_domain))
    ):
        result["error"] = "Native integration trace is incomplete or nonfinite"
        return result
    checks = result["checks"]
    checks["time_coverage"] = (
        time_domain[0] <= 1.1e-4
        and time_domain[-1] >= 0.4998
        and max(right - left for left, right in pairwise(time_domain)) <= 1.1e-4
    )
    windows = (
        (0.02, 0.09, 1.0),
        (0.12, 0.29, 2.0),
        (0.32, 0.49, 3.0),
    )
    for channel in ("P_SEQUENCE", "V_SEQUENCE"):
        for index, (start, end, expected) in enumerate(windows, start=1):
            values = [
                value
                for timestamp, value in zip(time_domain, trace[channel])
                if start <= timestamp <= end
            ]
            checks[f"{channel}:stage_{index}"] = bool(values) and max(
                abs(value - expected) for value in values
            ) <= 1e-9
    for channel in ("P_A_UPPER_W", "V_A_UPPER_W"):
        checks[channel + ":nonnegative"] = min(trace[channel]) >= -1e-6
        checks[channel + ":energized"] = max(trace[channel]) >= 1e-5
    for channel in ("P_A_UPPER_I", "V_A_UPPER_I"):
        checks[channel + ":bounded"] = max(abs(value) for value in trace[channel]) <= 20.0
    for channel in ("P_VDC", "V_VDC"):
        checks[channel + ":finite_bipole"] = max(
            abs(value)
            for timestamp, value in zip(time_domain, trace[channel])
            if 0.08 <= timestamp <= 0.49
        ) >= 1.0
    result["measurement_complete"] = True
    result["metrics"] = {
        "sample_count": len(time_domain),
        "time_start_s": time_domain[0],
        "time_end_s": time_domain[-1],
        "max_abs_arm_current_ka": max(
            max(abs(value) for value in trace[channel])
            for channel in ("P_A_UPPER_I", "V_A_UPPER_I")
        ),
        "max_abs_vdc_kv": {
            channel: max(abs(value) for value in trace[channel])
            for channel in ("P_VDC", "V_VDC")
        },
        "max_arm_energy_mj": {
            channel: max(trace[channel])
            for channel in ("P_A_UPPER_W", "V_A_UPPER_W")
        },
    }
    result["failed_checks"] = [name for name, passed in checks.items() if not passed]
    result["status"] = "PASS" if checks and not result["failed_checks"] else "FAIL"
    return result


async def run_attempt(args, run_dir: Path, *, service_factory=_service) -> dict:
    _optins()
    report_path = run_dir / "report.json"
    report: dict[str, Any] = {
        "schema_version": 1,
        "scope": SCOPE,
        "status": "FAIL",
        "assembly_accepted": False,
        "model_accepted": False,
        "started_at": _stamp(),
        "run_directory": str(run_dir),
        "concurrent": concurrent_acceptance_enabled(),
        "remaining_scope": [
            "Closed-loop P/Q/Vdc control, rated bidirectional power, fault behavior and independent golden acceptance remain unverified."
        ],
        "stages": [],
    }
    service, runtime, project_name = None, {}, None
    attach_attempted = run_pending = False
    source_hashes: dict[str, str] = {}
    finalized_inputs: dict[str, str] = {}
    stage, code_before = "inputs", {}

    def begin(name: str) -> None:
        nonlocal stage
        stage = name
        report["stages"].append({"name": name, "started_at": _stamp()})
        _write_report(report_path, report)
        print("MMC_NATIVE_AVM_STAGE=" + name, flush=True)

    async def bounded(awaitable, timeout=None):
        return await asyncio.wait_for(awaitable, timeout or args.operation_timeout)

    try:
        begin("inputs")
        source_paths = (
            args.master,
            args.source_project,
            args.constants_evidence,
            args.compiler_configuration,
            args.compiler_executable,
        )
        for path in source_paths:
            if path.is_symlink() or not path.is_file():
                raise FileNotFoundError(f"Required immutable input is unavailable: {path}")
        source_hashes = {str(path.resolve()): _sha256(path) for path in source_paths}
        report["source_hashes_before"] = source_hashes
        report["code_before"] = code_before = _code_snapshot()
        if code_before["working_tree_status"]:
            raise ValueError("Licensed native AVM acceptance requires a clean frozen checkout")
        report["processes_before"] = list_pscad_processes()
        begin("materialize")
        receipt = materialize_native_avm_fixture(
            run_dir / "model",
            constants_evidence=args.constants_evidence,
            master_path=args.master,
            source_project=args.source_project,
        )
        report["fixture"] = receipt
        project = Path(receipt["project_path"])
        library = Path(receipt["library"]["library_path"])
        project_name = receipt["project_name"]
        authored = snapshot_models((project, library))
        report["authored_model_snapshots"] = authored
        begin("attach")
        service = service_factory(run_dir)
        attach_attempted = True
        report["attach_result"] = await bounded(service.attach_local())
        runtime = await bounded(service.status())
        report["runtime"] = runtime
        require_runtime(runtime)
        begin("load_and_normalize")
        await bounded(service.load_projects([str(library), str(project)]))
        await bounded(service.save_project(library.stem, confirm=True))
        await bounded(service.save_project(project_name, confirm=True))
        normalization_started = time.time()
        report["normalization_compile_result"] = await bounded(
            service.build_project(project_name), args.build_timeout
        )
        report["normalization_compile_messages"] = await bounded(
            service.get_project_output(project_name, structured=True)
        )
        _require_no_errors(report["normalization_compile_messages"])
        await bounded(service.save_project(library.stem, confirm=True))
        await bounded(service.save_project(project_name, confirm=True))
        report["model_finalization"] = verify_model_finalization(authored)
        report["saved_topology"] = audit_native_avm_fixture(project, receipt)
        report["probe_owners"] = _probe_owners(
            project, channel_units=FIXTURE_CHANNELS
        )
        initial = fresh_project_executable(project, normalization_started)
        canonical = run_dir / "canonicalization-evidence"
        canonical.mkdir()
        canonical_executable = canonical / Path(initial["path"]).name
        shutil.copy2(initial["path"], canonical_executable)
        if _sha256(canonical_executable) != initial["sha256"]:
            raise ValueError("Canonicalization executable preservation failed")
        report["canonicalization_executable"] = {
            **initial,
            "preserved_path": str(canonical_executable),
        }
        finalized_inputs = {
            str(project): _sha256(project),
            str(library): _sha256(library),
            **receipt["library"]["constants_artifacts"],
        }
        begin("clean_owned_build")
        native = await bounded(service.backend._project(project_name))
        await bounded(
            service.backend.executor.run_safe(
                native.clean, timeout=args.operation_timeout
            )
        )
        if list(project.parent.rglob(project.stem + ".exe")):
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
        executable = fresh_project_executable(project, compile_started)
        report["fresh_executable"] = executable
        before_run = run_dir / "before-run.exe"
        shutil.copy2(executable["path"], before_run)
        if _sha256(before_run) != executable["sha256"]:
            raise ValueError("Pre-run executable preservation failed")
        report["finalized_hashes_before_run"] = require_finalized_hashes(
            finalized_inputs
        )
        begin("run")
        run_started = time.time()
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
                raise RuntimeError(f"Native AVM integration run ended with {status}")
            if time.monotonic() >= deadline:
                raise TimeoutError("Native AVM integration run exceeded its deadline")
            await asyncio.sleep(0.5)
        report["run_messages"] = await bounded(
            service.get_project_output(project_name, structured=True)
        )
        _require_no_errors(report["run_messages"])
        report["executable_relink"] = verify_executable_relink(
            before_run, executable["path"]
        )
        if report["executable_relink"]["before_sha256"] != executable["sha256"]:
            raise ValueError("Preserved pre-run executable changed")
        finalized_inputs[str(before_run)] = report["executable_relink"][
            "before_sha256"
        ]
        finalized_inputs[executable["path"]] = report["executable_relink"][
            "after_sha256"
        ]
        begin("read_and_analyze")
        files = discover_run_outputs(
            project, run_started, metadata_started_after=compile_started
        )
        report["outputs"] = files
        outputs = [*files["parts"], files["inf"], files["infx"]]
        output_hashes = {str(path): _sha256(path) for path in outputs}
        observed = read_arm_trace(
            files, report["probe_owners"], channel_units=FIXTURE_CHANNELS
        )
        report["channel_sources"] = observed["channel_sources"]
        trace_path = run_dir / "trace.json"
        _write_report(trace_path, observed["samples"])
        report["trace"] = {"path": str(trace_path), "sha256": _sha256(trace_path)}
        report["analysis"] = analyze_integration_trace(observed["samples"])
        report["output_hashes_before_read"] = output_hashes
        report["output_hashes_after_read"] = require_finalized_hashes(output_hashes)
        report["finalized_hashes_after_run"] = require_finalized_hashes(
            finalized_inputs
        )
        report["status"] = report["analysis"]["status"]
        if report["status"] != "PASS":
            report["failure_category"] = (
                "model_physical"
                if report["analysis"]["measurement_complete"]
                else "implementation_or_measurement"
            )
    except BaseException as error:  # noqa: BLE001 - persist failed attempts
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
            except BaseException as diagnostic_error:  # noqa: BLE001
                report["failure_messages_error"] = _error(diagnostic_error)
    finally:
        try:
            if service is not None and attach_attempted:
                if not runtime:
                    runtime = await bounded(service.status())
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
                }
            if report["cleanup"].get("errors") or not report["cleanup"].get(
                "owned_process_cleaned"
            ):
                report["status"] = "FAIL"
                report.setdefault("failure_category", "process_cleanup")
        except BaseException as cleanup_error:  # noqa: BLE001
            report.update(status="FAIL", cleanup_error=_error(cleanup_error))
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
            report["code_after"] = code_after = _code_snapshot()
            report["source_code_immutable"] = (
                bool(code_before)
                and code_after["commit"] == code_before["commit"]
                and code_after["source_code_hashes"]
                == code_before["source_code_hashes"]
            )
            if not report["source_inputs_immutable"] or not report[
                "source_code_immutable"
            ]:
                report["status"] = "FAIL"
                report.setdefault("failure_category", "implementation_defect")
            report["artifacts"] = {
                str(path): {"sha256": _sha256(path), "bytes": path.stat().st_size}
                for path in run_dir.rglob("*")
                if path.is_file()
                and path not in {report_path, report_path.with_suffix(".json.tmp")}
            }
        except BaseException as finalization_error:  # noqa: BLE001
            report.update(status="FAIL", finalization_error=_error(finalization_error))
        report["assembly_accepted"] = report["status"] == "PASS"
        report["model_accepted"] = False
        report["finished_at"] = _stamp()
        _write_report(report_path, report)
    return report


def main(argv=None, *, service_factory=_service) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--constants-evidence", type=Path, required=True)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--source-project", type=Path, default=DEFAULT_DONOR)
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
        ("run-timeout", 300),
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
    run_dir = args.workspace_root.resolve() / (
        time.strftime("attempt-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    )
    run_dir.mkdir(parents=True)
    report = asyncio.run(run_attempt(args, run_dir, service_factory=service_factory))
    print(
        json.dumps(
            {
                "status": report["status"],
                "assembly_accepted": report["assembly_accepted"],
                "model_accepted": False,
                "report": str(run_dir / "report.json"),
            }
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
