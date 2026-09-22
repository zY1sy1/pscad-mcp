"""Recover only publication of a closed, physically accepted public MMC run.

This harness never constructs a PSCAD service or reruns the original model.
The original failed journals and execution plan remain immutable evidence.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from xml.etree import ElementTree as ET

from pscad_mcp.acceptance.evidence import _is_reparse_point
from pscad_mcp.core.executor import robust_executor
from pscad_mcp.core.pscad_adapter import PscadAdapter
from pscad_mcp.hvdc.builders.mmc import blank_service, native_fault_replay
from pscad_mcp.hvdc.builders.mmc.blank import SubmoduleTopology
from pscad_mcp.hvdc.builders.mmc.journal import AtomicJournal, WorkspaceBuildLease


def _require(condition, message):
    if not condition:
        raise ValueError(message)


class _Ledger:
    def __init__(self):
        self.files = {}

    def check(self, path, digest, *, within=None):
        raw = Path(path)
        _require(raw.is_absolute() and re.fullmatch(r"[0-9a-f]{64}", str(digest)), "A frozen reference is malformed")
        if within is not None:
            root = Path(within).resolve()
            raw = blank_service._bundle_file(root, raw.relative_to(root).as_posix())
        for ancestor in (raw, *raw.parents):
            if _is_reparse_point(ancestor.lstat()):
                raise ValueError("Frozen references must not traverse links: " + str(raw))
        identity = blank_service._identity(raw)
        _require(identity["sha256"] == digest, "A frozen reference changed: " + str(raw))
        previous = self.files.setdefault(identity["path"], digest)
        _require(previous == digest, "One evidence file has conflicting frozen identities")
        return identity

    def read(self, path, digest, *, within=None):
        ref = self.check(path, digest, within=within)
        value = blank_service._read_hashed_json(Path(ref["path"]), digest)
        return value

    def recheck(self):
        for path, digest in tuple(self.files.items()):
            self.check(path, digest)


def _validate_terminal_records(coordinator, build):
    _require(coordinator.get("scope") == "public_and_joint_mmc" and coordinator.get("status") == "FAIL", "Only the original failed integration attempt can be recovered")
    _require(coordinator.get("history", [])[-1:] == ["finished"] and not coordinator.get("joint"), "The old attempt is unfinished or already started the joint phase")
    _require(coordinator.get("error", {}).get("code") == "MMC_PUBLIC_ACCEPTANCE_FAILED", "The coordinator failure has another cause")
    _require(coordinator.get("owned_process_cleaned") is True and coordinator.get("cleanup_pending") is False and coordinator.get("lease_retained") is False and not coordinator.get("finalization_errors"), "The old coordinator has unresolved cleanup or finalization")
    phase = coordinator["public"]
    _require(phase.get("build") == build and phase.get("build_id") == build.get("build_id"), "The public and coordinator journals disagree")
    _require(phase.get("owned_process_cleaned") is True and phase.get("cleanup_pending") is False and not phase.get("builder_cleanup_pending") and not phase.get("pending_vendor_calls"), "The old public phase has unresolved cleanup")
    cleanup = phase.get("service_cleanup", {})
    _require(cleanup.get("owned_process_cleaned") is True and cleanup.get("cleanup_pending") is False, "The owned public service did not close")
    failure = build.get("error", {})
    _require(build.get("state") == "failed" and build.get("run_completed") is True and build.get("containment", {}).get("confirmed") is True, "The public model run is incomplete")
    _require(not build.get("lease_retained") and not build.get("pending_vendor_calls") and not build.get("cleanup_pending"), "The inner public build has unresolved cleanup or ownership")
    _require(failure.get("code") == "MMC_BUILD_FAILED" and failure.get("details", {}).get("exception") == "FileNotFoundError" and "[WinError 206]" in failure.get("message", "") and "publication-candidate" in failure.get("message", ""), "The failure is not the reviewed publication path defect")
    states = [item.get("state") for item in build.get("history", [])]
    _require(states[-2:] == ["verifying_reload", "failed"] and all(name in states for name in ("simulated", "outputs_frozen", "evaluated")), "The failure occurred before completed physical evaluation and replay")
    result = build["result"]
    _require(result.get("acceptance", {}).get("verdict") == "PASS", "The original public physical checks did not pass")
    replay = result["reload"]
    _require(phase.get("reload") == replay, "The coordinator replay differs from its public build")
    _require(replay.get("status") == "PASS" and replay.get("owned_process_cleaned") is True and replay.get("cleanup_pending") is False and replay.get("worker_exit_code") == 0, "The original independent replay or its cleanup did not pass")
    return True


def _verify_shared_model_logic(before, after):
    excluded = {"_native_attempt_workspace", "_native_replay_workspace", "_preflight_publication_layout", "_publish_tested_fault_case"}
    additions = {
        ast.dump(ast.parse(statement).body[0], include_attributes=False)
        for statement in (
            'publication_workspace = _native_attempt_workspace(plan, workspace, build_id, "mmc-publications")',
            'record["result"]["publication_workspace"] = str(publication_workspace)',
        )
    }

    class PublicationArguments(ast.NodeTransformer):
        def visit_Call(self, node):
            node = self.generic_visit(node)
            if isinstance(node.func, ast.Name) and node.func.id == "_publish_tested_fault_case":
                node.keywords = [item for item in node.keywords if not (item.arg == "publication_workspace" and isinstance(item.value, ast.Name) and item.value.id == "publication_workspace")]
            return node

    def model_tree(text):
        tree = ast.parse(text)
        tree.body = [node for node in tree.body if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in excluded]
        for node in tree.body:
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_execute_native_mmc_plan":
                node.body = [item for item in node.body if ast.dump(item, include_attributes=False) not in additions]
                PublicationArguments().visit(node)
        return ast.dump(tree, include_attributes=False)

    _require(model_tree(before) == model_tree(after), "The shared model or evaluation code changed beyond the reviewed publication layout")
    return True


def _verify_historical_snapshot(identity, snapshot, git_bytes):
    snapshot = Path(snapshot)
    observed = blank_service._identity(snapshot)
    _require(observed["sha256"] == identity["sha256"], "The historical producer snapshot differs from the recorded execution bytes")
    _require(snapshot.read_bytes().replace(b"\r\n", b"\n") == git_bytes.replace(b"\r\n", b"\n"), "The historical snapshot differs from its Git source revision")
    return observed


def _git(*arguments):
    root = Path(__file__).resolve().parents[1]
    return subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True).stdout


def _producer_context(plan, snapshot, source_revision, ledger):
    _require(re.fullmatch(r"[0-9a-f]{40}", source_revision), "The execution source revision must be a complete commit SHA")
    _require(_git("rev-parse", source_revision + "^{commit}").decode().strip() == source_revision, "The original source revision is unavailable")
    producers = plan["model_recipe"]["producer_code_hashes"]
    _require(set(producers) == {"blank_service", "fault_channels", "template_native"}, "The original plan did not freeze all model producers")
    source_root = Path(blank_service.__file__).resolve().parent
    git_blobs = {}
    for name, ref in producers.items():
        _require(Path(ref["path"]).resolve() == source_root / (name + ".py"), "A model producer points outside the reviewed source files")
        blob = _git("show", source_revision + ":pscad_mcp/hvdc/builders/mmc/" + name + ".py")
        source_file = Path(snapshot) if name == "blank_service" else Path(ref["path"])
        archived_ref = _verify_historical_snapshot(ref, source_file, blob)
        ledger.check(archived_ref["path"], archived_ref["sha256"])
        git_blobs[name] = hashlib.sha256(blob).hexdigest()
    _verify_shared_model_logic(Path(snapshot).read_text(encoding="utf-8"), source_root.joinpath("blank_service.py").read_text(encoding="utf-8"))
    files = {"publisher": Path(blank_service.__file__), "resume_validator": Path(__file__), "replay_validator": Path(native_fault_replay.__file__), "output_reader": Path(PscadAdapter.read_psout.__code__.co_filename)}
    code = {name: blank_service._identity(path) for name, path in files.items()}
    for ref in code.values():
        ledger.check(ref["path"], ref["sha256"])
    return {"execution_source_revision": source_revision, "execution_producer_identities": copy.deepcopy(producers), "recovered_blank_service": blank_service._identity(Path(snapshot)), "historical_git_blob_sha256": git_blobs, "shared_model_logic_verified": True, "publication_revision": _git("rev-parse", "HEAD").decode().strip(), "publication_code_identities": code}


def _verify_runtime(record, ownership, request_hash):
    runtime = record["runtime"]
    session = runtime["session"]
    _require(runtime.get("licensed") is True and runtime.get("owns_process") is True and record.get("attach_completed") is True, "A completed licensed owned runtime is missing")
    _require(type(ownership.get("pid")) is int and ownership["pid"] > 0 and ownership["pid"] == session.get("managed_pid"), "Runtime ownership PID differs")
    _require(ownership.get("request_sha256") == request_hash and ownership.get("created_at", 0) > 0, "Runtime ownership does not bind the frozen request")
    _require(Path(ownership["executable"]).resolve() == Path(session["managed_executable"]).resolve(), "Runtime ownership executable differs")
    _require(record.get("owned_process_cleaned") is True and record.get("cleanup_pending") is False and not record.get("pending_vendor_calls"), "Runtime cleanup is incomplete")


def _verify_saved_settings(project, plan):
    settings = {item.get("name"): item.get("value") for item in ET.parse(project).findall("./paramlist[@name='Settings']/param")}
    for name, expected in (("time_duration", plan["settings"]["simulation_duration_s"]), ("time_step", plan["settings"]["time_step_s"] * 1e6), ("sample_step", plan["settings"]["output_step_s"] * 1e6)):
        _require(float(settings[name]) == expected, "The saved simulation settings differ from the original plan")
    _require(settings.get("StartType") == "0" and settings.get("startup_filename") == "" and settings.get("PlotType") == "1" and settings.get("output_filename") == project.stem + ".out", "The original cold start or output settings changed")


def _recorded_refs(value, ledger):
    if isinstance(value, dict):
        if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
            ledger.check(value["path"], value["sha256"])
            if isinstance(value.get("source"), str):
                ledger.check(value["source"], value["sha256"])
        for key in ("source", "destination", "input", "constants", "log", "output"):
            path = value.get(key + "_path", value.get(key))
            digest = value.get(key + "_sha256")
            if isinstance(path, str) and digest:
                ledger.check(path, digest)
        for item in value.values():
            _recorded_refs(item, ledger)
    elif isinstance(value, list):
        for item in value:
            _recorded_refs(item, ledger)


def load_completed_evidence(coordinator_ref, build_ref, historical_snapshot, source_revision):
    """Read and bind finalized evidence without writing or connecting to PSCAD."""
    ledger = _Ledger()
    coordinator = ledger.read(coordinator_ref["path"], coordinator_ref["sha256"])
    build = ledger.read(build_ref["path"], build_ref["sha256"])
    _validate_terminal_records(coordinator, build)
    plan = build["plan"]
    blank_service._verify_frozen_plan(plan)
    root, public_root = Path(coordinator["root"]).resolve(), Path(plan["workspace"]).resolve()
    _require(public_root == root / "public" and Path(coordinator["report_path"]).resolve() == Path(coordinator_ref["path"]).resolve(), "The coordinator belongs to another workspace")
    _require(Path(build_ref["path"]).resolve() == AtomicJournal(public_root, build["build_id"]).path, "The build journal is not in its owned directory")
    _require(coordinator["public_plan"] == plan and coordinator["public"]["request_sha256"] == coordinator["request_sha256"], "Coordinator plan/request binding differs")
    request = ledger.read(root / "request.json", coordinator["request_sha256"], within=root)
    _require(request["public_plan"] == plan and request["b_handoff"] == coordinator["b_handoff"]["file"], "The coordinator request changed its accepted inputs")
    _verify_runtime(coordinator["public"], coordinator["public"]["ownership"], coordinator["request_sha256"])
    provenance = _producer_context(plan, historical_snapshot, source_revision, ledger)
    _recorded_refs(plan["source_identities"], ledger)
    _recorded_refs(plan["compiler_support"], ledger)
    _recorded_refs(plan["line_constants"], ledger)
    _recorded_refs(build.get("dependency_copies", []), ledger)
    _recorded_refs(build.get("lineage", []), ledger)
    _recorded_refs(build.get("line_generation", []), ledger)
    _recorded_refs(request["b_handoff"], ledger)
    blank_service._verify_copies(build["dependency_copies"])
    result = build["result"]
    project = Path(result["project_file"]).resolve()
    _require(project == Path(plan["staging_path"]) / Path(plan["target_path"]).name, "The tested public project is outside its staging directory")
    bundle = project.with_suffix(".bundle")
    ledger.check(project, result["tested_project_sha256"], within=public_root)
    replay = result["reload"]
    replay_root = public_root / ".pscad-mcp/mmc-replays" / build["build_id"]
    _require(Path(replay["workspace"]).resolve() == replay_root, "The replay workspace differs from the reviewed owned directory")
    supervisor = ledger.read(replay["supervisor_report_path"], replay["supervisor_report_sha256"], within=replay_root)
    _require(Path(replay["supervisor_report_path"]).resolve() == replay_root / "supervisor-report.json", "The supervisor report belongs to another worker")
    expected = copy.deepcopy(supervisor)
    expected["supervisor_report_sha256"] = replay["supervisor_report_sha256"]
    expected["workspace"] = str(replay_root)
    expected["artifacts"]["supervisor-report.json"] = {"path": str(replay_root / "supervisor-report.json"), "sha256": replay["supervisor_report_sha256"]}
    _require(expected == replay, "The public replay result differs from its frozen supervisor report")
    _require(Path(replay["report_path"]).resolve() == replay_root / "worker/report.json", "The worker report belongs to another replay")
    worker = ledger.read(replay["report_path"], replay["report_sha256"], within=replay_root)
    _require(all(supervisor.get(key) == value for key, value in worker.items()), "The supervisor differs from its frozen worker evidence")
    _require(native_fault_replay._worker_matches_launcher(worker, supervisor["launcher_pid"]), "The worker is not bound to its recorded launcher")
    replay_request = ledger.read(replay_root / "request.json", worker["request_sha256"], within=replay_root)
    _require(replay_request["project"] == {"path": str(project), "sha256": result["tested_project_sha256"]}, "The replay request used another first-run project")
    _require(replay_request["settings"] == plan["settings"] and replay_request["source_identities"] == plan["source_identities"] and replay_request["checks_contract"] == plan["checks_contract"] and replay_request["checks_sha256"] == plan["checks_sha256"], "Replay plan/check/source lineage differs")
    _require(Path(replay_request["bundle"]["path"]).resolve() == bundle and native_fault_replay._files(bundle) == replay_request["bundle"]["source_snapshot"], "The original replay input bundle changed")
    for relative, digest in replay_request["bundle"]["source_snapshot"].items():
        ledger.check(blank_service._bundle_file(bundle, relative), digest, within=bundle)
    dependencies = {Path(item["path"]).relative_to(bundle).as_posix(): item["sha256"] for item in build["dependency_copies"]}
    _require(replay_request["bundle"]["files"] == dependencies, "The replay dependency set differs from the original build")
    _require(worker["copied_project_sha256"] == result["tested_project_sha256"] and replay["project_sha256"] == result["tested_project_sha256"] and worker["checks_sha256"] == plan["checks_sha256"], "The replay copied model or physical checks differ")
    for observed in (worker["copied_bundle_hashes"], supervisor["supervisor_dependency_hashes"], *worker["dependency_snapshots"].values()):
        _require(observed == dependencies, "The replay dependency snapshots are inconsistent")
    _require(native_fault_replay._dependency_hashes(replay_root / "worker" / bundle.name, dependencies) == dependencies, "The actual replay dependencies changed")
    for relative, item in replay["artifacts"].items():
        artifact = blank_service._bundle_file(replay_root, relative)
        _require(artifact == Path(item["path"]).resolve(), "A replay artifact escaped its owned directory")
        ledger.check(artifact, item["sha256"], within=replay_root)
    _require(native_fault_replay._files(replay_root) == {key: ref["sha256"] for key, ref in replay["artifacts"].items()}, "The replay artifact set is incomplete or changed")
    ownership_path = replay_root / "worker/ownership.json"
    ownership = ledger.read(ownership_path, replay["artifacts"]["worker/ownership.json"]["sha256"], within=replay_root)
    _require(worker["cleanup_ownership"] == ownership and worker.get("run_completed") is True and worker.get("replay_saved_model_verified") is True and worker.get("acceptance", {}).get("verdict") == "PASS", "The replay model/run/physical evidence is incomplete")
    _verify_runtime(worker, ownership, worker["request_sha256"])
    cases = {}
    for name, record, case_project in (("public", build, project), ("replay", worker, replay_root / "worker" / project.name)):
        values = record["result"]
        contract = ledger.read(values["channel_contract_path"], values["channel_contract_sha256"], within=case_project.parent)
        index = ledger.read(values["output_index_path"], values["output_index_sha256"], within=case_project.parent)
        archived = ledger.read(values["samples_path"], values["samples_sha256"], within=case_project.parent)
        ledger.check(case_project, values["tested_project_sha256"], within=case_project.parent)
        _require(contract["required_checks"] == plan["checks_contract"] and archived["identity"] == index, "Archived samples/checks differ from the frozen case")
        _require(Path(index["primary"]).name == case_project.stem + "_01.out" and index["started_after"] == record["run_started_after"], "A case dataset belongs to another run")
        blank_service.verify_output_dataset(index)
        blank_service.verify_fault_instrumentation(case_project, contract)
        _verify_saved_settings(case_project, plan)
        for ref in index["files"].values():
            ledger.check(ref["path"], ref["sha256"], within=case_project.parent)
        cases[name] = {"project": case_project, "contract": contract, "index": index, "archived": archived, "acceptance": record["result"]["acceptance"] if name == "public" else record["acceptance"]}
    _require(replay_request["channel_contract"] == cases["public"]["contract"] and replay_request["channel_contract_sha256"] == native_fault_replay._json_hash(cases["public"]["contract"]) and worker["parent_channel_contract_sha256"] == replay_request["channel_contract_sha256"], "Replay channel contract lineage differs")
    _require(worker["replay_channel_contract"] == cases["replay"]["contract"] and worker["output_identity"] == cases["replay"]["index"] and worker["frozen_output_identity_sha256"] == native_fault_replay._json_hash(cases["replay"]["index"]), "The replay's final contracts differ from its frozen files")
    native_fault_replay._verify_replay_saved_model(project, cases["replay"]["project"], cases["replay"]["contract"])
    partial = project.parent / "publication-candidate"
    partial_files = native_fault_replay._files(partial) if partial.exists() else None
    if partial_files is not None:
        for relative, digest in partial_files.items():
            ledger.check(blank_service._bundle_file(partial, relative), digest, within=partial)
    ledger.recheck()
    return {"coordinator": coordinator, "build": build, "plan": plan, "root": root, "public_root": public_root, "project": project, "bundle": bundle, "replay_root": replay_root, "cases": cases, "ledger": ledger, "provenance": provenance, "preserved_failed_publication": {"root": str(partial), "files": partial_files}}


def _reader():
    return PscadAdapter(robust_executor, pscad_module=False, psout_module=False, environ={}).read_psout


async def reevaluate_completed_cases(context):
    summaries = {}
    reader = _reader()
    plan = context["plan"]
    for name, case in context["cases"].items():
        samples = await blank_service.read_fault_output_dataset(reader, case["index"]["primary"], case["contract"], started_after=case["index"]["started_after"])
        _require(native_fault_replay._json_hash(samples) == native_fault_replay._json_hash(case["archived"]), "Re-read samples differ from the archived complete " + name + " dataset")
        acceptance = blank_service.evaluate_template_native_dc_fault(samples, channel_contract=case["contract"], checks_contract=plan["checks_contract"], fault_current_limit_ka=plan["checks_contract"]["fault_current_limit_ka"], topology=SubmoduleTopology(plan["request"]["submodule_topology"]))
        _require(acceptance.get("verdict") == "PASS" and native_fault_replay._json_hash(acceptance) == native_fault_replay._json_hash(case["acceptance"]), "Fresh physical evaluation differs from the recorded " + name + " acceptance")
        blank_service.verify_output_dataset(case["index"])
        summaries[name] = {"verdict": "PASS", "channel_count": len(samples["channels"]), "acceptance": acceptance}
    context["ledger"].recheck()
    return summaries


def _verify_versioned_code(provenance):
    root = Path(__file__).resolve().parents[1]
    revision = provenance["publication_revision"]
    for ref in provenance["publication_code_identities"].values():
        path = Path(ref["path"])
        blob = _git("show", revision + ":" + path.relative_to(root).as_posix())
        _require(path.read_bytes().replace(b"\r\n", b"\n") == blob.replace(b"\r\n", b"\n"), "Publication code is not the recorded committed revision")


def _check_preserved_partial(reference):
    root = Path(reference["root"])
    observed = native_fault_replay._files(root) if root.exists() else None
    _require(observed == reference["files"], "The original failed publication candidate changed")


def _finalize_recovery(report, leases, journal, successful):
    errors = report.setdefault("finalization_errors", [])

    def failed(stage, error):
        errors.append({"stage": stage, "type": type(error).__name__, "message": str(error)})
        report.setdefault("error", {"type": type(error).__name__, "message": str(error)})

    report["status"] = "FAIL"
    report["history"].append("finalizing")
    try:
        journal.write(report)
    except BaseException as error:  # noqa: BLE001 - journal I/O must never skip owned lease release
        failed("finalizing_journal", error)
    retained = False
    for lease in reversed(leases):
        try:
            _require(lease.release(lease.token) is True, "The owned publication lease was not released")
        except BaseException as error:  # noqa: BLE001 - retain only the lease whose release failed
            retained = True
            failed("lease_release", error)
    report["lease_retained"] = retained
    if successful and not errors:
        report["status"] = "PASS"
    report["history"].append("finished")
    try:
        journal.write(report)
    except BaseException as error:  # noqa: BLE001 - preserve the last durable non-PASS checkpoint
        failed("final_journal", error)
        report["status"] = "FAIL"
        try:
            journal.write(report)
        except BaseException as retry_error:  # noqa: BLE001 - the return value must retain failed finalization
            failed("failure_journal", retry_error)


async def resume_publication(coordinator_ref, build_ref, historical_snapshot, source_revision, workspace):
    output = Path(workspace).expanduser()
    _require(output.is_absolute(), "The recovery report workspace must be absolute")
    output = output.resolve()
    original = _Ledger().read(coordinator_ref["path"], coordinator_ref["sha256"])
    original_root = Path(original["root"]).resolve()
    _require(not output.is_relative_to(original_root) and not original_root.is_relative_to(output), "The new recovery report must not overlap the original attempt")
    for ancestor in (output, *output.parents):
        try:
            _require(not _is_reparse_point(ancestor.lstat()), "The recovery report must not traverse links")
        except FileNotFoundError:
            pass
    output.mkdir(parents=True, exist_ok=False)
    attempt_id = uuid4().hex
    journal = AtomicJournal(output, attempt_id)
    report = {"schema_version": 1, "scope": "public_mmc_publication_recovery", "status": "FAIL", "history": [], "publication_attempt_id": attempt_id, "report_path": str(journal.path), "source_attempt": {"coordinator": copy.deepcopy(coordinator_ref), "public_build": copy.deepcopy(build_ref)}, "supersedes": {"stage": "publication_only", "original_attempt_status": "FAIL", "public_build": copy.deepcopy(build_ref)}, "pscad_launched": False, "lease_retained": False}
    leases = []
    successful = False

    def checkpoint(stage):
        report["history"].append(stage)
        journal.write(report)

    try:
        checkpoint("validating_completed_evidence")
        context = load_completed_evidence(coordinator_ref, build_ref, historical_snapshot, source_revision)
        report["provenance"] = context["provenance"]
        _verify_versioned_code(context["provenance"])
        report["b_handoff"] = copy.deepcopy(context["coordinator"]["b_handoff"]["file"])
        report["preserved_failed_publication"] = context["preserved_failed_publication"]
        target = Path(context["plan"]["target_path"])
        _require(not target.exists() and not target.is_symlink() and not target.with_suffix(".bundle").exists() and not target.with_suffix(".bundle").is_symlink(), "The final publication target is already occupied")
        for root in (context["root"], context["public_root"]):
            leases.append(WorkspaceBuildLease.acquire(root, attempt_id))
            report["lease_retained"] = True
        checkpoint("rechecking_physics")
        report["reevaluation"] = await reevaluate_completed_cases(context)
        plan = context["plan"]
        candidate = blank_service._native_attempt_workspace(plan, context["public_root"], attempt_id, "mmc-publications")
        record = copy.deepcopy(context["build"])
        record["build_id"] = attempt_id
        report["publication_workspace"] = str(candidate)
        checkpoint("publishing")
        report["publication"] = blank_service._publish_tested_fault_case(plan, context["project"], context["bundle"], context["cases"]["public"]["contract"], record, replay_workspace=context["replay_root"], publication_workspace=candidate)
        checkpoint("validating_published_copy")
        service = blank_service.BlankMmcBuilderService(SimpleNamespace(read_output_file=_reader()), workspace_root=context["public_root"])
        validation = service.validate_model(plan["target_path"])
        _require(validation.get("accepted") is True and validation["acceptance"]["verdict"] == "PASS", "The published model did not pass fresh validation")
        context["ledger"].recheck()
        _check_preserved_partial(context["preserved_failed_publication"])
        report["published_validation"] = validation
        report["verified_input_files"] = context["ledger"].files
        report["published_project"] = blank_service._identity(Path(plan["target_path"]))
        report["publication_manifest"] = blank_service._identity(Path(report["publication"]["publication_manifest"]))
        successful = True
    except BaseException as error:  # noqa: BLE001 - preserve failed recovery independently of original journals
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        _finalize_recovery(report, leases, journal, successful)
    return report


def _validate_recovery_sources(report, ledger):
    coordinator_ref, build_ref = report["source_attempt"]["coordinator"], report["source_attempt"]["public_build"]
    coordinator = ledger.read(coordinator_ref["path"], coordinator_ref["sha256"])
    build = ledger.read(build_ref["path"], build_ref["sha256"])
    _validate_terminal_records(coordinator, build)
    root = Path(coordinator["root"])
    request = ledger.read(root / "request.json", coordinator["request_sha256"], within=root)
    _require(report["b_handoff"] == coordinator["b_handoff"]["file"] == request["b_handoff"], "The recovery receipt replaced its accepted B handoff")
    _require(coordinator["public_plan"] == request["public_plan"] == build["plan"], "The recovery source records disagree about the original plan")
    return coordinator, build


async def validate_publication_recovery(reference):
    """Recheck one frozen recovery receipt before a newly prepared joint run."""
    ledger = _Ledger()
    report = ledger.read(reference["path"], reference["sha256"])
    _require(report.get("schema_version") == 1 and report.get("scope") == "public_mmc_publication_recovery" and report.get("status") == "PASS", "The publication recovery receipt did not pass")
    _require(report.get("history", [])[-1:] == ["finished"] and report.get("lease_retained") is False and report.get("pscad_launched") is False and not report.get("error") and not report.get("finalization_errors"), "The publication recovery receipt is unfinished")
    _require(report.get("supersedes") == {"stage": "publication_only", "original_attempt_status": "FAIL", "public_build": report["source_attempt"]["public_build"]}, "The recovery receipt changed its acceptance scope")
    _require(set(report["reevaluation"]) == {"public", "replay"} and all(value.get("verdict") == "PASS" and value.get("acceptance", {}).get("verdict") == "PASS" for value in report["reevaluation"].values()), "The recovery receipt lacks both physical re-evaluations")
    for path, digest in report["verified_input_files"].items():
        ledger.check(path, digest)
    _recorded_refs(report["source_attempt"], ledger)
    _recorded_refs(report["provenance"]["publication_code_identities"], ledger)
    _recorded_refs(report["provenance"]["recovered_blank_service"], ledger)
    _recorded_refs(report["b_handoff"], ledger)
    _check_preserved_partial(report["preserved_failed_publication"])
    _coordinator, build = _validate_recovery_sources(report, ledger)
    _require(report["provenance"]["execution_producer_identities"] == build["plan"]["model_recipe"]["producer_code_hashes"], "The recovery receipt rewrote the original execution provenance")
    _require(report["provenance"]["recovered_blank_service"]["sha256"] == build["plan"]["model_recipe"]["producer_code_hashes"]["blank_service"]["sha256"], "The historical producer snapshot changed")
    project = ledger.check(report["published_project"]["path"], report["published_project"]["sha256"])
    manifest = ledger.check(report["publication_manifest"]["path"], report["publication_manifest"]["sha256"])
    publication, _contract, _checks, _index = blank_service._load_publication_evidence(Path(project["path"]))
    _require(publication["plan"] == build["plan"] and project["path"] == build["plan"]["target_path"] and Path(manifest["path"]) == Path(project["path"]).with_suffix(".bundle") / "manifest.json", "The recovered publication differs from its original frozen plan")
    service = blank_service.BlankMmcBuilderService(SimpleNamespace(read_output_file=_reader()), workspace_root=build["plan"]["workspace"])
    validation = service.validate_model(project["path"])
    _require(validation.get("accepted") is True and native_fault_replay._json_hash(validation) == native_fault_replay._json_hash(report["published_validation"]), "Fresh publication validation differs from the recovery receipt")
    ledger.recheck()
    return {"receipt": copy.deepcopy(reference), "project": project, "manifest": manifest, "plan": copy.deepcopy(publication["plan"]), "b_handoff": copy.deepcopy(report["b_handoff"]), "validation": validation}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coordinator", type=Path, required=True)
    parser.add_argument("--coordinator-sha256", required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--build-sha256", required=True)
    parser.add_argument("--historical-blank-service", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(resume_publication({"path": str(args.coordinator.resolve()), "sha256": args.coordinator_sha256}, {"path": str(args.build.resolve()), "sha256": args.build_sha256}, args.historical_blank_service.resolve(), args.source_revision, args.workspace))
    print(json.dumps({"status": report["status"], "report_path": report["report_path"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
