"""Licensed public-builder PWM acceptance with thirteen fresh physical runs."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pscad_mcp.acceptance.preflight_cli import _service
from pscad_mcp.acceptance.process_scope import (
    remaining_acceptance_processes,
    require_acceptance_ownership,
)
from pscad_mcp.core.executor import robust_executor
from pscad_mcp.core.process_inventory import list_pscad_processes
from pscad_mcp.hvdc.builders.mmc.parametric_service import ParametricMmcBuilderService
from pscad_mcp.hvdc.builders.mmc.pwm_output import digest
from pscad_mcp.hvdc.builders.mmc.pwm_runtime import write_report


async def accept(args, report, checkpoint):
    workspace = args.workspace.resolve()
    configured_root = workspace
    recovery = None
    if args.resume_report is not None:
        from pscad_mcp.hvdc.builders.mmc.publication_recovery import (
            FrozenPwmPublicationEngine,
        )

        recovery = FrozenPwmPublicationEngine(
            args.resume_report,
            lambda results: recovery_progress(report, checkpoint, results),
        )
        configured_root = Path(
            os.path.commonpath([workspace, Path(recovery.report["plan"]["workspace"])])
        )
        report["recovered_matrix_report"] = str(recovery.report_file)
        report["recovered_matrix_report_sha256"] = recovery.report_hash
    service = _service(configured_root)
    runtime = None
    try:
        await service.attach_local()
        runtime = await service.status()
        require_acceptance_ownership(runtime)
        report["runtime"] = runtime
        checkpoint()
        request = json.loads(args.request.read_text())
        builder = ParametricMmcBuilderService(
            service, workspace_root=configured_root, pwm_engine=recovery
        )
        plan = builder.plan_model(request, args.project_name, workspace)
        report["plan"] = plan
        report["original_inputs"] = {
            path: digest(path)
            for child in plan["engine_plans"]
            for path in child["source_paths"].values()
        }
        report["original_inputs"][str(args.request.resolve())] = digest(args.request)
        for child in plan["engine_plans"]:
            report["original_inputs"].update(child["asset_hashes"])
        if recovery is not None:
            report["original_inputs"][str(recovery.report_file)] = recovery.report_hash
        master = await service.get_master_library_identity()
        report["original_inputs"][master["master_path"]] = master["master_sha256"]
        checkpoint()
        started = await builder.build_model(
            request, plan["plan_hash"], args.project_name, workspace, confirm=True
        )
        report["build_id"] = started["build_id"]
        while True:
            status = builder.get_status(started["build_id"])
            report["parent_status"] = status
            checkpoint()
            if status["state"] in {"published", "failed", "interrupted"}:
                break
            await asyncio.sleep(1)
        if (
            status["state"] != "published"
            or status["result"].get("model_accepted") is not True
        ):
            raise RuntimeError(
                "The public PWM builder has no complete passing acceptance"
            )
        final_project = status["engines"][0]["final_path"]
        manifest = json.loads(
            Path(status["engines"][0]["acceptance_manifest"]).read_text()
        )
        report["independent_validation"] = await asyncio.to_thread(
            builder.validate_model,
            final_project,
            "detailed_pwm",
            list(manifest["delivery"]["outputs"]),
            "full",
        )
        if report["independent_validation"]["accepted"] is not True:
            raise RuntimeError(
                "The public validation API did not confirm frozen PWM physical evidence"
            )
        report["published_normal"] = status["engines"][0]["publication_verification"][
            "normal"
        ]
        report["delivered_project_sha256"] = digest(final_project)
        report["acceptance_manifest_sha256"] = digest(
            status["engines"][0]["acceptance_manifest"]
        )
        report["model_accepted"] = True
        report["status"] = "PASS"
    except Exception as error:  # noqa: BLE001 - preserve the public attempt verdict
        report["status"] = "FAIL"
        report["model_accepted"] = False
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        report["stage"] = "cleanup"
        checkpoint()
        try:
            report["quit_result"] = await service.quit_pscad(confirm=True)
        except Exception as error:  # noqa: BLE001 - retain owned cleanup evidence
            report["quit_error"] = str(error)
            report["status"] = "FAIL"
            report["model_accepted"] = False
        report["sources_immutable"] = all(
            digest(path) == expected
            for path, expected in report.get("original_inputs", {}).items()
        )
        if "delivered_project_sha256" in report:
            report["published_project_immutable"] = (
                digest(final_project) == report["delivered_project_sha256"]
            )
            report["published_support_immutable"] = all(
                digest(item["path"]) == item["sha256"]
                for item in manifest["publication"].get("compiler_support", [])
            )
            report["sources_immutable"] = (
                report["sources_immutable"]
                and report["published_project_immutable"]
                and report["published_support_immutable"]
            )
        if runtime:
            report["remaining_owned_processes"] = remaining_acceptance_processes(
                runtime, list_pscad_processes
            )
        if not report["sources_immutable"] or report.get("remaining_owned_processes"):
            report["status"] = "FAIL"
            report["model_accepted"] = False
        report["stage"] = "finished"
        checkpoint()


def recovery_progress(report, checkpoint, results):
    report["matrix_revalidation"] = results
    checkpoint()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--project-name", default="MMC_PWM")
    parser.add_argument("--resume-report", type=Path)
    args = parser.parse_args()
    for name in ("PSCAD_MCP_ACCEPTANCE", "PSCAD_MCP_MMC_ACCEPTANCE"):
        if os.getenv(name) != "1":
            raise SystemExit(name + "=1 is required")
    args.workspace.resolve().mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": 1,
        "status": "FAIL",
        "stage": "running",
        "model_accepted": False,
        "scope": "mmc.detailed_pwm.routed_reference.public_builder",
        "tested_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "publication_producer_hashes": {
            str(p.relative_to(ROOT)): digest(p)
            for p in (
                Path(__file__),
                ROOT / "pscad_mcp/hvdc/builders/mmc/parametric_service.py",
                ROOT / "pscad_mcp/hvdc/builders/mmc/publication_recovery.py",
            )
        },
    }

    def checkpoint():
        write_report(args.workspace.resolve() / "report.json", report)

    try:
        asyncio.run(accept(args, report, checkpoint))
    except Exception as error:  # noqa: BLE001 - preserve rejected recovery input
        report["status"], report["stage"] = "FAIL", "finished"
        report["model_accepted"] = False
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        checkpoint()
    finally:
        robust_executor.shutdown()
    print(
        json.dumps(
            {
                "report": str(args.workspace.resolve() / "report.json"),
                "status": report["status"],
                "model_accepted": report["model_accepted"],
            }
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
