"""Read frozen MMC sorting evidence; never issue a physical acceptance verdict."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from pscad_mcp.hvdc.builders.mmc.fault_channels import verify_output_dataset


def frozen(path, digest):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError(f"Frozen evidence changed: {path}")
    return json.loads(raw)


def diagnose(root: Path):
    report_path = root / "acceptance-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("owned_process_cleaned") is not True:
        raise ValueError("The diagnostic requires a completed owned run")
    case = next(item for item in report["cases"] if item["case"] == "steady")
    contract = frozen(case["channel_contract_path"], case["channel_contract_sha256"])
    identity = frozen(case["output_index_path"], case["output_index_sha256"])
    verify_output_dataset(identity)
    samples = frozen(case["samples_path"], case["samples_sha256"])
    if samples["identity"] != identity:
        raise ValueError("Samples do not refer to the frozen output dataset")
    channels = {item["channel_id"]: item for item in samples["channels"]}
    if len(channels) != len(samples["channels"]):
        raise ValueError("A diagnostic channel is duplicated")
    time = np.asarray(samples["channels"][0]["domain"])
    if any(item["domain"] != samples["channels"][0]["domain"] for item in channels.values()):
        raise ValueError("Diagnostic time domains differ")
    lo, hi = contract["required_checks"]["recovery_window_s"]
    window = (time >= lo) & (time < hi)
    rows = []
    ordering = []
    for station in ("T1", "T2"):
        for phase in "ABC":
            for arm in ("upper", "lower"):
                prefix = f"MFE_{station}_{phase}_{arm}_"

                def trace(role, prefix=prefix):
                    return np.asarray(channels[prefix + role]["values"])

                count = np.abs(trace("sort_requested_count"))
                applicable = trace("sort_boundary_applicable") == 1
                valid = trace("sort_index_invalid") == 0
                enabled = trace("sort_enable") != 0
                suffix = trace("modulation_request") * trace("i_arm") < 0
                scope = f"{station}/{phase}/{arm}"
                refresh_window = window & enabled
                inversion = trace("sort_index_inversions")[refresh_window]
                ordering.append({"scope": scope, "enabled_sample_count": int(refresh_window.sum()), "invalid_index_samples": int(np.sum(window & ~valid)), "enabled_inversion_maximum": float(np.max(inversion)) if inversion.size else None})
                for refreshed in (True, False):
                    for side in ("prefix", "suffix"):
                        for subset in ("below_half", "at_least_half"):
                            mask = window & applicable & valid & (enabled == refreshed)
                            mask &= suffix if side == "suffix" else ~suffix
                            mask &= (count < 38) if subset == "below_half" else (count >= 38)
                            gap = trace("sort_" + side + "_gap")[mask]
                            rows.append({"scope": scope, "refreshed": refreshed, "consumed_side": side, "subset": subset, "sample_count": int(mask.sum()), "wrong_set_count": int(np.sum(gap > 1e-9)), "maximum_gap_kv": float(np.max(gap)) if gap.size else None})
    return {"scope": "static_sorting_diagnostic_only", "producer_revision": report["commit"], "original_report": str(report_path), "original_report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(), "samples_sha256": case["samples_sha256"], "window_s_half_open": [lo, hi], "gap_tolerance_kv": 1e-9, "not_a_physical_acceptance_verdict": True, "ordering": ordering, "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = diagnose(args.root.resolve())
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
    for station in ("T1", "T2"):
        for side in ("prefix", "suffix"):
            for subset in ("below_half", "at_least_half"):
                rows = [row for row in result["rows"] if row["scope"].startswith(station + "/") and row["refreshed"] and row["consumed_side"] == side and row["subset"] == subset]
                print(station, side, subset, "wrong / samples", sum(row["wrong_set_count"] for row in rows), "/", sum(row["sample_count"] for row in rows), "max gap kV", max((row["maximum_gap_kv"] for row in rows if row["maximum_gap_kv"] is not None), default=None))
