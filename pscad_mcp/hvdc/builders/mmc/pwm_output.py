"""Bounded local reads of complete PWM evidence without repeated OUT parsing."""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections import defaultdict
from pathlib import Path

from .fault_channels import (
    _metadata,
    finalize_fault_instrumentation,
    read_fault_output_dataset,
)
from .pwm_channels import compose_pwm_scenario_contract


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


async def read_routed_pwm_run(report, project, scenario, contract):
    if (report["status"] != "PASS" or report.get("stage") != "finished" or report.get("sources_immutable") is not True
            or report.get("remaining_owned_processes") or (report.get("cleanup_mode") != "caller_retains_owned_instance"
            and report.get("remaining_owned_processes") != [])):
        raise RuntimeError("Complete, cleaned-up PWM runs are required")
    project = Path(project)
    if digest(project) != report["saved_project_sha256"]:
        raise RuntimeError("The measured saved model changed")
    for path, expected in report["original_inputs"].items():
        if digest(path) != expected:
            raise RuntimeError("An immutable PWM source changed")
    contract = compose_pwm_scenario_contract(contract, scenario, project.stem)
    contract["project_path"] = str(project)
    contract = finalize_fault_instrumentation(project, contract)
    outputs = sorted(Path(p) for p in report["output_files"])
    for path in outputs:
        if digest(path) != report["output_files"][str(path)]:
            raise RuntimeError("A frozen PWM output changed")
    primary = outputs[0]
    base = primary.stem.rsplit("_", 1)[0]
    metadata = _metadata(primary.parent / (base + ".inf"))
    wanted = {
        b["selector"]["description"]
        for b in contract["channels"] + contract["diagnostic_channels"]
    }

    def load():
        parts = defaultdict(list)
        for item in metadata:
            if item["description"] in wanted:
                parts[(item["call_id"] - 1) // 10 + 1].append(item)
        traces = []
        for number, items in sorted(parts.items()):
            domain = []
            values = {item["call_id"]: [] for item in items}
            with (primary.parent / f"{base}_{number:02d}.out").open() as stream:
                for line in stream:
                    row = [
                        float(v.replace("D", "E").replace("d", "e"))
                        for v in line.split()
                    ]
                    if not row:
                        continue
                    if not all(math.isfinite(v) for v in row):
                        raise RuntimeError("The PWM output contains a nonfinite value")
                    domain.append(row[0])
                    for item in items:
                        values[item["call_id"]].append(
                            row[(item["call_id"] - 1) % 10 + 1]
                        )
            for item in items:
                traces.append(
                    {
                        "description": item["description"],
                        "group": item["group"],
                        "units": item["units"],
                        "call_id": item["call_id"],
                        "domain": domain,
                        "values": values[item["call_id"]],
                    }
                )
        return traces

    traces = await asyncio.to_thread(load)

    async def reader(path, **kwargs):
        return {"channels": traces}

    samples = await read_fault_output_dataset(
        reader, primary, contract, started_after=report["run_started_after"]
    )
    if samples["missing_selectors"]:
        raise RuntimeError(str(samples["missing_selectors"]))
    return samples, contract
