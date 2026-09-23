"""Fresh independent replay of a closed joint run whose first dataset passed."""

from __future__ import annotations

import argparse
import ast
import asyncio
import copy
import hashlib
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path
from uuid import uuid4

from pscad_mcp.acceptance.evidence import _is_reparse_point
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc import blank_service, native_fault_replay
from pscad_mcp.hvdc.builders.mmc.journal import AtomicJournal, WorkspaceBuildLease
from tests import mmc_joint_acceptance as lifecycle
from tests import mmc_joint_after_publication as continuation
from tests import mmc_publication_resume as publication

SOURCE_REVISION = "330017cf71b5619b9b961d183ef7ee3b54ad9fdb"
_NATIVE = "pscad_mcp/hvdc/builders/mmc/native_fault_replay.py"
_HARNESS = (
    "tests/mmc_joint_acceptance.py", "tests/mmc_timing_fault_case.py",
    "tests/mmc_joint_seed.py", "tests/mmc_b_handoff.py",
    "tests/mmc_publication_resume.py", "tests/mmc_joint_after_publication.py",
    "tests/test_mmc_fault_evidence_real.py",
)
_SAVE_ERROR = "The replay saved model differs beyond the verified virtual document root and vendor save metadata"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _same(first, second):
    return native_fault_replay._json_hash(first) == native_fault_replay._json_hash(second)


def _validate_closed_failure(report, worker):
    _require(report.get("schema_version") == 1 and report.get("scope") == "fresh_joint_after_publication" and report.get("status") == "FAIL", "Only the failed fresh joint attempt is resumable")
    _require(report.get("history", [])[-1:] == ["finished"] and "joint_closed" in report["history"], "The previous joint attempt is not closed")
    _require(report.get("owned_process_cleaned") is True and report.get("cleanup_pending") is False and report.get("lease_retained") is False and not report.get("finalization_errors"), "The previous coordinator has unresolved cleanup")
    _require(report.get("error", {}).get("code") == "MMC_JOINT_ACCEPTANCE_FAILED", "The previous coordinator failed for another reason")
    phase = report["joint"]
    _require(phase.get("status") == "FAIL" and phase.get("run_completed") is True and phase.get("owned_process_cleaned") is True and phase.get("cleanup_pending") is False and not phase.get("pending_vendor_calls") and not phase.get("lease_retained"), "The first joint execution is incomplete or not cleaned")
    _require(phase.get("history") == ["saved_and_bound", "compiled", "running", "simulated", "outputs_frozen"], "The first execution has an unexpected lifecycle")
    cleanup = phase.get("service_cleanup", {})
    _require(cleanup.get("owned_process_cleaned") is True and cleanup.get("cleanup_pending") is False, "The first owned service did not close")
    analysis = phase["analysis"]
    checks = analysis.get("fault", {}).get("check_results", [])
    _require(analysis.get("verdict") == "PASS" and analysis.get("fault", {}).get("verdict") == "PASS" and checks and all(item.get("status") == "PASS" for item in checks) and analysis.get("timing", {}).get("measured_events"), "The first joint timing/physical dataset did not pass")
    replay = phase["reload"]
    _require(replay.get("status") == "FAIL" and replay.get("owned_process_cleaned") is True and replay.get("cleanup_pending") is False and replay.get("worker_exit_code") == 1, "The failed replay has unresolved ownership or another exit state")
    _require(worker.get("schema_version") == 1 and worker.get("status") == "FAIL" and worker.get("owned_process_cleaned") is True and worker.get("cleanup_pending") is False and not worker.get("pending_vendor_calls"), "The failed replay worker is not closed")
    _require(worker.get("error") == {"type": "ValueError", "message": _SAVE_ERROR} and replay.get("error") == worker["error"], "Replay did not fail solely at the reviewed saved-model comparison")
    _require([item.get("stage") for item in worker.get("history", [])] == ["frozen_copy_verified"] and not worker.get("run_started") and not worker.get("run_completed") and not worker.get("replay_saved_model_verified") and not worker.get("messages") and not worker.get("acceptance"), "The failed replay already compiled or ran")
    _require(not any(key in worker.get("result", {}) for key in ("output_file", "output_index_path", "samples_path")), "The failed replay contains unexpected output evidence")
    return True


