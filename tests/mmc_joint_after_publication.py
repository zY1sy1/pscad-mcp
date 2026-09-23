"""Run a fresh owned joint case after verified publication-only recovery."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
from pathlib import Path
from uuid import uuid4

from pscad_mcp.acceptance.evidence import _is_reparse_point
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.journal import AtomicJournal, WorkspaceBuildLease
from tests import mmc_joint_acceptance as lifecycle
from tests import mmc_publication_resume as publication


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _check_workspace_isolated(raw_root, receipt_ref):
    for path in (raw_root, *raw_root.parents):
        try:
            _require(not _is_reparse_point(path.lstat()), "The new workspace traverses a link")
        except FileNotFoundError:
            pass
    if not receipt_ref:
        return
    ledger = publication._Ledger()
    receipt = ledger.read(receipt_ref["path"], receipt_ref["sha256"])
    receipt_path = Path(receipt_ref["path"]).resolve()
    receipt_root = receipt_path.parent
    if len(receipt_path.parents) > 3 and receipt_path.parents[1].name == "mmc-builds" and receipt_path.parents[2].name == ".pscad-mcp":
        receipt_root = receipt_path.parents[3]
    protected = [receipt_root]
    if "source_attempt" in receipt:
        ref = receipt["source_attempt"]["coordinator"]
        coordinator = ledger.read(ref["path"], ref["sha256"])
        protected.append(Path(coordinator["root"]).resolve())
    if "published_project" in receipt:
        protected.append(Path(receipt["published_project"]["path"]).resolve().with_suffix(".bundle"))
    root = raw_root.resolve()
    _require(
        all(not root.is_relative_to(path) and not path.is_relative_to(root) for path in protected),
        "The fresh joint workspace overlaps preserved publication evidence",
    )


async def run_joint_after_publication(
    receipt_ref, handoff_ref, workspace, *, service_factory=lifecycle._service
):
    raw_root = Path(workspace).expanduser()
    _require(raw_root.is_absolute(), "Acceptance workspace must be absolute")
    try:
        _check_workspace_isolated(raw_root, receipt_ref)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {
            "schema_version": 1, "scope": "fresh_joint_after_publication", "status": "FAIL",
            "physical_acceptance_verified": False, "owned_process_cleaned": True,
            "cleanup_pending": False, "lease_retained": False, "report_path": None,
            "error": {"code": "MMC_JOINT_WORKSPACE_INVALID", "type": type(error).__name__, "message": str(error)},
        }
    root = raw_root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    run_id = uuid4().hex
    journal = AtomicJournal(root, run_id)
    report = {
        "schema_version": 1,
        "scope": "fresh_joint_after_publication",
        "status": "FAIL",
        "history": [],
        "physical_acceptance_verified": False,
        "python_pid": os.getpid(),
        "root": str(root),
        "owned_process_cleaned": True,
        "cleanup_pending": False,
        "report_path": str(journal.path),
        "publication_receipt": copy.deepcopy(receipt_ref),
    }
    lease = None
    previous_concurrent = os.environ.get("PSCAD_MCP_ACCEPTANCE_CONCURRENT")

    def checkpoint(stage):
        report["history"].append(stage)
        journal.write(report)

    try:
        checkpoint("preflight")
        if os.getenv("PSCAD_MCP_MMC_ACCEPTANCE") != "1":
            raise lifecycle._error(
                "MMC_ACCEPTANCE_OPT_IN_REQUIRED",
                "PSCAD_MCP_MMC_ACCEPTANCE=1 is required before licensed joint execution",
            )
        lifecycle._check_ref(receipt_ref)
        lifecycle._check_ref(handoff_ref)
        published = await publication.validate_publication_recovery(receipt_ref)
        _require(
            published["receipt"] == receipt_ref
            and published["b_handoff"] == handoff_ref
            and published["validation"].get("accepted") is True,
            "The verified publication differs from the requested frozen parents",
        )
        accepted = await lifecycle._validate_b(handoff_ref["path"])
        _require(accepted["file"] == handoff_ref, "The accepted B handoff changed")
        sources = accepted["source_hashes"]
        _require(
            sources == published["plan"]["source_identities"],
            "The published case and B handoff use different original sources",
        )
        lifecycle.require_recipe_match(accepted["recipe"], published["plan"]["model_recipe"])
        report["public_prerequisite"] = published
        report["b_handoff"] = accepted
        checkpoint("parents_verified")
        preparation = await lifecycle.prepare_joint_case(
            root / "joint",
            source=sources["project"]["path"],
            library=sources["library"]["path"],
            master=sources["master"]["path"],
            model_recipe=accepted["recipe"]["id"],
            publication_seed=published,
        )
        lifecycle.require_recipe_match(accepted["recipe"], preparation["public_plan"]["model_recipe"])
        _require(
            preparation["public_plan"]["source_identities"] == sources,
            "The newly prepared joint case changed its original sources",
        )
        bound = copy.deepcopy(preparation)
        bound["joint_parents"]["B"] = {
            "accepted": True, "handoff": handoff_ref, "recipe": accepted["recipe"]
        }
        bound["preparation_sha256"] = lifecycle._digest(
            {key: value for key, value in bound.items() if key != "preparation_sha256"}
        )
        lifecycle.verify_joint_preparation(bound)
        bound_path = root / "joint" / "accepted-preparation.json"
        lifecycle._write_evidence(bound_path, bound)
        report["joint_preparation"] = lifecycle._identity(bound_path)
        report["request_sha256"] = lifecycle._write_evidence(
            root / "request.json",
            {"publication_receipt": receipt_ref, "b_handoff": handoff_ref,
             "joint_preparation": report["joint_preparation"]},
        )
        lifecycle._check_ref(receipt_ref)
        lifecycle._check_ref(handoff_ref)
        lease = WorkspaceBuildLease.acquire(root, run_id)
        os.environ["PSCAD_MCP_ACCEPTANCE_CONCURRENT"] = "1"
        await lifecycle._owned_phase(
            root / "joint", "joint", report["request_sha256"], sources,
            lambda service, phase: lifecycle._run_joint(
                service, phase, accepted, bound, checkpoint
            ),
            report, checkpoint, service_factory,
        )
        lifecycle._check_ref(report["joint"]["first_saved_model"])
        lifecycle._check_ref(report["joint"]["first_saved_snapshot"])
        lifecycle.verify_joint_preparation(
            bound, saved_fault_contract=report["joint"]["first_saved_fault_contract"]
        )
        lifecycle.verify_output_dataset(report["joint"]["output_identity"])
        lifecycle._check_ref(handoff_ref)
        rechecked = await publication.validate_publication_recovery(receipt_ref)
        _require(
            lifecycle._digest(rechecked) == lifecycle._digest(published),
            "The recovered public prerequisite changed during joint execution",
        )
        checkpoint("post_close_evidence_verified")
        report.update({"status": "PASS", "physical_acceptance_verified": True})
    except BaseException as error:  # noqa: BLE001 - retain evidence through cancellation and cleanup
        report["error"] = error.to_dict() if isinstance(error, BackendError) else {
            "code": "MMC_JOINT_CONTINUATION_FAILED",
            "type": type(error).__name__, "message": str(error),
        }
    finally:
        lifecycle._finalize_run(report, lease, journal, previous_concurrent)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--handoff-sha256", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run_joint_after_publication(
        {"path": str(args.receipt.resolve()), "sha256": args.receipt_sha256},
        {"path": str(args.handoff.resolve()), "sha256": args.handoff_sha256},
        args.workspace,
    ))
    print(json.dumps({"status": report["status"], "report_path": report["report_path"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
