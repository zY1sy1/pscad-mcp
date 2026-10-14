"""Licensed compile/run probe for a prepared PWM command circuit.

This runner cannot certify a converter: its report always records
model_accepted=false. Complete scenario and physical evidence are separate.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pscad_mcp.acceptance.preflight_cli import _service
from pscad_mcp.acceptance.process_scope import (
    remaining_acceptance_processes,
    require_acceptance_ownership,
)
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.executor import robust_executor
from pscad_mcp.core.process_inventory import list_pscad_processes
from pscad_mcp.hvdc.builders.mmc import timed_control
from pscad_mcp.hvdc.builders.mmc.engines.pwm import _copy_library_support
from pscad_mcp.hvdc.builders.mmc.line_constants import (
    generate_public_line_constants,
    rebind_template_line_constants,
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def run(args, report, checkpoint):
    source, library = args.source.resolve(), args.library.resolve()
    directory = args.workspace.resolve()
    inputs = [source, library, Path(r"C:\Program Files (x86)\PSCAD46\master.pslx")]
    if args.scenario is not None:
        inputs.append(args.scenario.resolve())
    originals = {str(p): _hash(p) for p in inputs}
    report["original_inputs"] = originals
    report["tested_commit"] = (
        await asyncio.to_thread(
            subprocess.check_output, ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        )
    ).strip()
    report["producer_hashes"] = {
        str(p.relative_to(ROOT)): _hash(p)
        for p in (
            Path(__file__),
            ROOT / "pscad_mcp/hvdc/builders/mmc/pwm_commands.py",
        )
    }
    constants = generate_public_line_constants(source, directory / "line-constants")
    report["line_constants"] = [c.to_dict() for c in constants]
    project = rebind_template_line_constants(
        source, constants, directory / "H_MMC_Mono_DC.pscx"
    )
    shutil.copy2(library, directory / "intermediate.pslx")
    _copy_library_support(library, directory)
    tree = ET.parse(project)
    schedule = None
    if args.scenario is not None:
        scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
        schedule = scenario["timed_control"]
        if Path(schedule["scenario_source"]["path"]).resolve() != source or schedule[
            "scenario_source"
        ]["sha256"] != _hash(source):
            raise RuntimeError("The schedule does not bind the supplied source")
        if args.duration != schedule["duration_s"]:
            raise RuntimeError("Simulation duration differs from the schedule")
        tree = ET.ElementTree(timed_control._render(schedule, project.stem))
        for constant in constants:
            found = 0
            for wire in tree.getroot().findall(".//Wire[@classid='TLine']"):
                fields = {
                    p.get("name"): p for p in wire.findall("./User/paramlist/param")
                }
                if (
                    fields.get("Name") is not None
                    and fields["Name"].get("value") == constant.segment
                ):
                    fields["const_path"].set("value", constant.constants_path)
                    found += 1
            if found != 1:
                raise RuntimeError(
                    "The timed case has no unique line constants binding"
                )
        report["schedule_sha256"] = schedule["schedule_sha256"]
    parameters = tree.getroot().find("paramlist")
    for name, value in {
        "StartType": "0",
        "startup_filename": "",
        "PlotType": "1",
        "output_filename": "H_MMC_Mono_DC.out",
        "time_duration": str(args.duration),
        "time_step": "10",
        "sample_step": "50",
    }.items():
        parameter = parameters.find(f"param[@name='{name}']")
        if parameter is None:
            parameter = ET.SubElement(parameters, "param", {"name": name})
        parameter.set("value", value)
    tree.write(project, encoding="utf-8", xml_declaration=True)
    report["prepared_input_sha256"] = _hash(project)
    service = _service(directory)
    runtime = None
    pending = False
    try:
        report["stage"] = "attach"
        checkpoint()
        await service.attach_local()
        runtime = await service.status()
        require_acceptance_ownership(runtime)
        if runtime.get("licensed") is not True:
            raise RuntimeError("The owned instance is not licensed")
        report["runtime"] = runtime
        checkpoint()
        report["stage"] = "load"
        checkpoint()
        await service.load_projects(
            [str(directory / "intermediate.pslx"), str(project)]
        )
        cases = [
            p
            for p in await service.list_projects()
            if p.get("type", "").casefold() == "case"
        ]
        if len(cases) != 1:
            raise RuntimeError(f"Expected one owned case, observed {cases}")
        name = cases[0]["name"]
        await service.save_project(name, confirm=True)
        if schedule is not None:
            report["timed_readback"] = timed_control.verify_embedded_control(
                schedule, project
            )
        report["saved_project_sha256"] = _hash(project)
        report["stage"] = "compile"
        checkpoint()
        report["build_result"] = await service.build_project(name)
        report["build_messages"] = await service.get_project_output(
            name, structured=True
        )
        checkpoint()
        errors = [
            m
            for m in report["build_messages"]
            if str(m.get("severity", "")).casefold() in ("error", "fatal")
        ]
        if errors:
            raise RuntimeError(f"PWM compile has {len(errors)} errors")
        if args.simulate:
            report["stage"] = "run"
            checkpoint()
            report["run_started_after"] = time.time()
            pending = True
            report["run_result"] = await service.run_project(name)
            deadline = time.monotonic() + args.timeout
            while True:
                state = await service.get_run_status(name)
                report["run_state"] = state
                checkpoint()
                status = str(state.get("status", "")).casefold()
                if status in {"completed", "complete", "idle"}:
                    pending = False
                    break
                if status in {"failed", "stopped", "interrupted"}:
                    raise RuntimeError(f"Simulation ended with {status}")
                if time.monotonic() > deadline:
                    raise TimeoutError("Owned PWM simulation timed out")
                await asyncio.sleep(0.5)
            outputs = [
                p
                for p in directory.rglob("*.out")
                if p.stat().st_mtime >= report["run_started_after"]
                and "line-constants" not in p.parts
            ]
            if not outputs:
                raise RuntimeError("No fresh PWM OUT files")
            report["output_files"] = {str(p): _hash(p) for p in outputs}
            if schedule is not None:
                report["timing_evidence"] = timed_control.read_event_evidence(
                    schedule,
                    project,
                    outputs,
                    started_after=report["run_started_after"],
                )
        report["status"] = "PASS"
    finally:
        if pending:
            try:
                report["stop_result"] = await service.stop_project(name)
            except Exception as error:  # noqa: BLE001 - preserve the owned stop failure
                report["stop_error"] = str(error)
        report["stage"] = "cleanup"
        checkpoint()
        try:
            report["quit_result"] = await service.quit_pscad(confirm=True)
        except Exception as error:  # noqa: BLE001 - preserve the owned cleanup failure
            report["quit_error"] = str(error)
            report["status"] = "FAIL"
        report["sources_immutable"] = all(
            _hash(Path(p)) == digest for p, digest in originals.items()
        )
        if runtime is not None:
            report["remaining_owned_processes"] = remaining_acceptance_processes(
                runtime, list_pscad_processes
            )
        if (
            not report["sources_immutable"]
            or report.get("remaining_owned_processes")
            or report.get("quit_error")
        ):
            report["status"] = "FAIL"
        checkpoint()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--scenario", type=Path)
    parser.add_argument("--duration", type=float, default=0.8)
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()
    for name in ("PSCAD_MCP_ACCEPTANCE", "PSCAD_MCP_MMC_ACCEPTANCE"):
        if os.getenv(name) != "1":
            raise SystemExit(f"{name}=1 is required")
    args.workspace.resolve().mkdir(parents=True, exist_ok=False)
    report_path = args.workspace.resolve() / "report.json"
    report = {
        "schema_version": 1,
        "scope": "mmc.detailed_pwm.command_interface_probe",
        "status": "FAIL",
        "model_accepted": False,
        "stage": "prepare",
        "simulate": args.simulate,
        "duration_s": args.duration,
    }

    def checkpoint():
        temporary = report_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8"
        )
        temporary.replace(report_path)

    checkpoint()
    try:
        asyncio.run(run(args, report, checkpoint))
    except Exception as error:  # noqa: BLE001 - persist the complete attempt verdict
        report["status"] = "FAIL"
        report["error"] = (
            error.to_dict()
            if isinstance(error, BackendError)
            else {"type": type(error).__name__, "message": str(error)}
        )
    finally:
        robust_executor.shutdown()
        report["stage"] = "finished"
        checkpoint()
    print(
        json.dumps(
            {
                "report": str(report_path),
                "status": report["status"],
                "error": report.get("error"),
                "model_accepted": False,
            }
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
