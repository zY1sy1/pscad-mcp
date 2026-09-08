"""Opt-in proof of two independent licensed PSCAD acceptance lifecycles."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import psutil
import pytest


def _cleanup_worker(process, workspace):
    records = []
    ready = workspace / "ready.json"
    if ready.is_file():
        records.append(json.loads(ready.read_text()))
    if process.poll() is None:
        try:
            for child in psutil.Process(process.pid).children(recursive=True):
                if "pscad" in child.name().lower():
                    records.append({"pid": child.pid, "created_at": child.create_time()})
        except psutil.NoSuchProcess:
            pass
    result = {"forced_cleanup": False, "errors": [], "processes": records}
    try:
        if process.poll() is None:
            try:
                process.communicate(timeout=110)
            except subprocess.TimeoutExpired:
                result["forced_cleanup"] = True
        for record in records:
            try:
                owned = psutil.Process(record["pid"])
                if owned.create_time() != record["created_at"]:
                    continue
                result["forced_cleanup"] = True
                owned.terminate()
                try:
                    owned.wait(timeout=5)
                except psutil.TimeoutExpired:
                    owned.kill()
                    owned.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass
            except psutil.Error as error:
                result["errors"].append(str(error))
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=10)
    finally:
        (workspace / "supervisor-cleanup.json").write_text(json.dumps(result), encoding="utf-8")
    return result


@pytest.mark.skipif(
    os.getenv("PSCAD_MCP_ACCEPTANCE") != "1"
    or os.getenv("PSCAD_MCP_CONCURRENT_ACCEPTANCE_TEST") != "1",
    reason="Requires explicit licensed concurrent-acceptance opt-ins.",
)
def test_two_licensed_preflights_overlap_and_cleanup_independently():
    root = Path(os.environ["PSCAD_MCP_WORKSPACE"]).resolve() / f"concurrent-{uuid.uuid4().hex}"
    workers = [root / "worker-1", root / "worker-2"]
    for worker in workers:
        worker.mkdir(parents=True)
    environment = dict(os.environ, PSCAD_MCP_ACCEPTANCE_CONCURRENT="1")
    processes = []
    print(f"CONCURRENT_ACCEPTANCE_WORKSPACE={root}", flush=True)
    try:
        for index, worker in enumerate(workers):
            processes.append(subprocess.Popen(
                [sys.executable, "-m", "tests.concurrent_acceptance_worker",
                 "--workspace", str(worker), "--peer", str(workers[1 - index]),
                 "--rank", str(index + 1)],
                cwd=Path(__file__).resolve().parents[1], env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            ))
            if index == 0:
                deadline = time.monotonic() + 90
                while not (worker / "ready.json").is_file():
                    if processes[0].poll() is not None:
                        output, _ = processes[0].communicate()
                        raise AssertionError(output)
                    if time.monotonic() >= deadline:
                        raise TimeoutError("First PSCAD instance did not become ready.")
                    time.sleep(0.1)
        for process in processes:
            output, _ = process.communicate(timeout=180)
            print(output, flush=True)
            assert process.returncode == 0, output
        reports = [json.loads((worker / "report.json").read_text()) for worker in workers]
        pids = [report["runtime"]["session"]["managed_pid"] for report in reports]
        assert len(set(pids)) == 2
        assert reports[0]["revision"] == reports[1]["revision"]
        assert pids[0] in {record["pid"] for record in reports[1]["processes_before"]}
        for report in reports:
            assert report["status"] == "PASS"
            assert report["remaining_processes"] == []
            assert report["runtime"]["concurrent_evidence"]["overlap_confirmed"] is True
        assert reports[1]["runtime"]["concurrent_evidence"]["own_alive_after_peer_quit"] is True
    finally:
        for worker in workers:
            (worker / "cancel").touch()
        cleanup_results = [_cleanup_worker(process, worker) for process, worker in zip(processes, workers)]
        assert all(not result["forced_cleanup"] and not result["errors"] for result in cleanup_results), cleanup_results
