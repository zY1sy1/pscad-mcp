"""One isolated worker used by the opt-in concurrent PSCAD lifecycle test."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time

import psutil

from pscad_mcp.acceptance.preflight import (
    run_licensed_session_preflight, write_preflight_report,
)
from pscad_mcp.acceptance.preflight_cli import _service


async def run_worker(workspace: Path, peer: Path, rank: int) -> dict:
    service = _service(workspace)

    async def wait_for(path: Path) -> dict:
        deadline = time.monotonic() + 90
        while not path.is_file():
            if (workspace / "cancel").exists():
                raise RuntimeError("Concurrent acceptance cancelled by supervisor.")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for {path.name} from peer.")
            await asyncio.sleep(0.1)
        return json.loads(path.read_text(encoding="utf-8"))

    class CoordinatedService:
        async def attach_local(self):
            return await service.attach_local()

        async def status(self):
            status = await service.status()
            pid = status["session"]["managed_pid"]
            if type(pid) is not int or pid <= 0:
                raise RuntimeError("Owned PSCAD PID unavailable.")
            write_preflight_report(workspace / "ready.json", {
                "pid": pid, "created_at": psutil.Process(pid).create_time(),
            })
            peer_record = await wait_for(peer / "ready.json")
            if pid == peer_record["pid"] or not psutil.pid_exists(peer_record["pid"]):
                raise RuntimeError("Two distinct live PSCAD instances were not observed.")
            write_preflight_report(workspace / "overlap.json", {
                "own_pid": pid, "peer_pid": peer_record["pid"],
                "both_alive": True, "observed_at": time.time(),
            })
            await wait_for(peer / "overlap.json")
            if rank == 2:
                peer_report = await wait_for(peer / "report.json")
                if peer_report["status"] != "PASS":
                    raise RuntimeError("Peer acceptance failed.")
                if psutil.pid_exists(peer_record["pid"]):
                    raise RuntimeError("Peer report passed before its PSCAD exited.")
            status = await service.status()
            status["concurrent_evidence"] = {
                "peer_pid": peer_record["pid"],
                "overlap_confirmed": True,
                "own_alive_after_peer_quit": status["alive"] if rank == 2 else None,
            }
            return status

        async def quit_pscad(self, *, confirm):
            return await service.quit_pscad(confirm=confirm)

    return await run_licensed_session_preflight(
        CoordinatedService(), workspace_root=workspace,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--peer", required=True, type=Path)
    parser.add_argument("--rank", required=True, type=int, choices=(1, 2))
    args = parser.parse_args()
    if os.getenv("PSCAD_MCP_ACCEPTANCE") != "1":
        raise SystemExit("PSCAD_MCP_ACCEPTANCE=1 is required.")
    if os.getenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT") != "1":
        raise SystemExit("PSCAD_MCP_ACCEPTANCE_CONCURRENT=1 is required.")
    args.workspace.mkdir(parents=True, exist_ok=True)
    try:
        report = asyncio.run(run_worker(args.workspace, args.peer, args.rank))
    except Exception as error:
        report = {"status": "FAIL", "error": str(error)}
    report["revision"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1], text=True,
    ).strip()
    write_preflight_report(args.workspace / "report.json", report)
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
