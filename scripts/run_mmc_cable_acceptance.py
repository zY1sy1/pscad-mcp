"""Licensed isolated native cable DC-loop acceptance with immutable evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from pscad_mcp.acceptance.executable_finalization import verify_executable_relink
from pscad_mcp.acceptance.process_scope import concurrent_acceptance_enabled
from pscad_mcp.core.process_inventory import list_pscad_processes
from pscad_mcp.hvdc.builders.mmc.cable_companion import (
    CHANNEL_UNITS,
    DEFAULT_DONOR,
    DEFAULT_MASTER,
    analyze_cable_loop,
    audit_cable_assembly,
    materialize_cable_loop_fixture,
)
from scripts.run_mmc_average_arm_acceptance import (
    _code_snapshot,
    _probe_owners,
    _require_no_errors,
    fresh_project_executable,
    read_arm_trace,
    require_finalized_hashes,
    snapshot_model_inputs,
    verify_model_normalization,
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


def _optins():
    for name in ("PSCAD_MCP_ACCEPTANCE", "PSCAD_MCP_CABLE_ACCEPTANCE"):
        if os.environ.get(name) != "1":
            raise PermissionError(f"{name}=1 is required before an attempt")


def _code():
    snapshot = _code_snapshot()
    snapshot["source_code_hashes"][str(Path(__file__).resolve())] = _sha256(
        Path(__file__)
    )
    return snapshot


async def run_attempt(args, run_dir, *, service_factory=_service):
    _optins()
    report_path = run_dir / "report.json"
    report = {
        "schema_version": 1,
        "scope": "native_two_conductor_cable_dc_loop",
        "status": "FAIL",
        "component_accepted": False,
        "model_accepted": False,
        "started_at": _stamp(),
        "concurrent": concurrent_acceptance_enabled(),
        "stages": [],
    }
    service, runtime, project_name = None, {}, None
    pending, stage = False, "inputs"
    source_hashes, finalized, code_before = {}, {}, {}

    def begin(name):
        nonlocal stage
        stage = name
        report["stages"].append({"name": name, "started_at": _stamp()})
        _write_report(report_path, report)
        print("MMC_CABLE_STAGE=" + name, flush=True)

    async def bounded(awaitable):
        return await asyncio.wait_for(awaitable, args.timeout)

    try:
        begin("inputs")
        report["code_before"] = code_before = _code()
        if code_before["working_tree_status"]:
            raise ValueError("Native cable acceptance requires a frozen clean checkout")
        report["processes_before"] = list_pscad_processes()
        begin("materialize")
        receipt = materialize_cable_loop_fixture(
            run_dir / "model",
            constants_evidence=args.constants_evidence,
            source_project=args.source_project,
            master_path=args.master,
        )
        report["fixture"] = receipt
        source_hashes = dict(receipt["source_hashes_before"])
        report["source_hashes_before"] = source_hashes
        project = Path(receipt["project_path"])
        project_name = receipt["project_name"]
        preserved = run_dir / "authored.pscx"
        shutil.copy2(project, preserved)
        authored = snapshot_model_inputs((project,))
        report["authored_snapshots"] = authored
        begin("attach")
        service = service_factory(run_dir)
        report["attach_result"] = await bounded(service.attach_local())
        runtime = await bounded(service.status())
        report["runtime"] = runtime
        require_runtime(runtime)
        begin("initial_compile")
        await bounded(service.load_projects([str(project)]))
        await bounded(service.save_project(project_name, confirm=True))
        started = time.time()
        await bounded(service.build_project(project_name))
        report["initial_compile_messages"] = await bounded(
            service.get_project_output(project_name, structured=True)
        )
        _require_no_errors(report["initial_compile_messages"])
        await bounded(service.save_project(project_name, confirm=True))
        report["model_finalization"] = verify_model_normalization(authored)
        report["saved_topology"] = audit_cable_assembly(project, receipt)
        initial = fresh_project_executable(project, started)
        shutil.copy2(initial["path"], run_dir / "initial-build.exe")
        finalized = {
            str(project): _sha256(project),
            str(preserved): _sha256(preserved),
            **{
                path: digest
                for path, digest in receipt["delivered_hashes"].items()
                if path != str(project)
            },
        }
        begin("fresh_compile")
        native = await bounded(service.backend._project(project_name))
        await bounded(
            service.backend.executor.run_safe(native.clean, timeout=args.timeout)
        )
        if list(project.parent.rglob(project.stem + ".exe")):
            raise ValueError("Vendor clean retained a prior executable")
        started = time.time()
        await bounded(service.build_project(project_name))
        report["compile_messages"] = await bounded(
            service.get_project_output(project_name, structured=True)
        )
        _require_no_errors(report["compile_messages"])
        executable = fresh_project_executable(project, started)
        report["fresh_executable"] = executable
        before_run = run_dir / "before-run.exe"
        shutil.copy2(executable["path"], before_run)
        if _sha256(before_run) != executable["sha256"]:
            raise ValueError("Pre-run executable copy changed")
        report["finalized_hashes_before_run"] = require_finalized_hashes(finalized)
        owners = _probe_owners(project, channel_units=CHANNEL_UNITS)
        report["probe_owners"] = owners
        begin("run")
        run_started = time.time()
        pending = True
        await bounded(service.run_project(project_name))
        deadline = time.monotonic() + args.timeout
        while True:
            state = await bounded(service.get_run_status(project_name))
            if state.get("status") in ("complete", "completed", "idle"):
                pending = False
                break
            if state.get("status") in ("failed", "stopped", "interrupted"):
                raise ValueError(f"Cable run ended with {state}")
            if time.monotonic() >= deadline:
                raise TimeoutError("Cable run exceeded its deadline")
            await asyncio.sleep(0.5)
        report["run_messages"] = await bounded(
            service.get_project_output(project_name, structured=True)
        )
        _require_no_errors(report["run_messages"])
        relink = verify_executable_relink(before_run, executable["path"])
        if relink["before_sha256"] != executable["sha256"]:
            raise ValueError("Preserved executable changed")
        report["executable_relink"] = relink
        finalized[str(before_run)] = relink["before_sha256"]
        finalized[executable["path"]] = relink["after_sha256"]
        begin("read_and_analyze")
        files = discover_run_outputs(
            project, run_started, metadata_started_after=started
        )
        outputs = {
            str(path): _sha256(Path(path))
            for path in (*files["parts"], files["inf"], files["infx"])
        }
        observed = read_arm_trace(files, owners, channel_units=CHANNEL_UNITS)
        report["outputs"] = files
        report["channel_sources"] = observed["channel_sources"]
        _write_report(run_dir / "trace.json", observed["samples"])
        report["output_hashes"] = require_finalized_hashes(outputs)
        report["analysis"] = analyze_cable_loop(
            observed["samples"], receipt["physical_reference"]
        )
        report["status"] = report["analysis"]["status"]
        if report["status"] != "PASS":
            report["failure_category"] = (
                "model_physical"
                if report["analysis"]["measurement_complete"]
                else "implementation_or_measurement"
            )
    except BaseException as error:
        report.update(
            status="FAIL",
            error=_error(error),
            failed_stage=stage,
            failure_category=_category(stage, error),
        )
        if service is not None and runtime.get("owns_process") and project_name:
            try:
                report["failure_messages"] = await bounded(
                    service.get_project_output(project_name, structured=True)
                )
            except BaseException as error:
                report["diagnostic_error"] = _error(error)
    finally:
        try:
            if service is not None:
                runtime = runtime or await bounded(service.status())
                report["cleanup"] = await cleanup_owned_session(
                    service,
                    runtime,
                    project_name=project_name,
                    run_pending=pending,
                    timeout=30,
                )
                if report["cleanup"].get("errors") or not report["cleanup"].get(
                    "owned_process_cleaned"
                ):
                    report["status"] = "FAIL"
            else:
                report["cleanup"] = {
                    "owned_process_cleaned": True,
                    "runtime_started": False,
                }
        except BaseException as error:
            report.update(status="FAIL", cleanup_error=_error(error))
        try:
            if finalized:
                report["finalized_hashes_after_cleanup"] = require_finalized_hashes(
                    finalized
                )
            if source_hashes:
                report["source_hashes_after"] = require_finalized_hashes(source_hashes)
            report["code_after"] = after = _code()
            if code_before and (
                after["commit"] != code_before["commit"]
                or after["source_code_hashes"] != code_before["source_code_hashes"]
            ):
                raise ValueError("Acceptance source code changed during the run")
        except BaseException as error:
            report.update(status="FAIL", integrity_error=_error(error))
        report["artifacts"] = {
            str(p): {"sha256": _sha256(p), "bytes": p.stat().st_size}
            for p in run_dir.rglob("*")
            if p.is_file() and p != report_path
        }
        report["finished_at"] = _stamp()
        report["component_accepted"] = report["status"] == "PASS"
        _write_report(report_path, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--constants-evidence", type=Path, required=True)
    parser.add_argument("--source-project", type=Path, default=DEFAULT_DONOR)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args(argv)
    _optins()
    if not args.workspace_root.is_absolute() or not 0 < args.timeout <= 1800:
        raise ValueError(
            "An absolute workspace and bounded positive timeout are required"
        )
    if args.workspace_root.resolve().is_relative_to(REPOSITORY):
        raise ValueError("Acceptance output must be outside the source checkout")
    folder = args.workspace_root / (
        time.strftime("attempt-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    )
    folder.mkdir(parents=True)
    report = asyncio.run(run_attempt(args, folder))
    print(
        json.dumps(
            {
                "status": report["status"],
                "component_accepted": report["component_accepted"],
                "report": str(folder / "report.json"),
            }
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
