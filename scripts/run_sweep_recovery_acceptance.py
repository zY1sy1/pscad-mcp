"""Opt-in licensed cancellation, cross-process restart and orphan recovery gate.

The reviewed contract contains a sweep `spec` with at least three valid scenarios
and its `review_plan_hash`. Every run creates new campaigns and durable evidence.
The crash probe deliberately exits its own worker while its second owned instance
is running. Only that vendor-reported PID and its verified work-directory children
may be terminated by the supervisor; no global PID-difference ownership is used.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psutil

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.tools.sweep_tools import _new_session
from pscad_mcp.workflows.sweep.service import SweepService
from pscad_mcp.workflows.sweep.store import (
    atomic_json,
    contained,
    file_hash,
    process_alive,
    sweep_error,
    tree_inventory,
)


def require_optin():
    if os.getenv("PSCAD_MCP_ACCEPTANCE") != "1":
        raise RuntimeError(
            "PSCAD_MCP_ACCEPTANCE=1 is required; this runner never enables it."
        )


def service_for(workspace, factory=_new_session):
    from pscad_mcp.core.connection_manager import pscad_manager

    policy = PathPolicy(str(workspace))
    pscad_manager.service.path_policy = policy
    return SweepService(policy, session_factory=factory)


async def worker(workspace, cid, directory, mode, retries):
    require_optin()
    count = 0

    class ObservedSession:
        def __init__(self, number):
            self.service = _new_session()
            self.number = number

        def __getattr__(self, name):
            return getattr(self.service, name)

        async def get_run_status(self, project):
            result = await self.service.get_run_status(project)
            if result.get("status") == "running":
                details = await self.service.status()
                pid = details["session"]["managed_pid"]
                if details.get("owns_process") is not True:
                    raise RuntimeError("The observed PSCAD instance is not owned.")
                record = {
                    "vendor_pid": pid,
                    "create_time": psutil.Process(pid).create_time(),
                    "exe": psutil.Process(pid).exe(),
                    "status": result,
                    "observed_at": time.time(),
                }
                atomic_json(directory / f"session-{self.number}-running.json", record)
                if mode == "crash" and self.number == 2:
                    os._exit(
                        86
                    )  # Intentional failure injection in this owned worker only.
            return result

        async def stop_simulation(self, project):
            result = await self.service.stop_simulation(project)
            atomic_json(
                directory / f"session-{self.number}-stop.json",
                {"project": project, "result": result, "observed_at": time.time()},
            )
            return result

    def factory():
        nonlocal count
        count += 1
        return ObservedSession(count)

    service = service_for(workspace, factory)
    try:
        if mode == "resume":
            await service.resume(cid, confirm=True, retry_scenarios=retries or None)
        else:
            await service.start(cid, confirm=True)
        await service.wait(cid, timeout=900)
        atomic_json(
            directory / "worker-result.json",
            {
                "worker_pid": os.getpid(),
                "status": service.status(cid, include_report=True),
            },
        )
    finally:
        await service.shutdown(timeout_s=30)


def attempt_work_directory(campaign_root, attempt):
    work = contained(campaign_root, attempt["path"] + "/work")
    if not work.is_dir():
        raise sweep_error(
            "SWEEP_OUTPUT_MISSING", "The owned attempt work directory is missing."
        )
    return work


def terminate_owned_instance(record, work):
    """Reject reused PIDs and foreign executables before touching a crash orphan."""
    pid = record["vendor_pid"]
    identity = {"pid": pid, "create_time": record["create_time"]}
    if not process_alive(identity):
        return {"identity": identity, "already_absent": True, "terminated": []}
    instance = psutil.Process(pid)
    if (
        abs(instance.create_time() - record["create_time"]) > 0.001
        or instance.exe().casefold() != record["exe"].casefold()
        or instance.name().casefold() != "pscad.exe"
    ):
        raise RuntimeError("Owned PSCAD identity or executable did not verify.")
    work = work.resolve(strict=True)
    children = []
    for child in instance.children(recursive=True):
        try:
            executable = Path(child.exe()).resolve(strict=True)
            if work not in executable.parents:
                raise RuntimeError(
                    "A child executable is outside the owned attempt; refusing termination."
                )
            children.append((child, child.create_time(), str(executable)))
        except psutil.NoSuchProcess:
            continue
    terminated = []
    for child, created, executable in reversed(children):
        try:
            if (
                child.create_time() != created
                or child.exe().casefold() != executable.casefold()
            ):
                raise RuntimeError("A child PID identity changed.")
            child.terminate()
            child.wait(timeout=15)
            terminated.append(
                {"pid": child.pid, "create_time": created, "exe": executable}
            )
        except psutil.NoSuchProcess:
            pass
    instance.terminate()
    instance.wait(timeout=15)
    if process_alive(identity):
        raise RuntimeError("The verified crash orphan has not exited.")
    return {
        "identity": identity,
        "terminated": [*terminated, {"pid": pid, "exe": record["exe"]}],
        "session_absent": True,
    }


def independent_out(path, selectors, maximum):
    """Acceptance calculator deliberately does not use production readers."""
    import re

    metadata = path.with_name(re.sub(r"_\d{2}$", "", path.stem) + ".inf")
    entries = []
    for line in metadata.read_text(encoding="utf-8-sig").splitlines():
        if re.match(r"\s*PGB\(\d+\)", line):
            fields = dict(re.findall(r'(\w+)="([^"]*)"', line))
            entries.append(f"{fields.get('Group', '')}/{fields['Desc']}".strip("/"))
    traces = {}
    for selector in selectors:
        column = entries.index(selector)
        part = metadata.with_name(f"{metadata.stem}_{column // 10 + 1:02d}.out")
        lines = [line.split() for line in part.read_text().splitlines() if line.strip()]
        try:
            float(lines[0][0])
        except ValueError:
            lines = lines[1:]
        rows = [[float(v) for v in line] for line in lines]
        n = min(len(rows), maximum)
        indices = [0] if n == 1 else [i * (len(rows) - 1) // (n - 1) for i in range(n)]
        traces[selector] = (
            [rows[i][0] for i in indices],
            [rows[i][column % 10 + 1] for i in indices],
        )
    return traces


def independent_integral(time_domain, voltage, current):
    # Simpson's rule is exact for the product of two linear interpolants.
    return math.fsum(
        (time_domain[i + 1] - time_domain[i])
        / 6
        * (
            voltage[i] * current[i]
            + (voltage[i] + voltage[i + 1]) * (current[i] + current[i + 1])
            + voltage[i + 1] * current[i + 1]
        )
        for i in range(len(time_domain) - 1)
    )


def run_acceptance(workspace, contract_path):
    require_optin()
    if not workspace.is_absolute() or not contract_path.is_absolute():
        raise ValueError("An absolute workspace and reviewed contract are required.")
    root = workspace / (
        "recovery-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    )
    root.mkdir(parents=True, exist_ok=False)
    checks, workers = [], []
    report = {
        "status": "FAIL",
        "workflow_accepted": False,
        "model_accepted": False,
        "scope": "legacy_sweep_cancel_cross_process_restart_and_crash_guard",
        "checks": checks,
        "report_path": str(root / "report.json"),
    }
    service = service_for(workspace)

    def check(name, value):
        checks.append({"name": name, "passed": bool(value)})
        if not value:
            raise AssertionError(name)

    def launch(cid, label, mode, retries=None):
        directory = root / label
        directory.mkdir()
        log = (directory / "worker.log").open("w", encoding="utf-8")
        env = dict(
            os.environ,
            PSCAD_MCP_WORKSPACE=str(workspace),
            PSCAD_MCP_BACKEND="legacy",
            PSCAD_MCP_VERSION="4.6.2",
            PSCAD_MCP_X64="1",
            PSCAD_MCP_LEGACY_EXISTING_POLICY="allow",
            PSCAD_MCP_ACCEPTANCE_CONCURRENT="1",
            PYTHONUTF8="1",
        )
        args = [
            sys.executable,
            "-B",
            "-m",
            "scripts.run_sweep_recovery_acceptance",
            "--workspace",
            str(workspace),
            "--campaign",
            cid,
            "--directory",
            str(directory),
            "--worker",
            mode,
        ]
        if retries:
            args += ["--retry", *retries]
        child = subprocess.Popen(
            args,
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        workers.append((child, log, cid, directory))
        return child, directory

    def wait_running(child, directory):
        marker = directory / "session-2-running.json"
        deadline = time.monotonic() + 240
        while not marker.exists():
            if child.poll() is not None:
                raise RuntimeError(
                    f"Worker exited before a running second scenario; see {directory / 'worker.log'}"
                )
            if time.monotonic() >= deadline:
                raise TimeoutError("No running second scenario was observed.")
            time.sleep(0.05)
        return json.loads(marker.read_text(encoding="utf-8"))

    def wait_exit(child, expected=0):
        check(
            f"worker-{child.pid}:exit-{expected}", child.wait(timeout=600) == expected
        )

    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        spec = contract["spec"]
        check("at_least_three_valid_scenarios", len(spec["scenarios"]) >= 3)
        plan = service.plan(spec)
        check("reviewed_plan_hash", plan["plan_hash"] == contract["review_plan_hash"])
        source = Path(plan["spec"]["source_root"])
        original = tree_inventory(source)
        master = Path("C:/Program Files (x86)/PSCAD46/master.pslx")
        master_hash = file_hash(master)
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
        ).strip()
        check(
            "clean_revision",
            not subprocess.check_output(
                ["git", "status", "--porcelain"],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
            ).strip(),
        )
        report.update(
            tested_commit=revision,
            runner_sha256=file_hash(Path(__file__)),
            request_sha256=file_hash(contract_path),
            source_hash=plan["source_hash"],
            master_sha256=master_hash,
            campaigns=[],
        )
        for label, crash in (("cancel", False), ("crash", True)):
            cid = service.create(
                spec, expected_plan_hash=plan["plan_hash"], confirm=True
            )["campaign_id"]
            report["campaigns"].append(cid)
            child, directory = launch(cid, label, "crash" if crash else "normal")
            identity_record = wait_running(child, directory)
            _, checkpoint = service.store.load(cid)
            retained = json.loads(json.dumps(checkpoint["scenarios"][0]["results"]))
            check(
                f"{label}:first_scenario_completed",
                checkpoint["scenarios"][0]["state"] == "succeeded",
            )
            if crash:
                wait_exit(child, 86)
                try:
                    asyncio.run(service.resume(cid, confirm=True))
                except BackendError as error:
                    check(
                        "crash:live_orphan_blocks_resume",
                        getattr(error, "code", None) == "SWEEP_NEEDS_REVIEW",
                    )
                else:
                    check("crash:live_orphan_blocks_resume", False)
                _, blocked = service.store.load(cid)
                owned = blocked["active_attempt"]["owned_session"]
                check(
                    "crash:vendor_pid_matches_checkpoint",
                    owned["pid"] == identity_record["vendor_pid"]
                    and owned["create_time"] == identity_record["create_time"],
                )
                atomic_json(directory / "blocked-status.json", service.status(cid))
                work = attempt_work_directory(
                    service.store.campaign_path(cid), blocked["active_attempt"]
                )
                atomic_json(
                    directory / "owned-orphan-cleanup.json",
                    terminate_owned_instance(identity_record, work),
                )
                retries = [spec["scenarios"][1]["name"]]
            else:
                asyncio.run(service.cancel(cid, confirm=True))
                wait_exit(child)
                cancelled = service.status(cid, include_report=True)
                check("cancel:campaign_cancelled", cancelled["state"] == "cancelled")
                check(
                    "cancel:second_cancelled",
                    cancelled["scenarios"][1]["state"] == "cancelled",
                )
                check(
                    "cancel:stop_was_dispatched",
                    (directory / "session-2-stop.json").is_file(),
                )
                check(
                    "cancel:parameters_restored",
                    cancelled["report"]["scenarios"][1]["cleanup"][
                        "parameters_restored"
                    ],
                )
                check(
                    "cancel:owned_instance_exited",
                    not process_alive(
                        {
                            "pid": identity_record["vendor_pid"],
                            "create_time": identity_record["create_time"],
                        }
                    ),
                )
                retries = None
                atomic_json(directory / "cancelled-status.json", cancelled)
            restart, resumed_dir = launch(cid, label + "-resume", "resume", retries)
            check(f"{label}:new_worker_process", child.pid != restart.pid)
            wait_exit(restart)
            final = service.status(cid, include_report=True)
            _, completed = service.store.load(cid)
            check(f"{label}:completed", final["state"] == "completed")
            check(
                f"{label}:all_scenarios_succeeded",
                all(s["state"] == "succeeded" for s in final["scenarios"]),
            )
            check(
                f"{label}:first_result_hash_preserved",
                completed["scenarios"][0]["results"] == retained,
            )
            check(
                f"{label}:attempt_counts",
                [s["attempt_count"] for s in final["scenarios"][:3]] == [1, 2, 1],
            )
            check(f"{label}:no_active_attempt", final["active_attempt"] is None)
            for scenario in final["report"]["scenarios"]:
                check(
                    f"{label}:{scenario['name']}:cleanup",
                    scenario["cleanup"]["parameters_restored"]
                    and scenario["cleanup"]["session_absent"]
                    and not process_alive(scenario["owned_session"]),
                )
            atomic_json(resumed_dir / "final-status.json", final)
            output = spec["outputs"][0]
            voltage, current = output["channels"][:2]
            definitions = [
                {
                    "name": "energy",
                    "kind": "energy",
                    "output_path": output["path"],
                    "voltage_channel": voltage,
                    "current_channel": current,
                    "voltage_units": "kV",
                    "current_units": "kA",
                    "mode": "signed",
                    "window": contract["metric_window"],
                },
                {
                    "name": "i2t",
                    "kind": "i2t",
                    "output_path": output["path"],
                    "current_channel": current,
                    "current_units": "kA",
                    "window": contract["metric_window"],
                },
                {
                    "name": "peak",
                    "kind": "peak_abs",
                    "output_path": output["path"],
                    "channel": voltage,
                    "window": contract["metric_window"],
                },
                {
                    "name": "event",
                    "kind": "threshold_crossing",
                    "output_path": output["path"],
                    "channel": voltage,
                    "threshold": 1,
                    "operator": ">=",
                    "window": contract["metric_window"],
                },
            ]
            analysis = service.analyze(
                cid,
                metrics=definitions,
                objective={"metric": "energy", "direction": "maximize"},
                constraints=[{"metric": "i2t", "operator": ">=", "value": 0}],
            )
            for scenario in analysis["report"]["scenarios"]:
                artifact = next(
                    a
                    for a in scenario["artifacts"]
                    if a["relative_path"].endswith("/outputs/" + output["path"])
                )
                raw = independent_out(
                    Path(artifact["path"]),
                    (voltage, current),
                    plan["spec"]["max_samples"],
                )
                domain, v = raw[voltage]
                check(
                    f"{label}:{scenario['name']}:matching_time_domain",
                    domain == raw[current][0],
                )
                start, end = contract["metric_window"]
                # Reviewed window endpoints must be real recorded samples for this independent gate.
                first, last = domain.index(start), domain.index(end)
                t, u, i = (
                    domain[first : last + 1],
                    v[first : last + 1],
                    raw[current][1][first : last + 1],
                )
                expected_energy = independent_integral(t, u, i) * 1e6
                expected_i2t = independent_integral(t, i, i) * 1e6
                observed = {m["name"]: m["value"] for m in scenario["metrics"]}
                check(
                    f"{label}:{scenario['name']}:energy",
                    math.isclose(
                        observed["energy"], expected_energy, rel_tol=1e-12, abs_tol=1e-6
                    ),
                )
                check(
                    f"{label}:{scenario['name']}:i2t",
                    math.isclose(
                        observed["i2t"], expected_i2t, rel_tol=1e-12, abs_tol=1e-6
                    ),
                )
                check(
                    f"{label}:{scenario['name']}:peak",
                    observed["peak"] == max(map(abs, u)),
                )
            expected_best = max(
                analysis["report"]["scenarios"],
                key=lambda s: next(
                    m["value"] for m in s["metrics"] if m["name"] == "energy"
                ),
            )["name"]
            check(f"{label}:metric_ranking", analysis["best"]["name"] == expected_best)
            atomic_json(resumed_dir / "physical-analysis.json", analysis)
        check("source_immutable", tree_inventory(source) == original)
        check("master_immutable", file_hash(master) == master_hash)
        report["status"] = "PASS"
        report["workflow_accepted"] = True
    except Exception as error:  # noqa: BLE001 - preserve every failed acceptance attempt.
        report["error"] = {
            "type": type(error).__name__,
            "code": getattr(error, "code", None),
            "message": str(error),
        }
    finally:
        for child, log, cid, directory in workers:
            if child.poll() is None:
                asyncio.run(service.cancel(cid, confirm=True))
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    report.setdefault("cleanup_errors", []).append(
                        {
                            "worker_pid": child.pid,
                            "campaign_id": cid,
                            "message": "Owned worker has not completed cleanup; do not claim PASS.",
                        }
                    )
                    report["status"], report["workflow_accepted"] = "FAIL", False
            log.close()
            # A deliberately crashed worker can fail before the planned cleanup.
            # Recover only a PID that its own vendor observation also identifies.
            if child.poll() is not None:
                try:
                    _, final_checkpoint = service.store.load(cid)
                    attempt = final_checkpoint.get("active_attempt")
                    identity = (attempt or {}).get("owned_session")
                    if identity and process_alive(identity):
                        markers = list(directory.glob("session-*-running.json"))
                        records = [
                            json.loads(p.read_text(encoding="utf-8")) for p in markers
                        ]
                        record = next(
                            (
                                r
                                for r in records
                                if r["vendor_pid"] == identity["pid"]
                                and r["create_time"] == identity["create_time"]
                            ),
                            None,
                        )
                        if record is None:
                            raise RuntimeError(
                                "No vendor observation verifies the remaining owned instance."
                            )
                        work = attempt_work_directory(
                            service.store.campaign_path(cid), attempt
                        )
                        atomic_json(
                            directory / "failure-orphan-cleanup.json",
                            terminate_owned_instance(record, work),
                        )
                except Exception as error:  # noqa: BLE001 - report incomplete owned cleanup.
                    report.setdefault("cleanup_errors", []).append(
                        {"campaign_id": cid, "message": str(error)}
                    )
                    report["status"], report["workflow_accepted"] = "FAIL", False
        report["evidence"] = [
            {"path": str(p.relative_to(root)), "sha256": file_hash(p)}
            for p in sorted(root.rglob("*"))
            if p.is_file() and p.name != "report.json"
        ]
        atomic_json(root / "report.json", report)
        print(
            "SWEEP_RECOVERY_ACCEPTANCE_REPORT=" + str(root / "report.json"), flush=True
        )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--worker", choices=("normal", "crash", "resume"))
    parser.add_argument("--campaign")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--retry", nargs="*")
    args = parser.parse_args()
    if args.worker:
        if not args.campaign or not args.directory:
            parser.error("Workers need --campaign and --directory.")
        asyncio.run(
            worker(
                args.workspace, args.campaign, args.directory, args.worker, args.retry
            )
        )
        return 0
    if args.spec is None:
        parser.error("An absolute reviewed --spec is required.")
    return 0 if run_acceptance(args.workspace, args.spec)["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