def _verify_native_code_change(before, after):
    before_tree, after_tree = ast.parse(before), ast.parse(after)
    name = "_normalize_hierarchy_call_order"
    helpers = [node for node in after_tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    _require(len(helpers) == 1 and not any(isinstance(node, ast.FunctionDef) and node.name == name for node in before_tree.body), "The comparator change has an unexpected helper definition")
    helper_call = ast.dump(ast.parse("_normalize_hierarchy_call_order(before, after)").body[0], include_attributes=False)
    previous_call = ast.dump(ast.parse("_normalize_new_sticky_styles(before, after)").body[0], include_attributes=False)
    comparators = [node for node in after_tree.body if isinstance(node, ast.FunctionDef) and node.name == "_verify_saved_model_roots"]
    _require(len(comparators) == 1, "The saved-model comparator is missing")
    comparator = comparators[0]
    matches = [index for index, node in enumerate(comparator.body) if ast.dump(node, include_attributes=False) == helper_call]
    _require(len(matches) == 1 and matches[0] > 0 and ast.dump(comparator.body[matches[0] - 1], include_attributes=False) == previous_call, "The hierarchy helper call differs from its reviewed position or arguments")
    del comparator.body[matches[0]]
    after_tree.body.remove(helpers[0])
    _require(ast.dump(before_tree, include_attributes=False) == ast.dump(after_tree, include_attributes=False), "Native replay changed beyond the reviewed hierarchy helper and single call")
    return True


def _git(*arguments):
    return subprocess.run(["git", *arguments], cwd=Path(__file__).resolve().parents[1], capture_output=True, check=True).stdout


def _code_provenance(preparation, ledger):
    root = Path(__file__).resolve().parents[1]
    data = _git("archive", SOURCE_REVISION, "pscad_mcp", *_HARNESS)
    current, normalized = {}, {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for member in archive.getmembers():
            if not member.isfile() or not member.name.endswith(".py"):
                continue
            historical = archive.extractfile(member).read()
            path = root / member.name
            observed = path.read_bytes()
            if member.name == _NATIVE:
                _verify_native_code_change(historical, observed)
            else:
                _require(observed.replace(b"\r\n", b"\n") == historical.replace(b"\r\n", b"\n"), "A production/evaluation/worker file changed: " + member.name)
            ref = blank_service._identity(path)
            ledger.check(ref["path"], ref["sha256"])
            current[member.name] = ref
            normalized[member.name] = hashlib.sha256(historical.replace(b"\r\n", b"\n")).hexdigest()
    _require(all(path in current for path in (*_HARNESS, _NATIVE)), "Historical worker source coverage is incomplete")
    for ref in preparation["code_identities"]:
        ledger.check(ref["path"], ref["sha256"])
        old = Path(ref["path"])
        matching = [name for name in current if old.as_posix().casefold().endswith("/" + name.casefold())]
        _require(len(matching) == 1 and hashlib.sha256(old.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == normalized[matching[0]], "A frozen preparation producer differs from its original Git source")
    own = blank_service._identity(Path(__file__))
    ledger.check(own["path"], own["sha256"])
    current[Path(__file__).relative_to(root).as_posix()] = own
    return {"first_execution_source_revision": SOURCE_REVISION, "execution_revision": _git("rev-parse", "HEAD").decode().strip(), "current_code_identities": current, "historical_normalized_sha256": normalized, "retained_preparation_code_identities": copy.deepcopy(preparation["code_identities"]), "native_exception": {"helper": "_normalize_hierarchy_call_order", "call": "_normalize_hierarchy_call_order(before, after)", "remaining_ast_unchanged": True}}


def _verify_committed_execution(provenance):
    for name, ref in provenance["current_code_identities"].items():
        committed = _git("show", provenance["execution_revision"] + ":" + name)
        _require(Path(ref["path"]).read_bytes().replace(b"\r\n", b"\n") == committed.replace(b"\r\n", b"\n"), "Execution code is not the recorded committed revision: " + name)


def load_previous_joint(reference):
    ledger = publication._Ledger()
    report = ledger.read(reference["path"], reference["sha256"])
    root = Path(report["root"]).resolve()
    _require(Path(report["report_path"]).resolve() == Path(reference["path"]).resolve() and Path(reference["path"]).resolve().is_relative_to(root), "The previous report belongs to another workspace")
    phase = report["joint"]
    replay = phase["reload"]
    replay_root = root / "joint/reload"
    _require(Path(replay["report_path"]).resolve() == replay_root / "worker/report.json" and Path(replay["supervisor_report_path"]).resolve() == replay_root / "supervisor-report.json", "The old replay reports belong to another worker")
    worker = ledger.read(replay["report_path"], replay["report_sha256"], within=replay_root)
    supervisor = ledger.read(replay["supervisor_report_path"], replay["supervisor_report_sha256"], within=replay_root)
    _validate_closed_failure(report, worker)
    _require({**supervisor, "supervisor_report_sha256": replay["supervisor_report_sha256"]} == replay and all(supervisor.get(key) == value for key, value in worker.items()), "The old supervisor/worker/parent reports disagree")
    _require(native_fault_replay._worker_matches_launcher(worker, replay["launcher_pid"]), "The old worker PID is not bound to its launcher")
    request = ledger.read(root / "request.json", report["request_sha256"], within=root)
    replay_request = ledger.read(replay_root / "request.json", worker["request_sha256"], within=replay_root)
    preparation_ref = report["joint_preparation"]
    _require(request["joint_preparation"] == preparation_ref and request["publication_receipt"] == report["publication_receipt"] and request["b_handoff"] == report["b_handoff"]["file"], "The original joint request differs from its frozen parents")
    preparation = ledger.read(preparation_ref["path"], preparation_ref["sha256"], within=root / "joint")
    provenance = _code_provenance(preparation, ledger)
    result = phase["result"]
    project = Path(phase["first_saved_model"]["path"])
    _require(project.resolve() == root / "joint/JointFaultCase.pscx" and preparation["project"]["path"] == str(project), "The retained first model belongs to another case")
    ledger.check(project, phase["first_saved_model"]["sha256"], within=root / "joint")
    ledger.check(phase["first_saved_snapshot"]["path"], phase["first_saved_snapshot"]["sha256"], within=root / "joint")
    _require(phase["first_saved_model"]["sha256"] == phase["first_saved_snapshot"]["sha256"] == result["tested_project_sha256"], "The first model and preserved snapshot differ")
    contract = ledger.read(result["channel_contract_path"], result["channel_contract_sha256"], within=root / "joint")
    index = ledger.read(result["output_index_path"], result["output_index_sha256"], within=root / "joint")
    samples = ledger.read(result["samples_path"], result["samples_sha256"], within=root / "joint")
    analysis = phase["analysis"]
    saved_analysis = ledger.read(analysis["report_path"], analysis["report_sha256"], within=root / "joint")
    _require({**saved_analysis, "report_sha256": analysis["report_sha256"]} == analysis, "The first analysis differs from its frozen file")
    _require(contract == phase["first_saved_fault_contract"] and index == phase["output_identity"] == samples["identity"] == analysis["output_identity"], "The first-run model/channel/sample/analysis dataset bindings disagree")
    _require(analysis["schema_version"] == 1 and analysis["scope"] == "joint_dataset_evaluation" and analysis["preparation_sha256"] == preparation["preparation_sha256"] and analysis["schedule_sha256"] == preparation["schedule"]["schedule_sha256"] and analysis["checks_sha256"] == preparation["checks_sha256"] and analysis["saved_fault_contract_sha256"] == lifecycle._digest(contract), "The first analysis uses another preparation, schedule, or check contract")
    _require(index["started_after"] == phase["run_started_after"] and Path(index["primary"]).resolve() == Path(result["output_file"]).resolve() and Path(index["primary"]).name == project.stem + "_01.out", "The first output index belongs to another execution")
    lifecycle.verify_output_dataset(index)
    for ref in index["files"].values():
        ledger.check(ref["path"], ref["sha256"], within=root / "joint")
    b_ref = report["b_handoff"]["file"]
    expected_context = {"schema_version": 1, "scope": "joint_timing_fault", "b_handoff": b_ref, "preparation": preparation, "first_saved_model": phase["first_saved_model"], "first_saved_fault_contract": contract}
    _require(replay_request["schema_version"] == 1 and replay_request["verification_context"] == expected_context and replay_request["verification_context_sha256"] == lifecycle._digest(expected_context), "The old child context differs from the first-run parents")
    _require(replay_request["project"] == phase["first_saved_model"] and replay_request["channel_contract"] == contract and replay_request["channel_contract_sha256"] == worker["parent_channel_contract_sha256"] == lifecycle._digest(contract), "The old replay copied another first-run model or contract")
    _require(replay_request["checks_contract"] == preparation["checks"] and replay_request["checks_sha256"] == worker["checks_sha256"] == preparation["checks_sha256"] and replay_request["settings"] == preparation["public_plan"]["settings"] and replay_request["source_identities"] == preparation["public_plan"]["source_identities"], "The old replay changed the frozen physical plan")
    bundle = project.with_suffix(".bundle")
    _require(Path(replay_request["bundle"]["path"]).resolve() == bundle and native_fault_replay._files(bundle) == replay_request["bundle"]["source_snapshot"], "The first replay source bundle changed")
    dependencies = {Path(item["path"]).relative_to(bundle).as_posix(): item["sha256"] for item in preparation["dependency_copies"]}
    _require(replay_request["bundle"]["files"] == dependencies and worker["copied_bundle_hashes"] == dependencies and worker["copied_project_sha256"] == phase["first_saved_model"]["sha256"], "The old replay dependency/model lineage changed")
    _require(all(snapshot == dependencies for snapshot in worker["dependency_snapshots"].values()), "A frozen old replay dependency snapshot differs")
    for relative, digest in replay_request["bundle"]["source_snapshot"].items():
        ledger.check(blank_service._bundle_file(bundle, relative), digest, within=bundle)
    for relative, digest in dependencies.items():
        ledger.check(blank_service._bundle_file(replay_root / "worker" / bundle.name, relative), digest, within=replay_root)
    child_result = worker["result"]
    failed_contract = ledger.read(child_result["channel_contract_path"], child_result["channel_contract_sha256"], within=replay_root / "worker")
    failed_project = replay_root / "worker" / project.name
    ledger.check(failed_project, child_result["tested_project_sha256"], within=replay_root)
    lifecycle.verify_joint_saved_child(expected_context, failed_project, failed_contract)
    publication._verify_runtime(phase, phase["ownership"], report["request_sha256"])
    _require(phase["request_sha256"] == report["request_sha256"], "First runtime ownership references another request")
    publication._verify_runtime(worker, worker["cleanup_ownership"], worker["request_sha256"])
    ownership_path = replay_root / "worker/ownership.json"
    ownership = ledger.read(ownership_path, blank_service._sha256(ownership_path), within=replay_root)
    _require(ownership == worker["cleanup_ownership"], "The old worker ownership record differs")
    for ref in (b_ref, report["publication_receipt"], preparation["prepared_snapshot"], *preparation["public_plan"]["source_identities"].values()):
        ledger.check(ref["path"], ref["sha256"])
    publication._recorded_refs(preparation["dependency_copies"], ledger)
    for stage in preparation["lineage"]:
        ledger.check(stage["source"], stage["source_sha256"])
        if stage["stage"] != "embedded_control":
            ledger.check(stage["destination"], stage["destination_sha256"])
    lifecycle.verify_joint_preparation(preparation, saved_fault_contract=contract)
    publication._verify_saved_settings(project, preparation["public_plan"])
    ledger.recheck()
    return {"previous_report": report, "root": root, "preparation": preparation, "contract": contract, "index": index, "samples": samples, "analysis": analysis, "b_ref": b_ref, "ledger": ledger, "provenance": provenance, "replay_context": expected_context}


def revalidate_first_run(context):
    preparation, contract, index = context["preparation"], context["contract"], context["index"]
    project = Path(preparation["project"]["path"])
    lifecycle.verify_joint_preparation(preparation, saved_fault_contract=contract)
    lifecycle.verify_output_dataset(index)
    fault = blank_service.evaluate_template_native_dc_fault(context["samples"], channel_contract=contract, checks_contract=preparation["checks"], fault_current_limit_ka=preparation["checks"]["fault_current_limit_ka"])
    _require(fault.get("verdict") == "PASS" and _same(fault, context["analysis"]["fault"]), "The retained first-run physical checks no longer match the proven PASS")
    timing = lifecycle.timed_control.read_event_evidence(preparation["schedule"], project, [item["path"] for name, item in index["files"].items() if name.casefold().endswith(".out")], started_after=index["started_after"])
    lifecycle.require_same_dataset(index, timing)
    _require(_same(timing, context["analysis"]["timing"]), "Independent timing evidence differs from the retained first dataset")
    lifecycle.verify_output_dataset(index)
    context["ledger"].recheck()
    return {"verdict": "PASS", "fault": fault, "timing": timing, "output_identity": copy.deepcopy(index), "first_run_reused": True}


def _workspace_root(raw_root, previous_ref):
    _require(raw_root.is_absolute(), "The new replay workspace must be absolute")
    for path in (raw_root, *raw_root.parents):
        try:
            _require(not _is_reparse_point(path.lstat()), "The new replay workspace traverses a link")
        except FileNotFoundError:
            pass
    parent = publication._Ledger().read(previous_ref["path"], previous_ref["sha256"])
    if parent.get("publication_receipt"):
        continuation._check_workspace_isolated(raw_root, parent["publication_receipt"])
    protected = [Path(parent["root"]).resolve(), Path(__file__).resolve().parents[1]]
    if parent.get("joint_preparation"):
        ref = parent["joint_preparation"]
        preparation = publication._Ledger().read(ref["path"], ref["sha256"])
        for identity in preparation["code_identities"]:
            path = Path(identity["path"])
            marker = next((index for index, part in enumerate(path.parts) if part in {"pscad_mcp", "tests"}), None)
            if marker is not None:
                protected.append(Path(*path.parts[:marker]).resolve())
    root = raw_root.resolve()
    _require(all(not root.is_relative_to(path) and not path.is_relative_to(root) for path in protected), "The new workspace overlaps frozen evidence or source code")
    return root


def _finalize_replay(report, leases, journal, successful):
    errors = report.setdefault("finalization_errors", [])

    def failed(stage, error):
        errors.append({"stage": stage, "type": type(error).__name__, "message": str(error)})
        report.setdefault("error", {"type": type(error).__name__, "message": str(error)})

    report.update(status="FAIL", physical_acceptance_verified=False)
    report["history"].append("finalizing")
    try:
        journal.write(report)
    except BaseException as error:  # noqa: BLE001 - journal failure cannot skip owned lease cleanup
        failed("finalizing_journal", error)
    retained = bool(leases) and bool(report.get("cleanup_pending"))
    if not report.get("cleanup_pending"):
        for lease in reversed(leases):
            try:
                _require(lease.release(lease.token) is True, "The owned replay recovery lease was not released")
            except BaseException as error:  # noqa: BLE001 - keep each failed owned release pending
                retained = True
                failed("lease_release", error)
    report["lease_retained"] = retained
    if successful and not errors and not retained and report.get("owned_process_cleaned") is True and report.get("cleanup_pending") is False:
        report.update(status="PASS", physical_acceptance_verified=True)
    report["history"].append("finished")
    try:
        journal.write(report)
    except BaseException as error:  # noqa: BLE001 - only a durable completed report may claim PASS
        failed("final_journal", error)
        report.update(status="FAIL", physical_acceptance_verified=False)
        try:
            journal.write(report)
        except BaseException as retry_error:  # noqa: BLE001 - preserve accurate in-memory failed finalization
            failed("failure_journal", retry_error)


async def resume_joint_replay(previous_ref, workspace):
    root = _workspace_root(Path(workspace).expanduser(), previous_ref)
    root.mkdir(parents=True, exist_ok=False)
    run_id = uuid4().hex
    journal = AtomicJournal(root, run_id)
    report = {"schema_version": 1, "scope": "joint_independent_replay_recovery", "status": "FAIL", "physical_acceptance_verified": False, "history": [], "root": str(root), "report_path": str(journal.path), "python_pid": os.getpid(), "previous_report": copy.deepcopy(previous_ref), "supersedes": {"scope": "independent_joint_replay_only", "previous_status": "FAIL", "report": copy.deepcopy(previous_ref)}, "owned_process_cleaned": True, "cleanup_pending": False, "lease_retained": False, "replay_invoked": False}
    leases, successful = [], False

    def checkpoint(stage):
        report["history"].append(stage)
        journal.write(report)

    try:
        checkpoint("preflight")
        if os.getenv("PSCAD_MCP_MMC_ACCEPTANCE") != "1":
            raise lifecycle._error("MMC_ACCEPTANCE_OPT_IN_REQUIRED", "PSCAD_MCP_MMC_ACCEPTANCE=1 is required before fresh licensed joint replay")
        context = load_previous_joint(previous_ref)
        _verify_committed_execution(context["provenance"])
        report["provenance"] = context["provenance"]
        replay_root = root / "replay"
        project = Path(context["preparation"]["project"]["path"])
        for line in context["preparation"]["public_plan"]["line_constants"]["inputs"]:
            path = replay_root / "worker" / (project.stem + ".if15_x86") / (line["name"] + ".tli")
            _require(len(str(path)) <= 199, "The new replay TLine path exceeds the legacy solver limit")
        leases.append(WorkspaceBuildLease.acquire(root, run_id))
        report["lease_retained"] = True
        checkpoint("first_run_revalidation")
        report["first_revalidation"] = revalidate_first_run(context)
        report["retained_preparation"] = copy.deepcopy(context["previous_report"]["joint_preparation"])
        report["first_saved_model"] = copy.deepcopy(context["previous_report"]["joint"]["first_saved_model"])
        report["first_saved_snapshot"] = copy.deepcopy(context["previous_report"]["joint"]["first_saved_snapshot"])
        report["b_handoff"] = copy.deepcopy(context["b_ref"])
        report["reload"] = {"status": "FAIL", "owned_process_cleaned": False, "cleanup_pending": True, "workspace": str(replay_root)}
        report.update(owned_process_cleaned=False, cleanup_pending=True)
        checkpoint("fresh_replay_requested")
        report["replay_invoked"] = True
        replay = await lifecycle.run_joint_replay(context["preparation"], context["contract"], context["b_ref"], replay_root)
        _require(isinstance(replay, dict), "The replay returned no ownership report")
        report["reload"] = replay
        report["owned_process_cleaned"] = replay.get("owned_process_cleaned") is True
        report["cleanup_pending"] = replay.get("cleanup_pending") is not False or not report["owned_process_cleaned"]
        _require(replay.get("status") == "PASS" and replay.get("worker_exit_code") == 0 and not report["cleanup_pending"], "The fresh independent replay or its owned cleanup did not pass")
        _require(replay.get("project_sha256") == report["first_saved_model"]["sha256"] and replay.get("checks_sha256") == context["preparation"]["checks_sha256"] and replay.get("parent_channel_contract_sha256") == lifecycle._digest(context["contract"]) and replay.get("verification_context_sha256") == lifecycle._digest(context["replay_context"]), "The fresh replay differs from its retained first-run lineage")
        _require(replay.get("acceptance", {}).get("verdict") == "PASS" and replay.get("supplemental_saved_validation", {}).get("verdict") == "PASS" and replay.get("supplemental_evidence", {}).get("verdict") == "PASS" and replay["supplemental_evidence"]["output_identity"] == replay.get("output_identity"), "Fresh native and timing checks did not pass on the same dataset")
        lifecycle.verify_output_dataset(replay["output_identity"])
        lifecycle.verify_joint_preparation(context["preparation"], saved_fault_contract=context["contract"])
        context["ledger"].recheck()
        report["verified_input_files"] = context["ledger"].files
        checkpoint("fresh_replay_verified")
        successful = True
    except BaseException as error:  # noqa: BLE001 - a failed or interrupted replay must retain ownership evidence
        if not report["replay_invoked"]:
            report.update(owned_process_cleaned=True, cleanup_pending=False)
            if "reload" in report:
                report["reload"].update(owned_process_cleaned=True, cleanup_pending=False, phase="not_invoked")
        report["error"] = error.to_dict() if isinstance(error, BackendError) else {"code": "MMC_JOINT_REPLAY_RECOVERY_FAILED", "type": type(error).__name__, "message": str(error)}
    finally:
        _finalize_replay(report, leases, journal, successful)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-report", type=Path, required=True)
    parser.add_argument("--previous-report-sha256", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(resume_joint_replay({"path": str(args.previous_report.resolve()), "sha256": args.previous_report_sha256}, args.workspace))
    print(json.dumps({"status": report["status"], "report_path": report["report_path"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
