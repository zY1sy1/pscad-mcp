"""Licensed public-lifecycle gate for the native cable MMC AVM assembly."""

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
from pathlib import Path
from typing import Any

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from pscad_mcp.acceptance.executable_finalization import verify_executable_relink
from pscad_mcp.acceptance.process_scope import concurrent_acceptance_enabled
from pscad_mcp.core.process_inventory import list_pscad_processes
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.cable_companion import DEFAULT_DONOR, DEFAULT_MASTER
from pscad_mcp.hvdc.builders.mmc.engines.avm import (
    AvmBlueprintEngine,
    discover_native_avm_sources,
)
from pscad_mcp.hvdc.builders.mmc.native_bundle import FIXTURE_CHANNELS, NATIVE_SCOPE
from pscad_mcp.hvdc.builders.mmc.native_energy import diagnose_native_arm_energy
from pscad_mcp.hvdc.builders.mmc.native_envelope import evaluate_native_steady_envelope
from pscad_mcp.hvdc.builders.mmc.native_physical import evaluate_native_network_identities
from pscad_mcp.hvdc.builders.mmc.native_startup import analyze_precharge_trace
from pscad_mcp.hvdc.builders.mmc.parametric_models import parse_parametric_request
from pscad_mcp.hvdc.builders.mmc.parametric_service import ParametricMmcBuilderService
from scripts.run_mmc_average_arm_acceptance import (
    _probe_owners,
    _require_no_errors,
    fresh_project_executable,
    read_arm_trace,
    require_finalized_hashes,
)
from scripts.run_mmc_native_avm_integration import analyze_integration_trace
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

SCOPE = "public_native_cable_avm_assembly"
REQUEST = {
    "schema_version": 1,
    "model_fidelity": "average_value",
    "topology": "two_terminal_symmetrical_monopole",
    "converter": "half_bridge",
    "dc_voltage_kv": 640.0,
    "active_power_mw": 1000.0,
    "reactive_power_mvar": 0.0,
    "frequency_hz": 60.0,
    "station_p": {
        "ac_voltage_kv": 230.0,
        "short_circuit_ratio": 5.0,
        "x_over_r": 10.0,
    },
    "station_vdc": {
        "ac_voltage_kv": 230.0,
        "short_circuit_ratio": 5.0,
        "x_over_r": 10.0,
    },
    "dc_link": {"kind": "cable", "length_km": 100.0},
    "power_reversal_time_s": 1.0,
    "engineering_overrides": {},
}


def _optins() -> None:
    for name in (
        "PSCAD_MCP_ACCEPTANCE",
        "PSCAD_MCP_NATIVE_AVM_PUBLIC_ACCEPTANCE",
    ):
        if os.environ.get(name) != "1":
            raise PermissionError(f"{name}=1 is required before an attempt")


def _code_snapshot() -> dict[str, Any]:
    snapshot = _runtime_snapshot()
    for path in (
        Path(__file__).resolve(),
        REPOSITORY / "tests/test_mmc_native_avm_public_acceptance.py",
        REPOSITORY / "pscad_mcp/hvdc/builders/mmc/engines/avm.py",
        REPOSITORY / "pscad_mcp/hvdc/builders/mmc/native_bundle.py",
        REPOSITORY / "pscad_mcp/hvdc/builders/mmc/parametric_service.py",
    ):
        snapshot["source_code_hashes"][str(path)] = _sha256(path)
    return snapshot


def _require_public_plan(
    plan: dict[str, Any],
    sources: dict[str, str],
    *,
    control_kind: str = "closed_loop",
) -> dict[str, Any]:
    children = plan.get("engine_plans", ())
    if len(children) != 1 or children[0].get("engine") != "average_value":
        raise ValueError("Public plan did not produce exactly one AVM child")
    child = children[0]
    if child.get("source_hashes") != sources:
        raise ValueError("Public AVM plan source hashes differ from immutable inputs")
    capabilities = child.get("capabilities", {})
    if (
        capabilities.get("native_physical_assembly") is not True
        or capabilities.get("native_cable_constants") is not True
        or capabilities.get("control_kind") != control_kind
        or capabilities.get("model_accepted") is not False
    ):
        raise ValueError("Public AVM plan overstates or omits native capabilities")
    return child


