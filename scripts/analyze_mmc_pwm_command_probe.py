"""Evaluate frozen routed-PWM traces with exact compiled channel identities."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pscad_mcp.hvdc.builders.mmc import timed_control
from pscad_mcp.hvdc.builders.mmc.fault_channels import (
    _metadata,
    finalize_fault_instrumentation,
    reachable_instances,
    read_fault_output_dataset,
)
from pscad_mcp.hvdc.builders.mmc.pwm_channels import compose_pwm_scenario_contract
from pscad_mcp.hvdc.builders.mmc.pwm_physical import evaluate_routed_pwm_samples


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


async def analyze(args):
    report = json.loads((args.run / "report.json").read_text())
    if report["status"] != "PASS" or report.get("remaining_owned_processes"):
        raise RuntimeError("Only completed, cleaned-up probes can be evaluated")
    for path, expected in report["original_inputs"].items():
        if digest(path) != expected:
            raise RuntimeError("A recorded source input has changed")
    (project,) = args.run.glob("*.pscx")
    if digest(project) != report["saved_project_sha256"]:
        raise RuntimeError("The saved measured model has changed")
    scenario = json.loads(args.scenario.read_text())
    contract = json.loads(args.contract.read_text())
    if scenario["pwm_initialization"]["source_sha256"] == contract[
        "instrumented_project_sha256"
    ] and any(b["role"] == "pg_fault_state" for b in contract["diagnostic_channels"]):
        contract = compose_pwm_scenario_contract(contract, scenario, project.stem)
    original_namespace = ET.parse(contract["project_path"]).getroot().get("name")
    for component in contract["readback_components"]:
        definition = component["definition"]
        if definition.startswith(original_namespace + ":"):
            component["definition"] = (
                project.stem + definition[len(original_namespace) :]
            )
    for binding in contract["channels"] + contract["diagnostic_channels"]:
        definition = binding["signal_source"]["definition"]
        if definition.startswith(original_namespace + ":"):
            binding["signal_source"]["definition"] = (
                project.stem + definition[len(original_namespace) :]
            )
    contract["namespace_rebinding"] = {
        "before": original_namespace,
        "after": project.stem,
        "source": "timed_control_render",
    }
    contract["project_path"] = str(project)
    contract["reachable_instances"] = reachable_instances(
        timed_control._render(scenario["timed_control"], project.stem)
    )
    contract = finalize_fault_instrumentation(project, contract)
    outputs = sorted(Path(p) for p in report["output_files"])
    for path in outputs:
        if digest(path) != report["output_files"][str(path)]:
            raise RuntimeError("A recorded simulation output has changed")
    primary = outputs[0]
    base = primary.stem.rsplit("_", 1)[0]
    metadata = _metadata(primary.parent / f"{base}.inf")
    wanted = {
        b["channel_id"] for b in contract["channels"] + contract["diagnostic_channels"]
    }
    cache, traces = {}, []
    for item in metadata:
        if item["description"] not in wanted:
            continue
        part = (item["call_id"] - 1) // 10 + 1
        column = (item["call_id"] - 1) % 10 + 1
        if part not in cache:
            matrix = np.loadtxt(primary.parent / f"{base}_{part:02d}.out", ndmin=2)
            cache[part] = (matrix, matrix[:, 0].tolist())
        matrix, domain = cache[part]
        traces.append(
            {
                "description": item["description"],
                "group": item["group"],
                "units": item["units"],
                "domain": domain,
                "values": matrix[:, column].tolist(),
            }
        )

    async def reader(path, **kwargs):
        return {"channels": traces}

    samples = await read_fault_output_dataset(
        reader, primary, contract, started_after=report["run_started_after"]
    )
    if samples["missing_selectors"]:
        raise RuntimeError(str(samples["missing_selectors"]))
    physical = evaluate_routed_pwm_samples(samples, contract, scenario)
    bindings = {
        b["channel_id"]: b
        for b in contract["channels"] + contract["diagnostic_channels"]
    }
    windows = [
        (0, 0.2),
        (1.8, 2.0),
        (scenario["duration_s"] - 0.2, scenario["duration_s"]),
    ]
    windows += [
        (e["time_s"], min(e["time_s"] + 0.1, scenario["duration_s"]))
        for e in scenario["events"]
    ]
    diagnosis = []
    for channel in samples["channels"]:
        binding = bindings[channel["channel_id"]]
        if binding["role"] not in {
            "v_dc",
            "p_active",
            "i_dc_station",
            "i_dc_fault",
            "fault_active",
            "v_cap",
            "i_arm",
            "blocking_state",
            "modulation_request",
            "recovery_enable",
            "v_dc_converter",
            "controller_current_magnitude",
        }:
            continue
        t = np.asarray(channel["domain"])
        v = np.asarray(channel["values"])
        stats = []
        for start, end in windows:
            values = v[(t >= start) & (t <= end)]
            if values.size:
                stats.append(
                    {
                        "window_s": [start, end],
                        "min": float(values.min()),
                        "max": float(values.max()),
                        "mean": float(values.mean()),
                        "rms": float(np.sqrt(np.mean(values**2))),
                    }
                )
        diagnosis.append(
            {
                "channel_id": channel["channel_id"],
                "role": binding["role"],
                "scope": binding["model_scope"],
                "units": binding["units"],
                "windows": stats,
            }
        )
    args.destination.mkdir(parents=True, exist_ok=False)
    documents = {
        "finalized-channels.json": contract,
        "physical-checks.json": physical,
        "physical-diagnosis.json": diagnosis,
        "evidence-identity.json": {
            "probe_report": str(args.run / "report.json"),
            "probe_report_sha256": digest(args.run / "report.json"),
            "producer_sha256": digest(__file__),
            "evaluator_sha256": digest(
                ROOT / "pscad_mcp/hvdc/builders/mmc/pwm_physical.py"
            ),
            "scenario_sha256": digest(args.scenario),
            "channel_contract_sha256": digest(args.contract),
            "dataset": samples["identity"],
            "project_readback": samples["project_readback"],
        },
    }
    for filename, data in documents.items():
        (args.destination / filename).write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "scenario": scenario["name"],
                "status": physical["status"],
                "checks": len(physical["checks"]),
                "failures": [c for c in physical["checks"] if not c["passed"]],
                "destination": str(args.destination),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    asyncio.run(analyze(parser.parse_args()))
