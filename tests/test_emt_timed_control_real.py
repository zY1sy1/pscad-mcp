"""Opt-in licensed EMTDC timing proof through the public scenario entry point."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path
from uuid import uuid4

import psutil
import pytest

from pscad_mcp.acceptance.preflight_cli import _service
from pscad_mcp.acceptance.process_scope import (
    managed_acceptance_pid,
    remaining_acceptance_processes,
    require_acceptance_ownership,
)
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.process_inventory import list_pscad_processes
from pscad_mcp.hvdc.builders.mmc.engines.pwm import (
    _copy_library_support,
    library_support_files,
)
from pscad_mcp.hvdc.builders.mmc.scenarios import prepare_timed_scenario
from pscad_mcp.hvdc.builders.mmc.template_audit import discover_official_mmc_template
from pscad_mcp.hvdc.builders.mmc.timed_control import (
    plan_embedded_control,
    read_event_evidence,
    verify_embedded_control,
)
from pscad_mcp.hvdc.service import HvdcDomainService
from pscad_mcp.hvdc.timing import select_timing_mode

MASTER = Path("C:/Program Files (x86)/PSCAD46/master.pslx")


def _identity(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _write_json(path, payload):
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, default=str), encoding="utf-8"
    )


async def _close_owned_instance(service, report, *, domain=None, process_reader=None):
    """Use the existing managed connection even if status/scene cleanup failed."""
    backend = getattr(service, "_backend", None)
    if backend is None:
        backend = getattr(service, "_pending_cleanup_backend", None)
    session = getattr(backend, "session_details", {})
    runtime = {
        "session": dict(session),
        "owns_process": bool(getattr(backend, "owns_process", False)),
        "source": "cached_managed_connection",
    }
    report["cleanup_runtime"] = runtime
    errors = []
    if domain is not None:
        try:
            await domain.shutdown(timeout_s=15)
        except BaseException as error:  # noqa: BLE001 - quit still must be attempted
            errors.append({"stage": "scenario_shutdown", "message": str(error)})
    trusted = runtime["owns_process"] and managed_acceptance_pid(runtime) is not None
    if trusted:
        try:
            await service.quit_pscad(confirm=True)
        except BaseException as error:  # noqa: BLE001 - retain owned cleanup evidence
            errors.append({"stage": "owned_quit", "message": str(error)})
        try:
            for _ in range(100):
                remaining = remaining_acceptance_processes(
                    runtime, process_reader or list_pscad_processes
                )
                if not remaining:
                    break
                await asyncio.sleep(0.1)
            report["remaining_processes"] = remaining
            if remaining:
                errors.append(
                    {
                        "stage": "owned_exit",
                        "message": "The owned PSCAD PID remains alive.",
                    }
                )
        except BaseException as error:  # noqa: BLE001 - never substitute an empty inventory
            errors.append({"stage": "owned_exit", "message": str(error)})
    else:
        errors.append(
            {
                "stage": "ownership",
                "message": "No verified managed connection is available for cleanup.",
            }
        )
    report["cleanup_errors"] = errors
    if errors:
        report["cleanup_error"] = "; ".join(item["message"] for item in errors)
        report["status"] = "FAIL"


async def _minimal_run(root, *, official=False):
    service = _service(root)
    domain = HvdcDomainService(service, path_policy=service.path_policy)
    report = {
        "schema_version": 1,
        "status": "FAIL",
        "scope": "emt_timing_pwm_command" if official else "emt_timing_minimal",
        "run_id": root.name,
        "python_pid": os.getpid(),
        "interpreter": sys.executable,
        "revision": (
            await asyncio.to_thread(
                subprocess.check_output, ["git", "rev-parse", "HEAD"], text=True
            )
        ).strip(),
        "source_hashes": {"master": _identity(MASTER)},
        "run_evidence": [],
        "time_step_s": 1e-5,
        "output_step_s": 1e-5,
        "max_timing_error_s": 2e-5,
    }
    report["code_hashes"] = [
        _identity(Path(__file__).resolve().parents[1] / path)
        for path in (
            "pscad_mcp/hvdc/builders/mmc/timed_control.py",
            "pscad_mcp/hvdc/scenarios.py",
            "pscad_mcp/hvdc/timing.py",
        )
    ]
    connected = False
    try:
        await service.attach_local()
        connected = True
        runtime = await service.status()
        require_acceptance_ownership(runtime)
        report["runtime"] = runtime
        _write_json(root / "runtime.json", runtime)
        if official:
            project, library = discover_official_mmc_template()
            report["source_hashes"].update(
                project=_identity(project), library=_identity(library)
            )
            support = library_support_files(library)
            report["source_hashes"].update(
                {
                    "compiler_support:" + item["relative_path"]: {
                        "path": item["path"],
                        "sha256": item["sha256"],
                    }
                    for item in support
                }
            )
            source = root / "pwm_source.pscx"
            shutil.copy2(project, source)
            shutil.copy2(library, root / library.name)
            _copy_library_support(
                library,
                root,
                expected_hashes={item["path"]: item["sha256"] for item in support},
            )
            report["staged_inputs"] = [
                {
                    "path": str((root / item["relative_path"]).resolve()),
                    "sha256": item["sha256"],
                }
                for item in support
            ] + [
                {
                    "path": str((root / library.name).resolve()),
                    "sha256": report["source_hashes"]["library"]["sha256"],
                }
            ]
            await service.load_projects([str(root / library.name), str(source)])
            source_name = source.stem
            component = {"id": 450184592}
            definition, inactive, active, units = "master:var", -900.0, -800.0, "MW"
        else:
            created = await service.create_project(
                "case", "emt_source.pscx", str(root), confirm=True
            )
            source_name = created["name"]
            component = await service.create_canvas_component(
                source_name,
                "master:const",
                180,
                180,
                0,
                {"Name": "EMT timing command", "Value": 0},
            )
            await service.save_project(source_name, confirm=True)
            source = Path(created["filename"])
            definition, inactive, active, units = "master:const", 0, 1, "1"
        before = _identity(source)
        report["scenario_source"] = before
        if not official:
            report["source_hashes"]["project"] = before
        report["vendor_capabilities"] = await service.get_timed_control_capabilities(
            source_name
        )
        try:
            await select_timing_mode(service, source_name)
        except BackendError as error:
            report["native_rejection"] = error.to_dict()
        else:
            raise AssertionError("Unexpected unreviewed native provider on PSCAD 4.6.2")
        event = {
            "event_id": "pulse",
            "time_s": 0.02,
            "end_time_s": 0.03,
            "target": {
                "instance_path": "Main",
                "owner": str(component["id"]),
                "definition": definition,
                "parameter": "Value",
            },
            "before_value": inactive,
            "value": active,
            "after_value": inactive,
            "units": units,
        }
        plan = plan_embedded_control(
            source,
            [event],
            master_path=MASTER,
            time_step_s=1e-5,
            output_step_s=1e-5,
            duration_s=0.05,
            max_timing_error_s=2e-5,
            source_hashes=report["source_hashes"],
        )
        _write_json(root / "schedule.json", plan)
        report["schedule_sha256"] = plan["schedule_sha256"]
        profile_directory = root / ".pscad-mcp" / "hvdc-profiles"
        profile_directory.mkdir(parents=True, exist_ok=True)
        _write_json(
            profile_directory / "emt_event.json",
            {
                "profile_version": 2,
                "project_fingerprints": [],
                "required_assets": [],
                "mappings": [],
                "command_bindings": [
                    {
                        "canonical": "event_command",
                        "component": {
                            "canvas": "Main",
                            "component_id": str(component["id"]),
                            "definition": definition,
                        },
                        "parameter_name": "Value",
                        "allowed_values": [inactive, active],
                        "semantics": "active_high",
                        "read_back": True,
                    }
                ],
                "result_channels": [],
                "metric_roles": {},
                "sequences": [],
            },
        )
        scenario = {
            "name": "emt_pulse",
            "profile": "emt_event",
            "project": str(source),
            "derived_project": str(root / "emt_run.pscx"),
            "timed_control": plan,
            "events": [{**event, "target": "event_command"}],
            "analysis": {},
            "run": {"timeout_s": 180},
        }
        native_probe = root / "native_probe.pscx"
        shutil.copy2(source, native_probe)
        await service.load_projects([str(native_probe)])
        try:
            await domain.run_scenario(
                str(source),
                {
                    key: value
                    for key, value in {
                        **scenario,
                        "derived_project": str(native_probe),
                    }.items()
                    if key != "timed_control"
                },
                confirm=True,
            )
        except BackendError as error:
            assert error.code == "HVDC_TIMED_CONTROL_UNAVAILABLE"
            report["native_scenario_rejection"] = error.to_dict()
            assert domain._active_scenario_id is None
        else:
            raise AssertionError(
                "The public scenario unexpectedly accepted unverified native timing"
            )
        if official:
            scenario.update(
                time_step_s=1e-5,
                output_step_s=1e-5,
                duration_s=0.05,
                timed_control_options={
                    "master_path": str(MASTER),
                    "max_timing_error_s": 2e-5,
                },
            )
            scenario = prepare_timed_scenario(
                source,
                scenario,
                workspace_root=root,
                source_hashes=report["source_hashes"],
            )
            assert (
                scenario["timed_control"]["schedule_sha256"] == plan["schedule_sha256"]
            )
        _write_json(root / "scenario-request.json", scenario)
        started = await domain.run_scenario(str(source), scenario, confirm=True)
        await domain._scenario_tasks[started["scenario_id"]]
        for _ in range(50):
            if domain._active_scenario_id is None:
                break
            await asyncio.sleep(0.02)
        terminal = await domain.scenario_status(started["scenario_id"])
        _write_json(root / "scenario-report.json", terminal)
        report["run_evidence"].append(
            {
                "report": _identity(root / "scenario-report.json"),
                "status": terminal["status"],
            }
        )
        if terminal["status"] != "completed":
            raise AssertionError(terminal.get("error"))
        assert terminal["reservation_held"] is False
        assert _identity(source) == before
        assert all(
            _identity(item["path"]) == item for item in report["source_hashes"].values()
        )
        assert all(
            _identity(item["path"]) == item for item in report.get("staged_inputs", [])
        )
        report["source_immutable"] = True
        report["measured_events"] = terminal["timing_basis"]["measured_events"]
        report["output_evidence"] = terminal["timing_basis"]["output_evidence"]
        report["readback"] = terminal["timing_basis"]["readback"]
        files = sorted(
            {Path(path) for path in terminal["output_files"]}
            | set(root.rglob("*.inf"))
            | set(root.rglob("*.infx"))
        )
        report["outputs"] = [_identity(path) for path in files]
        _write_json(root / "output-index.json", report["outputs"])
        report["output_index"] = _identity(root / "output-index.json")
        report["status"] = "PASS"
    except BaseException as error:  # noqa: BLE001 - retain interrupted acceptance evidence
        report["error"] = (
            error.to_dict()
            if isinstance(error, BackendError)
            else {"type": type(error).__name__, "message": str(error)}
        )
        report["traceback"] = traceback.format_exc()
    finally:
        if (
            connected
            or bool(getattr(getattr(service, "_backend", None), "owns_process", False))
            or getattr(service, "_pending_cleanup_backend", None) is not None
        ):
            await _close_owned_instance(service, report, domain=domain)
        _write_json(root / "report.json", report)
    return report


async def _replay_run(parent):
    """A fresh process loads the frozen saved project; it does not regenerate it."""
    root = parent / "reload"
    root.mkdir()
    original = json.loads((parent / "report.json").read_text(encoding="utf-8"))
    assert original["status"] == "PASS"
    plan = json.loads((parent / "schedule.json").read_text(encoding="utf-8"))
    frozen = _identity(original["readback"]["project_path"])
    assert frozen["sha256"] == original["readback"]["project_sha256"]
    derived = root / Path(frozen["path"]).name
    shutil.copy2(frozen["path"], derived)
    assert _identity(derived)["sha256"] == frozen["sha256"]
    files = []
    if (parent / "intermediate.pslx").is_file():
        assert (
            _identity(parent / "intermediate.pslx")["sha256"]
            == plan["source_hashes"]["library"]["sha256"]
        )
        shutil.copy2(parent / "intermediate.pslx", root / "intermediate.pslx")
        support_hashes = {
            str((parent / key.removeprefix("compiler_support:")).resolve()): item[
                "sha256"
            ]
            for key, item in plan["source_hashes"].items()
            if key.startswith("compiler_support:")
        }
        _copy_library_support(
            parent / "intermediate.pslx", root, expected_hashes=support_hashes
        )
        files.append(str(root / "intermediate.pslx"))
    files.append(str(derived))
    service = _service(root)
    report = {
        "schema_version": 1,
        "status": "FAIL",
        "scope": "emt_saved_project_reload",
        "run_id": root.name,
        "python_pid": os.getpid(),
        "source_report": _identity(parent / "report.json"),
        "frozen_project": frozen,
        "copied_project": _identity(derived),
        "schedule_sha256": plan["schedule_sha256"],
        "revision": (
            await asyncio.to_thread(
                subprocess.check_output, ["git", "rev-parse", "HEAD"], text=True
            )
        ).strip(),
    }
    connected = False
    try:
        report["readback_before_load"] = verify_embedded_control(plan, derived)
        await service.attach_local()
        connected = True
        report["runtime"] = await service.status()
        require_acceptance_ownership(report["runtime"])
        pid = report["runtime"]["session"]["managed_pid"]
        _write_json(
            root / "ready.json",
            {"pid": pid, "created_at": psutil.Process(pid).create_time()},
        )
        await service.load_projects(files)
        await service.build_project(derived.stem)
        messages = await service.get_project_output(derived.stem, structured=True)
        report["build_messages"] = messages
        assert not [
            item
            for item in messages
            if item.get("severity", "").casefold() in {"error", "fatal"}
        ]
        await service.save_project(derived.stem, confirm=True)
        report["readback_after_save"] = verify_embedded_control(plan, derived)
        started_at = time.time()
        await service.run_project(derived.stem)
        deadline = asyncio.get_running_loop().time() + 180
        while True:
            state = await service.get_run_status(derived.stem)
            if state["status"] in {"idle", "completed", "stopped"}:
                break
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError("Saved-project replay did not terminate")
            await asyncio.sleep(0.1)
        outputs = await service.discover_output_files(
            str(derived), started_after=started_at
        )
        assert outputs
        report.update(
            await asyncio.to_thread(
                read_event_evidence, plan, derived, outputs, started_after=started_at
            )
        )
        report["outputs"] = [
            _identity(path)
            for path in sorted(
                {Path(path) for path in outputs}
                | set(root.rglob("*.inf"))
                | set(root.rglob("*.infx"))
            )
        ]
        assert _identity(frozen["path"]) == frozen
        assert all(
            _identity(item["path"]) == item
            for item in original.get("staged_inputs", [])
        )
        report["frozen_input_immutable"] = True
        report["status"] = "PASS"
    except BaseException as error:  # noqa: BLE001 - retain interrupted replay evidence
        report["error"] = (
            error.to_dict()
            if isinstance(error, BackendError)
            else {"type": type(error).__name__, "message": str(error)}
        )
        report["traceback"] = traceback.format_exc()
    finally:
        if (
            connected
            or bool(getattr(getattr(service, "_backend", None), "owns_process", False))
            or getattr(service, "_pending_cleanup_backend", None) is not None
        ):
            await _close_owned_instance(service, report)
        _write_json(root / "report.json", report)
    return report


def _verify_replay(root):
    from tests.test_concurrent_acceptance_real import _cleanup_worker

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.test_emt_timed_control_real",
            "--replay",
            str(root),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        output, _ = process.communicate(timeout=240)
        print(output, flush=True)
        assert process.returncode == 0, output
        replay = json.loads((root / "reload" / "report.json").read_text())
        assert replay["status"] == "PASS"
        assert replay["remaining_processes"] == []
        original = json.loads((root / "report.json").read_text())
        assert replay["python_pid"] != original["python_pid"]
        assert (
            replay["runtime"]["session"]["managed_pid"]
            != original["runtime"]["session"]["managed_pid"]
        )
        _write_json(
            root / "acceptance.json",
            {
                "schema_version": 1,
                "status": "PASS",
                "scope": original["scope"],
                "revision": original["revision"],
                "schedule_sha256": original["schedule_sha256"],
                "first_run": _identity(root / "report.json"),
                "reload_run": _identity(root / "reload" / "report.json"),
            },
        )
    finally:
        cleanup = _cleanup_worker(process, root / "reload")
        assert not cleanup["forced_cleanup"] and not cleanup["errors"], cleanup


@pytest.mark.skipif(
    os.getenv("PSCAD_MCP_ACCEPTANCE") != "1",
    reason="Requires explicit licensed acceptance opt-in.",
)
def test_minimal_emtdc_pulse_from_real_out():
    workspace = Path(os.environ["PSCAD_MCP_WORKSPACE"])
    assert workspace.is_absolute()
    root = workspace / f"minimal-{uuid4().hex}"
    root.mkdir(parents=True)
    print(f"EMT_TIMING_WORKSPACE={root}", flush=True)
    report = asyncio.run(_minimal_run(root))
    print(f"EMT_TIMING_REPORT={root / 'report.json'}", flush=True)
    assert report["status"] == "PASS", report.get("error", report.get("cleanup_error"))
    _verify_replay(root)


@pytest.mark.skipif(
    os.getenv("PSCAD_MCP_ACCEPTANCE") != "1"
    or os.getenv("PSCAD_MCP_MMC_ACCEPTANCE") != "1",
    reason="Requires explicit licensed and MMC acceptance opt-ins.",
)
def test_official_pwm_command_from_real_out():
    workspace = Path(os.environ["PSCAD_MCP_WORKSPACE"])
    assert workspace.is_absolute()
    root = workspace / f"pwm-{uuid4().hex}"
    root.mkdir(parents=True)
    print(f"EMT_PWM_TIMING_WORKSPACE={root}", flush=True)
    report = asyncio.run(_minimal_run(root, official=True))
    print(f"EMT_PWM_TIMING_REPORT={root / 'report.json'}", flush=True)
    assert report["status"] == "PASS", report.get("error", report.get("cleanup_error"))
    _verify_replay(root)


if __name__ == "__main__":
    if os.getenv("PSCAD_MCP_ACCEPTANCE") != "1" or sys.argv[1:2] != ["--replay"]:
        raise SystemExit(
            "Only an explicitly opted-in saved-project replay is supported."
        )
    replay_report = asyncio.run(_replay_run(Path(sys.argv[2])))
    print(
        json.dumps(
            {
                "status": replay_report["status"],
                "error": replay_report.get("error"),
                "workspace": sys.argv[2],
            }
        )
    )
    raise SystemExit(0 if replay_report["status"] == "PASS" else 1)
