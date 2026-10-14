"""Licensed compile/run probe for a prepared PWM command circuit.

This runner cannot certify a converter: its report always records
model_accepted=false. Complete scenario and physical evidence are separate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.executor import robust_executor
from pscad_mcp.hvdc.builders.mmc.pwm_runtime import cleanup_owned, run, write_report

__all__ = ["cleanup_owned", "main"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--scenario", type=Path)
    parser.add_argument("--case-name", default="H_MMC_Mono_DC")
    parser.add_argument("--duration", type=float, default=0.8)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    args = parser.parse_args()
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,29}", args.case_name) is None:
        parser.error(
            "--case-name must be a valid EMTDC namespace of at most 30 characters"
        )
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
        write_report(report_path, report)

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
