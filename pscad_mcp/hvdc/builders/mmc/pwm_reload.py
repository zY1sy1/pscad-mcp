"""Separate-process, owned PSCAD reload of a frozen PWM delivery."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

from ....core.executor import robust_executor
from .pwm_output import digest, read_routed_pwm_run
from .pwm_physical import evaluate_routed_pwm_samples
from .pwm_runtime import run, write_report


async def execute(job):
    if digest(job["source"]) != job["source_sha256"]:
        raise RuntimeError("The delivered PWM input changed before independent reload")
    directory = Path(job["workspace"])
    directory.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": 1,
        "status": "FAIL",
        "stage": "prepare",
        "model_accepted": False,
        "scope": "mmc.detailed_pwm.independent_reload",
        "parent_managed_pid": job["parent_managed_pid"],
    }

    def checkpoint():
        write_report(directory / "report.json", report)

    args = SimpleNamespace(
        source=Path(job["source"]),
        library=Path(job["library"]),
        master=Path(job["master"]),
        workspace=directory,
        case_name=job["case_name"],
        duration=job["scenario"]["duration_s"],
        scenario=None,
        simulate=True,
        timeout=900,
        startup_timeout=30,
    )
    try:
        await run(args, report, checkpoint)
        report["stage"] = "finished"
        checkpoint()
        if report["runtime"]["session"]["managed_pid"] == job["parent_managed_pid"]:
            raise RuntimeError(
                "The reload did not use an independent owned PSCAD process"
            )
        samples, contract = await read_routed_pwm_run(
            report,
            directory / (args.case_name + ".pscx"),
            job["scenario"],
            job["channel_contract"],
        )
        physical = evaluate_routed_pwm_samples(samples, contract, job["scenario"])
        (directory / "physical.json").write_text(
            json.dumps(
                {
                    "physical": physical,
                    "channel_contract": contract,
                    "dataset": samples["identity"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if physical["status"] != "PASS":
            raise RuntimeError(
                "The independent reload did not satisfy physical criteria"
            )
        return 0
    except Exception as error:  # noqa: BLE001 - preserve the complete isolated attempt
        report["status"] = "FAIL"
        report["stage"] = "finished"
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        checkpoint()
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    args = parser.parse_args()
    for name in ("PSCAD_MCP_ACCEPTANCE", "PSCAD_MCP_MMC_ACCEPTANCE"):
        if os.getenv(name) != "1":
            raise SystemExit(name + "=1 is required")
    try:
        return asyncio.run(execute(json.loads(args.job.read_text())))
    finally:
        robust_executor.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