def _require_complete_trace(trace: dict, parameters: dict) -> None:
    times = trace.get("time", ())
    tolerance = 1.1 * float(parameters["output_step_s"])
    expected_end = float(parameters["simulation_duration_s"])
    if (len(times) < 2 or any(not math.isfinite(t) for t in times)
            or any(b <= a for a, b in zip(times, times[1:]))
            or times[0] > tolerance or times[-1] < expected_end - tolerance):
        raise BackendError("MMC_RUN_INCOMPLETE", "The native output does not cover the complete planned run.",
                           "hvdc", "native_avm_acceptance",
                           {"expected_end_s": expected_end, "observed_start_s": times[0] if times else None,
                            "observed_end_s": times[-1] if times else None})


def _public_failure_category(stage: str, error: BaseException, messages: list) -> str:
    text = json.dumps(messages).casefold()
    if "bind the new server socket" in text or "winsock error #10048" in text:
        return "environment_contention"
    if getattr(error, "code", "") == "MMC_RUN_INCOMPLETE":
        return "process_or_runtime"
    if getattr(error, "code", "") == "MMC_PRECHARGE_FAILED":
        return "model_physical"
    return _category(stage, error)


async def run_attempt(
    args: argparse.Namespace,
    run_dir: Path,
    *,
    service_factory=_service,
    builder_factory=ParametricMmcBuilderService,
) -> dict[str, Any]:
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
            "Complete startup, protection, PLL, energy/ripple, reversal, fault and portable reload acceptance remain pending. Fixed golden comparison applies only to the fixed profile."
        ],
        "stages": [],
    }
    service = None
    runtime: dict[str, Any] = {}
    project_name: str | None = None
    run_pending = attach_attempted = False
    source_hashes: dict[str, str] = {}
    finalized_inputs: dict[str, str] = {}
    code_before: dict[str, Any] = {}
    stage = "inputs"

    def begin(name: str) -> None:
        nonlocal stage
        stage = name
        report["stages"].append({"name": name, "started_at": _stamp()})
        _write_report(report_path, report)
        print("MMC_NATIVE_AVM_PUBLIC_STAGE=" + name, flush=True)

    async def bounded(awaitable: Any, timeout: float | None = None) -> Any:
        return await asyncio.wait_for(awaitable, timeout or args.operation_timeout)

    try:
        begin("inputs")
        paths = {
            "master": args.master.resolve(),
            "cable_donor": args.source_project.resolve(),
            "tline": args.tline.resolve(),
            "compiler_configuration": args.compiler_configuration.resolve(),
            "compiler_executable": args.compiler_executable.resolve(),
        }
        request_path = getattr(args, "request_json", None)
        if request_path is not None:
            paths["request_json"] = request_path.resolve()
        for path in paths.values():
            if path.is_symlink() or not path.is_file():
                raise FileNotFoundError(f"Required immutable input is unavailable: {path}")
        source_hashes = {name: _sha256(path) for name, path in paths.items()}
        report["source_paths"] = {name: str(path) for name, path in paths.items()}
        report["source_hashes_before"] = source_hashes
        request = parse_parametric_request(
            json.loads(paths["request_json"].read_text(encoding="utf-8"))
            if request_path is not None else REQUEST
        ).to_dict()
        report["request"] = request
        report["code_before"] = code_before = _code_snapshot()
        if code_before["working_tree_status"]:
            raise ValueError("Public AVM acceptance requires a clean frozen checkout")
        report["processes_before"] = list_pscad_processes()
        workspace = run_dir / "workspace"
        workspace.mkdir()

        begin("attach")
        service = service_factory(run_dir)
        attach_attempted = True
        report["attach_result"] = await bounded(service.attach_local())
        runtime = await bounded(service.status())
        report["runtime"] = runtime
        require_runtime(runtime)

        begin("plan")
        control_kind = getattr(args, "control_kind", "closed_loop")
        if control_kind == "closed_loop":
            builder = builder_factory(service, workspace_root=workspace)
        else:
            native_sources = discover_native_avm_sources(
                master_path=args.master,
                source_project=args.source_project,
                executable=args.tline,
            )
            builder = builder_factory(
                service,
                workspace_root=workspace,
                avm_engine=AvmBlueprintEngine(
                    native_sources=native_sources,
                    native_required=True,
                    native_control_kind=control_kind,
                ),
            )
        plan = builder.plan_model(
            request,
            project_name="MMC_PUBLIC_NATIVE",
            folder=str(workspace),
        )
        report["plan"] = plan
        child = _require_public_plan(
            plan,
            {name: source_hashes[name] for name in ("master", "cable_donor", "tline")},
            control_kind=control_kind,
        )
        report["diagnostic_control_kind"] = control_kind

        begin("build_and_verify_acceptance_boundary")
        started = await builder.build_model(
            request,
            plan["plan_hash"],
            "MMC_PUBLIC_NATIVE",
            str(workspace),
            confirm=True,
        )
        report["build_started"] = started
        deadline = time.monotonic() + args.build_timeout
        while True:
            terminal = builder.get_status(started["build_id"])
            if terminal.get("state") in {"built", "published", "failed", "interrupted"}:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Public native AVM build exceeded its deadline")
            await asyncio.sleep(0.25)
        report["build_terminal"] = terminal
        if terminal.get("state") != "built":
            raise RuntimeError("Public native AVM must retain unaccepted candidates in staging")
        engine = terminal["engines"][0]
        if (
            engine.get("capability_level") != "built"
            or engine.get("model_accepted") is not False
            or terminal.get("result", {}).get("model_accepted") is not False
        ):
            raise ValueError("Public lifecycle overstated native AVM acceptance")
        project = Path(engine["candidate_result"]["project_path"]).resolve()
        library = Path(engine["candidate_result"]["library_path"]).resolve()
        if not project.is_relative_to(workspace) or Path(child["target_path"]).exists():
            raise ValueError("An unaccepted native AVM candidate escaped staging or was published")
        report["publication_blocked_until_full_acceptance"] = True
        project_name = project.stem
        diagnostic_step = getattr(args, "diagnostic_time_step_us", None)
        if diagnostic_step is not None:
            original_settings = await bounded(service.get_project_settings(project_name))
            await bounded(service.set_project_settings(project_name, {"time_step": str(diagnostic_step)}))
            observed_settings = await bounded(service.get_project_settings(project_name))
            if float(observed_settings["time_step"]) != diagnostic_step:
                raise ValueError("Diagnostic EMT timestep did not read back")
            report["timestep_diagnostic"] = {
                "planned_time_step_us": float(original_settings["time_step"]),
                "applied_time_step_us": diagnostic_step,
                "public_plan_execution_unchanged": False,
            }
            report["scope"] = "native_avm_timestep_diagnostic"
        await bounded(service.save_project(NATIVE_SCOPE, confirm=True))
        await bounded(service.save_project(project_name, confirm=True))
        report["probe_owners"] = _probe_owners(
            project, channel_units=FIXTURE_CHANNELS
        )
        finalized_inputs = {
            str(project): _sha256(project),
            str(library): _sha256(library),
            **{
                path: digest
                for path, digest in engine["candidate_result"]["fixture"]["library"][
                    "constants_artifacts"
                ].items()
            },
        }

        begin("clean_owned_build")
        native = await bounded(service.backend._project(project_name))
        await bounded(
            service.backend.executor.run_safe(
                native.clean, timeout=args.operation_timeout
            )
        )
        if list(project.parent.rglob(project.stem + ".exe")):
            raise ValueError("Public native AVM clean retained a project executable")
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
                raise RuntimeError(f"Public native AVM run ended with {status}")
            if time.monotonic() >= deadline:
                raise TimeoutError("Public native AVM run exceeded its deadline")
            await asyncio.sleep(0.5)
        report["run_messages"] = await bounded(
            service.get_project_output(project_name, structured=True)
        )
        _require_no_errors(report["run_messages"])
        report["executable_relink"] = verify_executable_relink(
            before_run, executable["path"]
        )

        begin("read_and_analyze")
        files = discover_run_outputs(
            project, run_started, metadata_started_after=compile_started
        )
        report["outputs"] = files
        observed = read_arm_trace(
            files, report["probe_owners"], channel_units=FIXTURE_CHANNELS
        )
        report["channel_sources"] = observed["channel_sources"]
        trace_path = run_dir / "trace.json"
        _write_report(trace_path, observed["samples"])
        report["trace"] = {"path": str(trace_path), "sha256": _sha256(trace_path)}
        fixture_parameters = engine["candidate_result"]["fixture"]["parameters"]
        _require_complete_trace(observed["samples"], fixture_parameters)
        reversal_end = fixture_parameters["reversal_time_s"] + fixture_parameters["reversal_duration_s"]
        forward_window = (0.6, 0.9)
        reverse_window = (reversal_end + 0.5, reversal_end + 0.8)
        deblock_time = fixture_parameters["deblock_time_s"]
        if control_kind == "closed_loop":
            report["precharge"] = analyze_precharge_trace(observed["samples"], fixture_parameters)
            if "operating_windows" not in report["precharge"]:
                raise BackendError("MMC_PRECHARGE_FAILED", report["precharge"].get("error", "Precharge operating windows are missing"),
                                   "hvdc", "native_avm_acceptance", report["precharge"])
            forward_window = tuple(report["precharge"]["operating_windows"]["forward"])
            reverse_window = tuple(report["precharge"]["operating_windows"]["reverse"])
            deblock_time = report["precharge"]["deblock_time_s"]
        report["energy_diagnostics"] = diagnose_native_arm_energy(
            observed["samples"],
            engine["candidate_result"]["fixture"]["parameters"]["arm"],
            windows=(forward_window, reverse_window),
        )
        if control_kind == "closed_loop":
            report["steady_envelope"] = evaluate_native_steady_envelope(
                observed["samples"], power_mw=request["active_power_mw"],
                voltage_kv=request["dc_voltage_kv"], reactive_mvar=request["reactive_power_mvar"],
                forward_window_s=forward_window,
                reverse_window_s=reverse_window,
            )
            report["network_identities"] = evaluate_native_network_identities(
                observed["samples"],
                capacitance_f=fixture_parameters["arm"]["C_eq_F"],
                grounding_resistance_ohm=fixture_parameters["dc_grounding_resistance_ohm"],
                valve_grounding_resistance_ohm=fixture_parameters["valve_grounding_resistance_ohm"],
                voltage_kv=request["dc_voltage_kv"], frequency_hz=request["frequency_hz"],
                windows={"forward": forward_window, "reverse": reverse_window},
            )
        report["analysis"] = analyze_integration_trace(
            observed["samples"],
            sequence_windows=(
                (0.02, deblock_time - 0.01, 1.0),
                (*forward_window, 2.0),
                (*reverse_window, 3.0),
            ),
            minimum_end_s=fixture_parameters["simulation_duration_s"] - 0.001,
        )
        report["assembly_accepted"] = report["analysis"]["status"] == "PASS"
        report["steady_operating_accepted"] = report.get("steady_envelope", {}).get("status") == "PASS"
        report["network_identities_accepted"] = report.get("network_identities", {}).get("status") == "PASS"
        report["precharge_accepted"] = report.get("precharge", {}).get("status") == "PASS"
        report["status"] = (
            "PASS" if report["assembly_accepted"]
            and (control_kind != "closed_loop" or (report["steady_operating_accepted"] and report["network_identities_accepted"] and report["precharge_accepted"]))
            else "FAIL"
        )
        if report["status"] != "PASS":
            report["failure_category"] = (
                "model_physical"
                if report["analysis"]["measurement_complete"]
                else "implementation_or_measurement"
            )
        output_paths = [*files["parts"], files["inf"], files["infx"]]
        output_hashes = {str(path): _sha256(path) for path in output_paths}
        report["output_hashes_before_read"] = output_hashes
        report["output_hashes_after_read"] = require_finalized_hashes(output_hashes)
        report["finalized_hashes_after_run"] = require_finalized_hashes(
            finalized_inputs
        )
    except BaseException as error:  # noqa: BLE001 - failed attempts are evidence
        report.update(
            status="FAIL",
            assembly_accepted=False,
            error=_error(error),
            failed_stage=stage,
            failure_category=_public_failure_category(stage, error, report.get("run_messages", [])),
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
                report["cleanup"] = await cleanup_owned_session(
                    service,
                    runtime or await bounded(service.status()),
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
                report["assembly_accepted"] = False
                report.setdefault("failure_category", "process_cleanup")
        except BaseException as cleanup_error:  # noqa: BLE001
            report.update(
                status="FAIL",
                assembly_accepted=False,
                cleanup_error=_error(cleanup_error),
            )
        try:
            report["source_hashes_after"] = {
                name: _sha256(Path(path))
                for name, path in report.get("source_paths", {}).items()
            }
            report["source_inputs_immutable"] = (
                bool(source_hashes)
                and report["source_hashes_after"] == source_hashes
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
                report["assembly_accepted"] = False
                report.setdefault("failure_category", "implementation_defect")
            report["artifacts"] = {
                str(path): {"sha256": _sha256(path), "bytes": path.stat().st_size}
                for path in run_dir.rglob("*")
                if path.is_file()
                and path not in {report_path, report_path.with_suffix(".json.tmp")}
            }
        except BaseException as finalization_error:  # noqa: BLE001
            report.update(
                status="FAIL",
                assembly_accepted=False,
                finalization_error=_error(finalization_error),
            )
        report["model_accepted"] = False
        report["finished_at"] = _stamp()
        _write_report(report_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--request-json", type=Path, help="Immutable complete parameterized AVM request; included in source hashes")
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--source-project", type=Path, default=DEFAULT_DONOR)
    parser.add_argument("--diagnostic-time-step-us", type=float)
    parser.add_argument(
        "--control-kind",
        choices=("scheduled_open_loop", "closed_loop"),
        default="closed_loop",
    )
    parser.add_argument(
        "--tline",
        type=Path,
        default=DEFAULT_MASTER.parent / "bin" / "win" / "tline.exe",
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
        ("operation-timeout", 180.0),
        ("build-timeout", 900.0),
        ("run-timeout", 300.0),
        ("cleanup-timeout", 30.0),
    ):
        parser.add_argument("--" + name, type=float, default=default)
    args = parser.parse_args(argv)
    if args.diagnostic_time_step_us is not None and (
        not math.isfinite(args.diagnostic_time_step_us)
        or args.diagnostic_time_step_us <= 0
    ):
        parser.error("Diagnostic timestep must be finite and positive")
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
        raise SystemExit("Workspace must be absolute and timeout values finite and positive")
    run_dir = args.workspace_root.resolve() / (
        time.strftime("attempt-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    )
    run_dir.mkdir(parents=True)
    report = asyncio.run(run_attempt(args, run_dir))
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
