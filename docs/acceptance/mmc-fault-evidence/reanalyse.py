"""Re-evaluate a completed, owned run without launching or attaching PSCAD."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from pscad_mcp.core.pscad_adapter import PscadAdapter
from pscad_mcp.hvdc.builders.mmc.fault_channels import read_fault_output_dataset
from pscad_mcp.hvdc.builders.mmc.template_native import evaluate_template_native_dc_fault
from tests.test_mmc_fault_evidence_real import _checks, _steady


async def main(root: Path):
    original_report = root / "acceptance-report.json"
    original = json.loads(original_report.read_text(encoding="utf-8"))
    if original.get("owned_process_cleaned") is not True:
        raise RuntimeError("Only completed owned runs may be re-evaluated")
    output = root / ("reanalysis-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir(exist_ok=False)
    record = {"original_report": str(original_report), "original_report_sha256": hashlib.sha256(original_report.read_bytes()).hexdigest(), "scope": "static_readback_and_physical_reanalysis", "cases": []}
    adapter = PscadAdapter(None)
    for name in ("steady", "fault"):
        contract = json.loads((root / name / "channels.json").read_text(encoding="utf-8"))
        primary = next((root / name).glob("MMC_*.gf42/*_01.out"))
        samples = await read_fault_output_dataset(adapter.read_psout, primary, contract)
        report = _steady(samples, contract) if name == "steady" else evaluate_template_native_dc_fault(samples, fault_current_limit_ka=20.0, channel_contract=contract, checks_contract=_checks())
        (output / (name + "-samples.json")).write_text(json.dumps(samples, allow_nan=False), encoding="utf-8")
        (output / (name + "-report.json")).write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
        failures = [item for item in report.get("check_results", report.get("checks", [])) if isinstance(item, dict) and (item.get("status") == "FAIL" or item.get("passed") is False)]
        record["cases"].append({"case": name, "verdict": report["verdict"], "channels": len(samples["channels"]), "failed_checks": failures})
        print(name, report["verdict"], len(samples["channels"]), "channels", flush=True)
        for item in failures:
            source = item.get("source")
            print(item.get("name", item.get("channel_id")), source.get("channel_id") if isinstance(source, dict) else item.get("channel_id"), item.get("observed", {key: item.get(key) for key in ("mean", "min", "max")}), flush=True)
    (output / "reanalysis.json").write_text(json.dumps(record, indent=2, allow_nan=False), encoding="utf-8")
    print("MMC_REANALYSIS=" + str(output), flush=True)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]).resolve()))
