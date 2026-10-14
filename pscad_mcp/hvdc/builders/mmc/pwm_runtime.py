"""Shared lifecycle for fresh, owned routed PWM simulations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import psutil

from ....acceptance.preflight_cli import _service
from ....acceptance.process_scope import (
    remaining_acceptance_processes,
    require_acceptance_ownership,
)
from ....core.process_inventory import list_pscad_processes
from . import timed_control
from .engines.pwm import _copy_library_support
from .line_constants import (
    generate_public_line_constants,
    rebind_template_line_constants,
)

ROOT = Path(__file__).resolve().parents[4]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_report(path: Path, report: dict) -> None:
    """Retry transient Windows sharing locks while retaining atomic publication."""
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
    ) as stream:
        json.dump(report, stream, indent=2, ensure_ascii=True)
        temporary = Path(stream.name)
    try:
        for attempt in range(8):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def owned_children(runtime: dict | None) -> list[dict]:
    if runtime is None:
        return []
    pid = runtime["session"]["managed_pid"]
    try:
        children = psutil.Process(pid).children(recursive=True)
    except psutil.NoSuchProcess:
        return []
    records = []
    for child in children:
        try:
            records.append({"pid": child.pid, "name": child.name(), "exe": child.exe()})
        except psutil.NoSuchProcess:
            continue
    return records


async def cleanup_owned(service, name, runtime, originals, report, checkpoint, pending):
    """A failed report checkpoint must never bypass owned process cleanup."""
    if pending and name is not None:
        try:
            report["stop_result"] = await service.stop_simulation(name)
        except Exception as error:  # noqa: BLE001 - retain the actual stop failure
            report["stop_error"] = str(error)
    report["stage"] = "cleanup"
    try:
        checkpoint()
    except OSError as error:
        report.setdefault("checkpoint_errors", []).append(str(error))
        report["status"] = "FAIL"
    try:
        report["quit_result"] = await service.quit_pscad(confirm=True)
    except Exception as error:  # noqa: BLE001 - retain owned cleanup evidence
        report["quit_error"] = str(error)
        report["status"] = "FAIL"
    report["sources_immutable"] = all(
        _hash(Path(path)) == digest for path, digest in originals.items()
    )
    if runtime is not None:
        report["remaining_owned_processes"] = remaining_acceptance_processes(
            runtime, list_pscad_processes
        )
    if not report["sources_immutable"] or report.get("remaining_owned_processes"):
        report["status"] = "FAIL"
    try:
        checkpoint()
    except OSError as error:
        report.setdefault("checkpoint_errors", []).append(str(error))
        report["status"] = "FAIL"


async def run(args, report, checkpoint, *, service=None):
    source, library = args.source.resolve(), args.library.resolve()
    directory = args.workspace.resolve()
    inputs = [
        source,
        library,
        Path(getattr(args, "master", r"C:\Program Files (x86)\PSCAD46\master.pslx")),
    ]
    if args.scenario is not None:
        inputs.append(args.scenario.resolve())
    originals = {str(p): _hash(p) for p in inputs}
    report["original_inputs"] = originals
    try:
        report["tested_commit"] = (
            await asyncio.to_thread(
                subprocess.check_output,
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            )
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        report["tested_commit"] = None
    report["producer_hashes"] = {
        str(p.relative_to(ROOT)): _hash(p)
        for p in (
            *Path(__file__).parent.glob("pwm_*.py"),
            ROOT / "scripts/run_mmc_pwm_command_probe.py",
            ROOT / "pscad_mcp/hvdc/builders/mmc/fault_channels.py",
            ROOT / "pscad_mcp/hvdc/builders/mmc/timed_control.py",
        )
        if p.is_file()
    }
    constants = generate_public_line_constants(source, directory / "line-constants")
    report["line_constants"] = [c.to_dict() for c in constants]
    project = rebind_template_line_constants(
        source, constants, directory / f"{args.case_name}.pscx"
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
    if schedule is None:
        original_namespace = tree.getroot().get("name")
        tree.getroot().set("name", project.stem)
        for component in tree.getroot().iter():
            for key in ("defn", "name"):
                value = component.get(key, "")
                if value.startswith(original_namespace + ":"):
                    component.set(key, project.stem + value[len(original_namespace) :])
    for name, value in {
        "StartType": "0",
        "startup_filename": "",
        "PlotType": "1",
        "output_filename": f"{args.case_name}.out",
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
    owns_session_lifecycle = service is None
    service = _service(directory) if service is None else service
    runtime = None
    name = None
    pending = False
    try:
        report["stage"] = "attach"
        checkpoint()
        if owns_session_lifecycle:
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
            and p.get("name") == args.case_name
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
            startup_deadline = time.monotonic() + args.startup_timeout
            activity_seen = False
            while True:
                state = await service.get_run_status(name)
                report["run_state"] = state
                checkpoint()
                status = str(state.get("status", "")).casefold()
                activity_seen = activity_seen or status in {"running", "paused"}
                if status in {"completed", "complete", "idle"}:
                    fresh = [
                        p
                        for p in directory.glob(f"{project.stem}.*/*.out")
                        if p.name.startswith(project.stem + "_")
                        and p.stat().st_mtime >= report["run_started_after"]
                    ]
                    if fresh:
                        pending = False
                        break
                if status in {"failed", "stopped", "interrupted"}:
                    raise RuntimeError(f"Simulation ended with {status}")
                if not activity_seen and time.monotonic() > startup_deadline:
                    raise RuntimeError(
                        "Owned PWM solver did not start or produce output"
                    )
                if time.monotonic() > deadline:
                    raise TimeoutError("Owned PWM simulation timed out")
                await asyncio.sleep(0.5)
            outputs = [
                p
                for p in directory.glob(f"{project.stem}.*/*.out")
                if p.stat().st_mtime >= report["run_started_after"]
                and p.name.startswith(project.stem + "_")
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
    except Exception:
        if name is not None:
            try:
                report["post_run_messages"] = await service.get_project_output(
                    name, structured=True
                )
                report["post_run_runtime"] = await service.status()
                report["owned_children"] = owned_children(runtime)
            except Exception as error:  # noqa: BLE001 - preserve diagnostics failure
                report["diagnostic_error"] = str(error)
        raise
    finally:
        if owns_session_lifecycle:
            await cleanup_owned(
                service, name, runtime, originals, report, checkpoint, pending
            )
        else:
            if pending and name is not None:
                report["stop_result"] = await service.stop_simulation(name)
            report["sources_immutable"] = all(
                _hash(Path(p)) == digest for p, digest in originals.items()
            )
            report["cleanup_mode"] = "caller_retains_owned_instance"
            if not report["sources_immutable"]:
                report["status"] = "FAIL"
            checkpoint()
