"""Opt-in owned public and joint MMC acceptance with a fixed replay worker."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psutil

from pscad_mcp.acceptance.preflight_cli import _service
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.executor import robust_executor
from pscad_mcp.core.pscad_adapter import PscadAdapter
from pscad_mcp.hvdc.builders.mmc import native_fault_replay, timed_control
from pscad_mcp.hvdc.builders.mmc.blank_service import (
    BlankMmcBuilderService,
    _copy_frozen,
    _identity,
    _read_hashed_json,
    _run_native_fault_case,
    _verify_runtime_master,
    _write_evidence,
)
from pscad_mcp.hvdc.builders.mmc.fault_channels import (
    finalize_fault_instrumentation,
    verify_fault_instrumentation,
    verify_output_dataset,
)
from pscad_mcp.hvdc.builders.mmc.journal import AtomicJournal, WorkspaceBuildLease
from tests.mmc_timing_fault_case import (
    _digest,
    evaluate_joint_dataset,
    prepare_joint_case,
    require_same_dataset,
    verify_joint_preparation,
)


def _error(code, message):
    return BackendError(code, message, "acceptance", "mmc_public_joint_acceptance")


def require_recipe_match(b_recipe, public_recipe):
    from tests.mmc_b_handoff import require_recipe_match as compare

    return compare(b_recipe, public_recipe)


def _reader():
    return PscadAdapter(
        robust_executor, pscad_module=False, psout_module=False, environ={}
    ).read_psout


async def _validate_b(path):
    from tests.mmc_b_handoff import validate_b_handoff

    try:
        return await validate_b_handoff(path, _reader())
    except (BackendError, OSError, ValueError, KeyError, TypeError) as error:
        raise _error(
            "MMC_B_HANDOFF_NOT_ACCEPTED", "B handoff verification failed: " + str(error)
        ) from error


def _check_ref(reference):
    observed = _identity(Path(reference["path"]))
    if observed != reference:
        raise ValueError("A frozen acceptance input changed: " + reference["path"])
    return observed


async def _close_owned_service(service, ownership, record):
    quit_task = None
    try:
        ownership = ownership or native_fault_replay._capture_ownership(
            service, record["request_sha256"]
        )
        if ownership is None:
            uncertain = record.get("attach_started") is True
            record.update(
                {
                    "owned_process_cleaned": not uncertain,
                    "cleanup_pending": uncertain,
                    "attach_outcome_uncertain": uncertain,
                    "ownership_status": "launch_identity_unconfirmed"
                    if uncertain
                    else "no_launch_attempted",
                }
            )
            return
        record["ownership"] = ownership
        try:
            quit_task = asyncio.create_task(service.quit_pscad(confirm=True))
            await asyncio.wait_for(quit_task, timeout=30)
            process = psutil.Process(ownership["pid"])
            if process.create_time() == ownership["created_at"]:
                await asyncio.to_thread(process.wait, 10)
            record.update({"owned_process_cleaned": True, "cleanup_pending": False})
        except psutil.NoSuchProcess:
            record.update({"owned_process_cleaned": True, "cleanup_pending": False})
        except BaseException as error:  # noqa: BLE001 - cleanup still owns only the captured process
            record["graceful_cleanup_error"] = str(error)
            record.update(await native_fault_replay._terminate_owned_pscad(ownership))
    except BaseException as error:  # noqa: BLE001 - unknown ownership is retained, never guessed
        record.update(
            {
                "owned_process_cleaned": False,
                "cleanup_pending": True,
                "cleanup_error": str(error),
            }
        )
    finally:
        try:
            record["pending_vendor_calls"] = native_fault_replay._pending_owned_calls(
                service, asyncio.current_task(), quit_task
            )
            if record["pending_vendor_calls"]:
                record.update({"owned_process_cleaned": False, "cleanup_pending": True})
        except BaseException as error:  # noqa: BLE001 - settlement uncertainty survives a missing backend handle
            record.update(
                {
                    "owned_process_cleaned": False,
                    "cleanup_pending": True,
                    "settlement_error": str(error),
                }
            )


async def _owned_phase(
    root, name, request_hash, source_ids, operation, report, checkpoint, service_factory
):
    phase = {
        "status": "FAIL",
        "request_sha256": request_hash,
        "owned_process_cleaned": False,
        "cleanup_pending": True,
    }
    report[name] = phase
    service = None
    ownership = None
    checkpoint(name + "_starting")
    try:
        service = service_factory(root)
        phase["attach_started"] = True
        await service.attach_local()
        phase["attach_completed"] = True
        ownership = native_fault_replay._capture_ownership(service, request_hash)
        if ownership is None:
            raise RuntimeError(
                "The acceptance phase has no verified owned PSCAD instance"
            )
        phase["ownership"] = ownership
        phase["runtime"] = await service.status()
        phase["runtime_master"] = await _verify_runtime_master(
            service, source_ids["master"]
        )
        checkpoint(name + "_connected")
        await operation(service, phase)
        phase["status"] = "PASS"
    except BaseException as error:
        phase["error"] = (
            error.to_dict()
            if isinstance(error, BackendError)
            else {"type": type(error).__name__, "message": str(error)}
        )
        raise
    finally:
        if service is not None:
            await _close_owned_service(service, ownership, phase)
        else:
            phase.update({"owned_process_cleaned": True, "cleanup_pending": False})
        phase["service_cleanup"] = {
            "owned_process_cleaned": phase["owned_process_cleaned"],
            "cleanup_pending": phase["cleanup_pending"],
        }
        replay_pending = "reload" in phase and (
            not isinstance(phase["reload"], Mapping)
            or phase["reload"].get("owned_process_cleaned") is not True
            or bool(phase["reload"].get("cleanup_pending"))
        )
        phase["cleanup_pending"] = bool(
            phase["cleanup_pending"]
            or phase.get("builder_cleanup_pending")
            or replay_pending
        )
        phase["owned_process_cleaned"] = (
            phase["service_cleanup"]["owned_process_cleaned"] is True
            and not phase["cleanup_pending"]
        )
        if phase["cleanup_pending"]:
            phase["status"] = "FAIL"
        checkpoint(name + "_closed")
    if phase["status"] != "PASS":
        raise RuntimeError("Owned phase cleanup did not complete: " + name)


def verify_joint_saved_child(context, project, contract):
    if (
        context.get("scope") != "joint_timing_fault"
        or context.get("schema_version") != 1
    ):
        raise ValueError(
            "The fixed joint worker has no recognized verification context"
        )
    _check_ref(context["b_handoff"])
    _check_ref(context["first_saved_model"])
    preparation = context["preparation"]
    first_contract = context["first_saved_fault_contract"]
    verify_joint_preparation(preparation, saved_fault_contract=first_contract)
    if (
        Path(preparation["project"]["path"]).resolve()
        != Path(context["first_saved_model"]["path"]).resolve()
        or first_contract["instrumented_project_sha256"]
        != context["first_saved_model"]["sha256"]
    ):
        raise ValueError("The joint replay does not identify the first saved model")

    expected = copy.deepcopy(first_contract)
    expected["project_path"] = str(project)
    expected["readback"]["project_path"] = str(project)
    expected["vendor_finalized"] = False
    expected.pop("virtual_root_rebinding", None)
    expected["replay_parent_contract_sha256"] = _digest(first_contract)
    expected = finalize_fault_instrumentation(project, expected)
    if expected != contract:
        raise ValueError(
            "The child fault contract differs from the complete first-save lineage"
        )
    native_fault_replay._verify_replay_saved_model(
        Path(context["first_saved_model"]["path"]), project, contract
    )
    timing = timed_control.verify_embedded_control(preparation["schedule"], project)
    verify_fault_instrumentation(project, contract)
    return {
        "verdict": "PASS",
        "raw_to_first_saved_sha256": context["first_saved_model"]["sha256"],
        "first_to_child_saved_sha256": _identity(project)["sha256"],
        "timing_readback": timing,
        "schedule_sha256": preparation["schedule"]["schedule_sha256"],
    }


def verify_joint_child_dataset(context, project, contract, samples):
    saved = verify_joint_saved_child(context, project, contract)
    identity = samples["identity"]
    verify_output_dataset(identity)
    timing = timed_control.read_event_evidence(
        context["preparation"]["schedule"],
        project,
        [
            item["path"]
            for name, item in identity["files"].items()
            if name.casefold().endswith(".out")
        ],
        started_after=identity["started_after"],
    )
    require_same_dataset(identity, timing)
    verify_output_dataset(identity)
    return {
        "verdict": "PASS",
        "saved_validation": saved,
        "timing": timing,
        "output_identity": copy.deepcopy(identity),
    }


async def run_joint_replay(preparation, saved_contract, b_ref, workspace):
    project = Path(preparation["project"]["path"])
    verify_joint_preparation(preparation, saved_fault_contract=saved_contract)
    context = {
        "schema_version": 1,
        "scope": "joint_timing_fault",
        "b_handoff": b_ref,
        "preparation": preparation,
        "first_saved_model": _identity(project),
        "first_saved_fault_contract": saved_contract,
    }
    bundle = project.with_suffix(".bundle")
    dependencies = {
        Path(item["path"]).relative_to(bundle).as_posix(): item["sha256"]
        for item in preparation["dependency_copies"]
    }
    result = await native_fault_replay.verify_native_fault_replay(
        project=project,
        bundle=bundle,
        channel_contract=saved_contract,
        checks_contract=preparation["checks"],
        settings=preparation["public_plan"]["settings"],
        source_identities=preparation["public_plan"]["source_identities"],
        dependency_files=dependencies,
        workspace=workspace,
        verification_context=context,
        worker_module="tests.mmc_joint_acceptance",
    )
    if result.get("status") == "PASS":
        try:
            child = Path(workspace) / "worker" / project.name
            repeated = verify_joint_child_dataset(
                context,
                child,
                result["replay_channel_contract"],
                {"identity": result["output_identity"]},
            )
            if repeated != result.get("supplemental_evidence"):
                raise ValueError(
                    "The supervisor's fresh joint read differs from the child evidence"
                )
        except BaseException as error:  # noqa: BLE001 - retain the completed worker's actual cleanup state
            result.update(
                {
                    "status": "FAIL",
                    "joint_supervisor_error": {
                        "type": type(error).__name__,
                        "message": str(error),
                    },
                }
            )
    return result


def _capture_builder_cleanup(builder, phase, stage):
    snapshot = {"stage": stage}
    try:
        build_id = phase.get("build_id")
        statuses = getattr(builder, "_statuses", None)
        if build_id is None and isinstance(statuses, Mapping) and len(statuses) == 1:
            build_id = next(iter(statuses))
            phase["build_id"] = build_id
        pending = bool(getattr(builder, "_leases", {})) or any(
            not item.done()
            for name in ("_cleanup_waiters", "_cleanup_tasks", "_tasks")
            for item in getattr(builder, name, {}).values()
        )
        if build_id is None:
            if not isinstance(statuses, Mapping) or statuses:
                raise RuntimeError("The builder's admitted work cannot be identified")
            snapshot["no_build_admitted"] = True
        else:
            build = builder.get_build_status(build_id)
            phase["build"] = copy.deepcopy(build)
            snapshot["build"] = copy.deepcopy(build)
            result = build.get("result")
            result = result if isinstance(result, Mapping) else {}
            reload = result.get("reload")
            if isinstance(reload, Mapping):
                phase["reload"] = copy.deepcopy(dict(reload))
                pending = (
                    pending
                    or reload.get("cleanup_pending") is True
                    or reload.get("owned_process_cleaned") is not True
                )
            containment = build.get("containment", {})
            pending = (
                pending
                or build.get("lease_retained") is True
                or bool(build.get("pending_vendor_calls"))
                or containment.get("confirmed") is False
            )
            if (
                build.get("run_started")
                and not build.get("run_completed")
                and containment.get("confirmed") is not True
            ):
                pending = True
        snapshot["cleanup_pending"] = pending
    except BaseException as error:  # noqa: BLE001 - unreadable builder state cannot prove cleanup
        pending = True
        snapshot.update(
            {
                "cleanup_pending": True,
                "error": {"type": type(error).__name__, "message": str(error)},
            }
        )
    phase.setdefault("builder_cleanup_snapshots", []).append(snapshot)
    return pending


async def _run_public(service, phase, accepted, public_root, request, plan, checkpoint):
    builder = BlankMmcBuilderService(service, workspace_root=public_root)
    failure = None
    try:
        ticket = await builder.build_model(request, plan["plan_hash"], confirm=True)
        phase["build_id"] = ticket["build_id"]
        await builder._tasks[ticket["build_id"]]
        build = builder.get_build_status(ticket["build_id"])
        phase["build"] = build
        phase["reload"] = build.get("result", {}).get("reload", {})
        if build["state"] != "published":
            raise _error(
                "MMC_PUBLIC_ACCEPTANCE_FAILED",
                "The public builder did not publish its tested and independently replayed case",
            )
        validation = builder.validate_model(plan["target_path"])
        phase["validation"] = validation
        if validation.get("accepted") is not True:
            raise _error(
                "MMC_PUBLIC_ACCEPTANCE_FAILED",
                "Public validation did not accept its frozen published evidence",
            )
        _check_ref(accepted["file"])
        checkpoint("public_validated")
    except BaseException as error:  # noqa: BLE001 - preserve the original failure while settling the builder
        failure = error
    finally:
        _capture_builder_cleanup(builder, phase, "before_shutdown")
        shutdown_failed = False
        try:
            await builder.shutdown(timeout_s=15)
        except BaseException as error:  # noqa: BLE001 - independent builder/replay cleanup remains authoritative
            shutdown_failed = True
            phase["builder_cleanup_error"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
            failure = failure or error
        pending = _capture_builder_cleanup(builder, phase, "after_shutdown")
        phase["builder_cleanup_pending"] = shutdown_failed or pending
    if failure is not None:
        raise failure
    if phase["builder_cleanup_pending"]:
        raise RuntimeError("The public builder did not confirm all internal cleanup")


async def _run_joint(service, phase, accepted, preparation, checkpoint):
    project = Path(preparation["project"]["path"])
    library = (
        project.with_suffix(".bundle")
        / Path(preparation["public_plan"]["source_identities"]["library"]["path"]).name
    )
    phase.update({"result": {}, "history": []})

    def case_checkpoint(stage):
        phase["history"].append(stage)
        if stage == "saved_and_bound":
            saved = _read_hashed_json(
                Path(phase["result"]["channel_contract_path"]),
                phase["result"]["channel_contract_sha256"],
            )
            verify_joint_preparation(preparation, saved_fault_contract=saved)
        checkpoint("joint_" + stage)

    contract, samples = await _run_native_fault_case(
        service,
        project,
        library,
        copy.deepcopy(preparation["fault_contract"]),
        preparation["checks"],
        preparation["public_plan"]["settings"],
        project.parent / "evidence",
        phase,
        case_checkpoint,
    )
    analysis = await evaluate_joint_dataset(
        preparation, service.read_output_file, contract, samples["identity"]
    )
    phase["analysis"] = analysis
    if analysis["verdict"] != "PASS":
        raise _error(
            "MMC_JOINT_ACCEPTANCE_FAILED",
            "The first joint dataset did not pass both timing and fault checks",
        )
    phase["first_saved_model"] = _identity(project)
    phase["first_saved_fault_contract"] = copy.deepcopy(contract)
    phase["output_identity"] = copy.deepcopy(samples["identity"])
    snapshot = project.parent / "evidence" / "first-saved" / project.name
    _copy_frozen(project, snapshot, phase["first_saved_model"]["sha256"])
    phase["first_saved_snapshot"] = _identity(snapshot)
    _check_ref(accepted["file"])
    phase["reload"] = {
        "status": "FAIL",
        "cleanup_pending": True,
        "owned_process_cleaned": False,
    }
    checkpoint("joint_replay_requested")
    phase["reload"] = await run_joint_replay(
        preparation, contract, accepted["file"], project.parent / "reload"
    )
    if (
        phase["reload"].get("status") != "PASS"
        or phase["reload"].get("owned_process_cleaned") is not True
        or phase["reload"].get("cleanup_pending")
    ):
        raise _error(
            "MMC_JOINT_ACCEPTANCE_FAILED",
            "The independent joint worker did not pass and finish owned cleanup",
        )


async def run_public_joint_acceptance(
    handoff_path, workspace, *, service_factory=_service
):
    raw_root = Path(workspace).expanduser()
    if not raw_root.is_absolute():
        raise ValueError("Acceptance workspace must be absolute")
    root = raw_root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    run_id = uuid4().hex
    journal = AtomicJournal(root, run_id)
    report = {
        "schema_version": 1,
        "scope": "public_and_joint_mmc",
        "status": "FAIL",
        "history": [],
        "physical_acceptance_verified": False,
        "python_pid": os.getpid(),
        "root": str(root),
        "owned_process_cleaned": True,
        "cleanup_pending": False,
        "report_path": str(journal.path),
    }
    lease = None
    previous_concurrent = os.environ.get("PSCAD_MCP_ACCEPTANCE_CONCURRENT")

    def checkpoint(stage):
        report["history"].append(stage)
        journal.write(report)

    try:
        checkpoint("preflight")
        if os.getenv("PSCAD_MCP_MMC_ACCEPTANCE") != "1":
            raise _error(
                "MMC_ACCEPTANCE_OPT_IN_REQUIRED",
                "PSCAD_MCP_MMC_ACCEPTANCE=1 is required before licensed public/joint execution",
            )
        accepted = await _validate_b(handoff_path)
        report["b_handoff"] = accepted
        source_ids = accepted["source_hashes"]
        recipe = accepted["recipe"]["id"]
        request = {
            "project_name": "PublicFault_" + run_id[:8],
            "template_path": source_ids["project"]["path"],
            "library_path": source_ids["library"]["path"],
            "parameterization": {
                "master_path": source_ids["master"]["path"],
                "model_recipe": recipe,
            },
        }
        public_root = root / "public"
        plan = BlankMmcBuilderService(None, workspace_root=public_root).plan_model(
            request
        )
        require_recipe_match(accepted["recipe"], plan["model_recipe"])
        preparation = await prepare_joint_case(
            root / "joint",
            source=source_ids["project"]["path"],
            library=source_ids["library"]["path"],
            master=source_ids["master"]["path"],
            model_recipe=recipe,
        )
        bound = copy.deepcopy(preparation)
        bound["joint_parents"]["B"] = {
            "accepted": True,
            "handoff": accepted["file"],
            "recipe": accepted["recipe"],
        }
        bound["preparation_sha256"] = _digest(
            {key: value for key, value in bound.items() if key != "preparation_sha256"}
        )
        bound_path = root / "joint" / "accepted-preparation.json"
        _write_evidence(bound_path, bound)
        report["joint_preparation"] = _identity(bound_path)
        report["public_plan"] = plan
        report["request_sha256"] = _write_evidence(
            root / "request.json",
            {
                "b_handoff": accepted["file"],
                "public_plan": plan,
                "joint_preparation": report["joint_preparation"],
            },
        )
        _check_ref(accepted["file"])
        lease = WorkspaceBuildLease.acquire(root, run_id)
        os.environ["PSCAD_MCP_ACCEPTANCE_CONCURRENT"] = "1"
        await _owned_phase(
            public_root,
            "public",
            report["request_sha256"],
            source_ids,
            lambda service, phase: _run_public(
                service, phase, accepted, public_root, request, plan, checkpoint
            ),
            report,
            checkpoint,
            service_factory,
        )
        closed_validation = BlankMmcBuilderService(
            SimpleNamespace(read_output_file=_reader()), workspace_root=public_root
        ).validate_model(plan["target_path"])
        report["public"]["post_close_validation"] = closed_validation
        if closed_validation.get("accepted") is not True:
            raise _error(
                "MMC_PUBLIC_ACCEPTANCE_FAILED",
                "Published public evidence changed during owned cleanup",
            )
        await _owned_phase(
            root / "joint",
            "joint",
            report["request_sha256"],
            source_ids,
            lambda service, phase: _run_joint(
                service, phase, accepted, bound, checkpoint
            ),
            report,
            checkpoint,
            service_factory,
        )
        _check_ref(report["joint"]["first_saved_model"])
        _check_ref(report["joint"]["first_saved_snapshot"])
        verify_joint_preparation(
            bound, saved_fault_contract=report["joint"]["first_saved_fault_contract"]
        )
        verify_output_dataset(report["joint"]["output_identity"])
        checkpoint("post_close_evidence_verified")
        _check_ref(accepted["file"])
        report.update({"status": "PASS", "physical_acceptance_verified": True})
    except BaseException as error:  # noqa: BLE001 - every interrupted/failed phase retains its evidence
        report["error"] = (
            error.to_dict()
            if isinstance(error, BackendError)
            else {
                "code": "MMC_JOINT_RUN_FAILED",
                "type": type(error).__name__,
                "message": str(error),
            }
        )
    finally:
        _finalize_run(report, lease, journal, previous_concurrent)
    return report


def _finalize_run(report, lease, journal, previous_concurrent):
    requested_pass = report.get("status") == "PASS"
    report.update(
        {
            "status": "FAIL",
            "physical_acceptance_verified": False,
            "lease_retained": lease is not None,
        }
    )
    errors = report.setdefault("finalization_errors", [])

    def failed(stage, error):
        errors.append(
            {"stage": stage, "type": type(error).__name__, "message": str(error)}
        )
        if "error" not in report:
            report["error"] = {"code": "MMC_FINALIZATION_FAILED", "message": str(error)}

    try:
        phases = [report[key] for key in ("public", "joint") if key in report]
        report["cleanup_pending"] = any(item.get("cleanup_pending") for item in phases)
        report["owned_process_cleaned"] = (
            all(item.get("owned_process_cleaned") is True for item in phases)
            and not report["cleanup_pending"]
        )
        report["history"].append("finalizing")
        try:
            journal.write(report)
        except BaseException as error:  # noqa: BLE001 - retain a non-PASS checkpoint before resource release
            failed("finalizing_journal", error)
        if lease is not None and not report["cleanup_pending"]:
            try:
                lease.release(lease.token)
                report["lease_retained"] = False
            except BaseException as error:  # noqa: BLE001 - I/O failure does not imply a running process
                failed("lease_release", error)
    except BaseException as error:  # noqa: BLE001 - restoration is unconditional even for malformed cleanup state
        failed("cleanup_state", error)
    finally:
        try:
            if previous_concurrent is None:
                os.environ.pop("PSCAD_MCP_ACCEPTANCE_CONCURRENT", None)
            else:
                os.environ["PSCAD_MCP_ACCEPTANCE_CONCURRENT"] = previous_concurrent
        except BaseException as error:  # noqa: BLE001 - never persist PASS when process-local state was not restored
            failed("environment_restore", error)
    if (
        requested_pass
        and not errors
        and not report.get("cleanup_pending")
        and not report["lease_retained"]
    ):
        report.update({"status": "PASS", "physical_acceptance_verified": True})
    report["history"].append("finished")
    try:
        journal.write(report)
    except BaseException as error:  # noqa: BLE001 - the last durable checkpoint remains non-PASS
        failed("final_journal", error)
        report.update({"status": "FAIL", "physical_acceptance_verified": False})
        try:
            journal.write(report)
        except BaseException as retry_error:  # noqa: BLE001 - return the accurate in-memory failure without hiding the primary cause
            failed("failure_journal", retry_error)


async def _joint_worker(request_path, expected_hash):
    try:
        if os.getenv("PSCAD_MCP_MMC_ACCEPTANCE") != "1":
            raise _error(
                "MMC_ACCEPTANCE_OPT_IN_REQUIRED",
                "The joint worker requires the existing MMC licensed opt-in",
            )
        request = _read_hashed_json(Path(request_path), expected_hash)
        context = request.get("verification_context", {})
        if (
            context.get("scope") != "joint_timing_fault"
            or context.get("schema_version") != 1
        ):
            raise ValueError("The joint request has no recognized verification context")
        _check_ref(context["b_handoff"])
        accepted = await _validate_b(context["b_handoff"]["path"])
        require_recipe_match(
            accepted["recipe"], context["preparation"]["public_plan"]["model_recipe"]
        )
        _check_ref(context["first_saved_model"])
        verify_joint_preparation(
            context["preparation"],
            saved_fault_contract=context["first_saved_fault_contract"],
        )
        if (
            request["project"] != context["first_saved_model"]
            or request["channel_contract"] != context["first_saved_fault_contract"]
            or request["checks_contract"] != context["preparation"]["checks"]
            or request["source_identities"] != accepted["source_hashes"]
        ):
            raise ValueError(
                "The joint worker request differs from the verified first run and B handoff"
            )
    except BaseException as error:  # noqa: BLE001 - a rejected preflight has not launched PSCAD
        root = Path(request_path).parent / "worker"
        root.mkdir()
        report = {
            "schema_version": 1,
            "status": "FAIL",
            "owned_process_cleaned": True,
            "cleanup_pending": False,
            "python_pid": os.getpid(),
            "worker_parent_pid": os.getppid(),
            "request_sha256": expected_hash,
            "phase": "preflight",
            "error": error.to_dict()
            if isinstance(error, BackendError)
            else {"type": type(error).__name__, "message": str(error)},
        }
        _write_evidence(root / "report.json", report)
        return report
    return await native_fault_replay._worker(
        Path(request_path),
        expected_hash,
        saved_verifier=verify_joint_saved_child,
        dataset_verifier=verify_joint_child_dataset,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--request-sha256")
    args = parser.parse_args()
    if args.request is not None:
        report = asyncio.run(_joint_worker(args.request, args.request_sha256))
    else:
        if args.handoff is None or args.workspace is None:
            parser.error("--handoff and --workspace are required")
        report = asyncio.run(run_public_joint_acceptance(args.handoff, args.workspace))
    print(
        json.dumps(
            {"status": report["status"], "report_path": report.get("report_path")}
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
