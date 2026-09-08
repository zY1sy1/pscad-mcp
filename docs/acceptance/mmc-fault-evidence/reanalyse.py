"""Re-evaluate a completed, owned run without launching or attaching PSCAD."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.pscad_adapter import PscadAdapter
from pscad_mcp.hvdc.builders.mmc.fault_channels import (
    read_fault_output_dataset,
    verify_output_dataset,
)
from pscad_mcp.hvdc.builders.mmc.template_native import (
    evaluate_template_native_dc_fault,
)
from tests.test_mmc_fault_evidence_real import _steady


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_frozen_case(record):
    for field, digest_field in (("channel_contract_path", "channel_contract_sha256"), ("output_index_path", "output_index_sha256")):
        path = Path(record.get(field, ""))
        if not path.is_file() or path.is_symlink() or not record.get(digest_field) or sha256(path) != record[digest_field]:
            raise BackendError("MMC_OUTPUT_IDENTITY_CHANGED", "The original run has no matching frozen contract or output index; historical unfrozen runs remain diagnostic only.", "hvdc", "reanalyse_mmc_fault", {"field": field, "path": str(path)})
    contract = json.loads(Path(record["channel_contract_path"]).read_text(encoding="utf-8"))
    identity = json.loads(Path(record["output_index_path"]).read_text(encoding="utf-8"))
    verify_output_dataset(identity)
    if not isinstance(contract.get("required_checks"), dict):
        raise BackendError("MMC_OUTPUT_IDENTITY_CHANGED", "The original physical checks contract is missing.", "hvdc", "reanalyse_mmc_fault", {})
    return contract, identity


async def main(root: Path, *, checks_path: Path | None = None, reason: str | None = None):
    original_report = root / "acceptance-report.json"
    original = json.loads(original_report.read_text(encoding="utf-8"))
    if original.get("owned_process_cleaned") is not True:
        raise RuntimeError("Only completed owned runs may be re-evaluated")
    output = root / ("reanalysis-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir(exist_ok=False)
    repository = Path(__file__).parents[3]
    revision = await asyncio.to_thread(subprocess.run, ["git", "rev-parse", "HEAD"], cwd=repository, capture_output=True, text=True, check=True)
    record = {"original_report": str(original_report), "original_report_sha256": sha256(original_report), "scope": "static_readback_and_physical_reanalysis", "cases": [], "code_identity": {"commit": revision.stdout.strip(), "files": {str(path.relative_to(repository)): sha256(path) for path in (Path(__file__), repository / "pscad_mcp/hvdc/builders/mmc/template_native.py", repository / "pscad_mcp/hvdc/builders/mmc/fault_channels.py")}}}
    adapter = PscadAdapter(None)
    for case in original["cases"]:
        name = case["case"]
        try:
            contract, identity = load_frozen_case(case)
        except BackendError as error:
            record["cases"].append({"case": name, "verdict": "INCOMPLETE_ANALYSIS", "eligible_for_acceptance": False, "error": error.to_dict()})
            continue
        checks = contract["required_checks"]
        checks_change = None
        if checks_path is not None:
            if not reason or not reason.strip():
                raise ValueError("Changing an acceptance contract requires an explicit reason")
            replacement = json.loads(checks_path.read_text(encoding="utf-8"))
            checks_change = {"old_sha256": json_hash(checks), "new_sha256": json_hash(replacement), "new_file": str(checks_path), "new_file_sha256": sha256(checks_path), "reason": reason}
            checks = replacement
        samples = await read_fault_output_dataset(adapter.read_psout, identity["primary"], contract, started_after=identity.get("started_after"))
        if samples["identity"] != identity:
            raise RuntimeError("The current complete dataset differs from its original freeze")
        report = _steady(samples, contract, checks) if name == "steady" else evaluate_template_native_dc_fault(samples, fault_current_limit_ka=checks["fault_current_limit_ka"], channel_contract=contract, checks_contract=checks)
        (output / (name + "-samples.json")).write_text(json.dumps(samples, allow_nan=False), encoding="utf-8")
        (output / (name + "-report.json")).write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
        failures = [item for item in report.get("check_results", report.get("checks", [])) if isinstance(item, dict) and (item.get("status") == "FAIL" or item.get("passed") is False)]
        record["cases"].append({"case": name, "verdict": report["verdict"], "channels": len(samples["channels"]), "failed_checks": failures, "checks_contract_sha256": json_hash(checks), "checks_contract_change": checks_change})
        print(name, report["verdict"], len(samples["channels"]), "channels", flush=True)
        for item in failures:
            source = item.get("source")
            print(item.get("name", item.get("channel_id")), source.get("channel_id") if isinstance(source, dict) else item.get("channel_id"), item.get("observed", {key: item.get(key) for key in ("mean", "min", "max")}), flush=True)
    (output / "reanalysis.json").write_text(json.dumps(record, indent=2, allow_nan=False), encoding="utf-8")
    print("MMC_REANALYSIS=" + str(output), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--checks-contract", type=Path)
    parser.add_argument("--reason")
    args = parser.parse_args(sys.argv[1:])
    asyncio.run(main(args.root.resolve(), checks_path=args.checks_contract, reason=args.reason))
