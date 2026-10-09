"""Licensed generic-builder acceptance against the official voltage divider."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pscad_mcp.acceptance.process_scope import (  # noqa: E402
    acceptance_launch_policy, remaining_acceptance_processes,
    require_acceptance_ownership,
)
from pscad_mcp.builders.blueprint.service import BlueprintBuilderService  # noqa: E402
from pscad_mcp.core.backend.legacy import LegacyBackend  # noqa: E402
from pscad_mcp.core.executor import robust_executor  # noqa: E402
from pscad_mcp.core.path_policy import PathPolicy  # noqa: E402
from pscad_mcp.core.process_inventory import list_pscad_processes  # noqa: E402
from pscad_mcp.core.service import PscadService  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def divider_blueprint(source_hash: str) -> dict:
    channel = "Mid Point Voltage/Mid Point Voltage"
    rules = [{
        "rule_id": "finite-voltage", "kind": "all_finite", "channel": channel,
        "required": True, "source_class": "model_observed", "physical": False,
        "arguments": {},
    }]
    for name, metric, low, high in (
        ("positive-peak", "maximum", 24.9, 25.1),
        ("negative-peak", "minimum", -25.1, -24.9),
        ("zero-mean", "mean", -0.02, 0.02),
    ):
        rules.append({
            "rule_id": name, "kind": "window_summary", "channel": channel,
            "required": True, "source_class": "engineering_accepted", "physical": True,
            "arguments": {"window": [0.05, 0.15], "metric": metric,
                          "minimum": low, "maximum": high},
        })
    return {
        "identity": {"schema_version": 1, "name": "voltage-divider-462-v1",
                     "supported_pscad_versions": ["4.6.2"]},
        "source_package": {"entry_point": "vdiv.pscx", "handling_policy": "read_only",
                           "required": [{"path": "vdiv.pscx", "kind": "file", "sha256": source_hash}]},
        "operations": [
            {"sequence": 1, "kind": "set_component_parameters", "target": "Source1",
             "operation_id": "halve-source-voltage",
             "arguments": {"parameters": {"Vm": "35.355 [kV]"}, "units": {}}},
            {"sequence": 2, "kind": "set_project_settings", "target": "project",
             "operation_id": "enable-fresh-output",
             "arguments": {"settings": {"time_duration": "0.2", "time_step": "50",
                                         "sample_step": "50", "PlotType": "1",
                                         "output_filename": "Divider.out"}}},
        ],
        "acceptance": {
            "required_structure": [{"logical_id": "Source1", "definition": "master:source_1"}],
            "required_parameters": [{"logical_id": "Source1", "name": "Vm", "value": "35.355 [kV]"}],
            "blocking_messages": ["error", "fatal"],
            "outputs": [{"channel": channel, "units": "kV", "required": True}],
            "rules": rules,
        },
        "publication": {"delivery_package": True, "scope": "physical_and_model",
                        "evidence_files": ["plan.json", "validation-report.json", "manifest.json"]},
    }


async def run(workspace: Path, reference: Path) -> dict:
    if os.getenv("PSCAD_MCP_ACCEPTANCE") != "1":
        raise ValueError("PSCAD_MCP_ACCEPTANCE=1 is required")
    workspace = workspace.resolve()
    reference = reference.resolve(strict=True)
    if workspace == reference.parent or workspace in reference.parents or reference.parent in workspace.parents:
        raise ValueError("Acceptance workspace must be disjoint from the immutable reference")
    workspace.mkdir(parents=True, exist_ok=False)
    source_root = workspace / "source"
    source_root.mkdir()
    shutil.copyfile(reference, source_root / "vdiv.pscx")
    master = Path("C:/Program Files (x86)/PSCAD46/master.pslx")
    compiler = Path("C:/Program Files (x86)/GFortran/4.6/bin/gfortran.exe")
    before = {str(path): sha256(path) for path in (reference, master, compiler)}
    report = {
        "schema_version": 1, "scope": "generic_blueprint_builder",
        "status": "FAIL", "model_accepted": False,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_hashes_before": before,
        "physical_basis": "Official vdiv: 60 Hz, 1 ohm source and 1 ohm load; 35.355 kV RMS source gives 25 kV peak load voltage.",
    }
    backend = LegacyBackend(robust_executor, version="4.6.2", x64=True,
                            process_probe=list_pscad_processes,
                            legacy_existing_policy=acceptance_launch_policy())
    service = PscadService(lambda: backend, executor=robust_executor,
                           path_policy=PathPolicy(workspace_root=str(workspace)))
    runtime = {}
    attached = False
    try:
        await service.attach_local()
        attached = True
        runtime = await service.status()
        require_acceptance_ownership(runtime)
        report["runtime"] = runtime
        # The official tutorial was authored in 4.5.4. Let the vendor convert
        # the owned seed copy before freezing it as this builder's input.
        seed = source_root / "vdiv.pscx"
        await service.load_projects([str(seed)])
        await service.save_project("vdiv", confirm=True)
        before[str(seed)] = sha256(seed)
        report["reference_preparation"] = {
            "kind": "vendor_native_save_of_owned_copy",
            "original_sha256": before[str(reference)],
            "prepared_sha256": before[str(seed)],
        }
        blueprint = divider_blueprint(before[str(seed)])
        (workspace / "blueprint.json").write_text(json.dumps(blueprint, indent=2) + "\n", encoding="utf-8")
        builder = BlueprintBuilderService(service, workspace_root=workspace)
        plan = await builder.plan_project(blueprint, str(source_root), "Divider")
        (workspace / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        started = await builder.build_project(plan["plan_hash"], blueprint, str(source_root), "Divider", confirm=True)
        report["build"] = await asyncio.wait_for(builder.wait_for_build(started["build_id"]), timeout=600)
    except Exception as error:
        report["error"] = error.to_dict() if hasattr(error, "to_dict") else {"exception": type(error).__name__, "message": str(error)}
    finally:
        if attached:
            try:
                await service.quit_pscad(confirm=True)
            except Exception as error:
                report["cleanup_error"] = {"exception": type(error).__name__, "message": str(error)}
        report["remaining_owned_processes"] = remaining_acceptance_processes(runtime, list_pscad_processes) if runtime else None
        report["source_hashes_after"] = {path: sha256(Path(path)) for path in before}
        report["sources_immutable"] = report["source_hashes_before"] == report["source_hashes_after"]
        build = report.get("build", {})
        result = build.get("result") or {}
        accepted = (
            build.get("state") == "published"
            and result.get("run_through_acceptance") is True
            and result.get("physical_acceptance") is True
            and report["sources_immutable"]
            and report["remaining_owned_processes"] == []
            and "cleanup_error" not in report and "error" not in report
        )
        report["status"] = "PASS" if accepted else "FAIL"
        report["model_accepted"] = accepted
        report["artifact_hashes"] = {
            str(path): sha256(path) for path in sorted(workspace.rglob("*"))
            if path.is_file() and path.suffix.casefold() in {".pscx", ".json", ".inf", ".out", ".pslx"}
        }
        (workspace / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=Path("C:/Users/Public/Documents/PSCAD/4.6/Examples/tutorial/vdiv.pscx"))
    args = parser.parse_args()
    report = asyncio.run(run(args.workspace, args.reference))
    print(json.dumps({"status": report["status"], "error": report.get("error"),
                      "build_error": report.get("build", {}).get("error"),
                      "report": str(args.workspace.resolve() / "report.json")}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
