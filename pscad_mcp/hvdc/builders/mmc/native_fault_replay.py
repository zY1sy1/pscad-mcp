"""Independent owned replay of an already tested native MMC fault project."""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import re
import shutil
import sys
import time
import traceback
from collections.abc import Mapping
from pathlib import Path
from xml.etree import ElementTree as ET

import psutil

from ....acceptance.evidence import _is_reparse_point
from ....acceptance.preflight_cli import _service
from ....acceptance.process_scope import require_acceptance_ownership
from .fault_channels import (
    default_fault_checks,
    verify_fault_instrumentation,
    verify_output_dataset,
)
from .template_native import evaluate_template_native_dc_fault


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")


def _files(root: Path) -> dict[str, str]:
    if not root.is_dir() or _is_reparse_point(root.lstat()):
        raise ValueError("Replay bundle must be a regular directory")
    result = {}
    for path in sorted(root.rglob("*")):
        if _is_reparse_point(path.lstat()) or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Replay inputs must not escape their bundle")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = _hash(path)
    return result


def _dependency_hashes(bundle, expected):
    from .blank_service import _bundle_file

    return {relative: _hash(_bundle_file(bundle, relative)) for relative in expected}


def _frozen_output_index(root, report):
    from .blank_service import _bundle_file, _read_hashed_json

    path = _bundle_file(root, "evidence/output-index.json")
    result = report["result"]
    if Path(result["output_index_path"]).resolve() != path:
        raise ValueError("The replay output index does not belong to this child")
    return _read_hashed_json(path, result["output_index_sha256"])


def _pending_owned_calls(service, *owners):
    getter = getattr(getattr(service, "executor", None), "pending_settlements_for", None)
    if not callable(getter):
        return []
    pending = {}
    for owner in owners:
        if owner is None:
            continue
        for token in getter(owner):
            if not token.settled:
                pending[id(token)] = {"operation_id": getattr(token, "operation_id", None), "generation": getattr(token, "generation", None), "operation": str(getattr(token, "operation", "unknown"))}
    return list(pending.values())


async def _terminate_owned_pscad(ownership):
    """Terminate only a recorded PID with matching birth time and executable."""
    result = {"owned_process_cleaned": False, "cleanup_pending": True}
    try:
        if type(ownership.get("pid")) is not int or ownership["pid"] <= 0:
            raise ValueError("No verified owned PSCAD PID")
        process = psutil.Process(ownership["pid"])
        if process.create_time() != ownership["created_at"]:
            return {"owned_process_cleaned": True, "cleanup_pending": False, "ownership_status": "original_process_exited"}
        expected = Path(ownership["executable"]).resolve()
        if expected.stem.casefold() != "pscad" or Path(process.exe()).resolve() != expected:
            raise ValueError("The owned PSCAD executable identity changed")
        process.terminate()
        try:
            await asyncio.to_thread(process.wait, 5)
        except psutil.TimeoutExpired:
            if process.create_time() != ownership["created_at"]:
                return {"owned_process_cleaned": True, "cleanup_pending": False, "ownership_status": "original_process_exited"}
            process.kill()
            await asyncio.to_thread(process.wait, 5)
        return {"owned_process_cleaned": True, "cleanup_pending": False, "ownership_status": "owned_process_exited"}
    except psutil.NoSuchProcess:
        return {"owned_process_cleaned": True, "cleanup_pending": False, "ownership_status": "owned_process_exited"}
    except (psutil.Error, OSError, KeyError, TypeError, ValueError) as error:
        return {**result, "cleanup_error": str(error)}


def _supervisor_report(root, result):
    result["supervisor_report_path"] = str(root / "supervisor-report.json")
    try:
        if result["status"] == "PASS":
            result["artifacts"] = {name: {"path": str(root / name), "sha256": digest} for name, digest in _files(root).items()}
        _write(Path(result["supervisor_report_path"]), result)
        digest = _hash(Path(result["supervisor_report_path"]))
        if result["status"] == "PASS":
            result["artifacts"]["supervisor-report.json"] = {"path": result["supervisor_report_path"], "sha256": digest}
        return {**result, "supervisor_report_sha256": digest}
    except (OSError, TypeError, ValueError) as error:
        return {**result, "status": "FAIL", "report_write_error": str(error)}


async def _finalize_python_worker(process, communication, root, result):
    errors = []
    if process.returncode is None:
        for command in ("terminate", "kill"):
            try:
                getattr(process, command)()
                await asyncio.wait_for(process.wait(), timeout=10)
                break
            except BaseException as error:  # noqa: BLE001 - preserve termination failures and try the owned fallback
                errors.append({"stage": command, "type": type(error).__name__, "message": str(error)})
    result["worker_exit_code"] = process.returncode
    if process.returncode is None:
        result.update({"python_cleanup_pending": True, "cleanup_pending": True, "owned_process_cleaned": False})
    if communication is not None:
        try:
            output, _ = await asyncio.wait_for(asyncio.shield(communication), timeout=1)
            (root / "worker.log").write_bytes(output)
        except BaseException as error:  # noqa: BLE001 - a broken pipe/log cannot erase ownership evidence
            errors.append({"stage": "worker_log", "type": type(error).__name__, "message": str(error)})
            if not communication.done():
                communication.cancel()
                await asyncio.gather(communication, return_exceptions=True)
    if errors:
        result["status"] = "FAIL"
        result["finalization_errors"] = errors


def _worker_matches_launcher(report, launcher_pid):
    worker_pid, parent_pid = report.get("python_pid"), report.get("worker_parent_pid")
    if any(type(pid) is not int or pid <= 0 for pid in (launcher_pid, worker_pid)):
        return False
    if "worker_parent_pid" in report and (type(parent_pid) is not int or parent_pid <= 0 or parent_pid == worker_pid):
        return False
    # Windows venv python.exe can launch the interpreter as its child.
    return worker_pid == launcher_pid or parent_pid == launcher_pid


async def verify_native_fault_replay(*, project, bundle, channel_contract, checks_contract, settings, source_identities, dependency_files, workspace, verification_context=None, worker_module=None):
    """Launch one fresh worker; request JSON never supplies an alternate verifier."""
    root = Path(workspace).resolve()
    if root.exists():
        raise FileExistsError(str(root))
    root.mkdir(parents=True)
    result = {"status": "FAIL", "owned_process_cleaned": True, "cleanup_pending": False, "worker_launched": False}
    if os.getenv("PSCAD_MCP_MMC_ACCEPTANCE") != "1":
        result["error"] = {"code": "MMC_RELOAD_OPT_IN_REQUIRED", "message": "Independent licensed MMC replay requires PSCAD_MCP_MMC_ACCEPTANCE=1."}
        return _supervisor_report(root, result)
    project, bundle = Path(project).resolve(), Path(bundle).resolve()
    verify_fault_instrumentation(project, channel_contract)
    if checks_contract != default_fault_checks():
        raise ValueError("Replay requires the fixed production physical checks")
    source_bundle_files = _files(bundle)
    if not dependency_files or any(source_bundle_files.get(name) != digest for name, digest in dependency_files.items()):
        raise ValueError("The frozen compiler dependency set changed")
    request = {"schema_version": 1, "project": {"path": str(project), "sha256": _hash(project)},
        "bundle": {"path": str(bundle), "files": dict(dependency_files), "source_snapshot": source_bundle_files}, "channel_contract": channel_contract,
        "channel_contract_sha256": _json_hash(channel_contract), "checks_contract": checks_contract,
        "checks_sha256": _json_hash(checks_contract), "settings": settings, "source_identities": source_identities}
    if verification_context is not None:
        if not isinstance(verification_context, Mapping) or not worker_module:
            raise ValueError("Supplemental verification requires a context and a trusted Python worker entry point")
        request["verification_context"] = copy.deepcopy(dict(verification_context))
        request["verification_context_sha256"] = _json_hash(verification_context)
    elif worker_module is not None:
        raise ValueError("A supplemental worker requires its frozen verification context")
    request_path = root / "request.json"
    _write(request_path, request)
    request_hash = _hash(request_path)
    environment = {**os.environ, "PSCAD_MCP_ACCEPTANCE_CONCURRENT": "1", "PSCAD_MCP_WORKSPACE": str(root / "worker")}
    process = None
    communication = None
    try:
        result.update({"launch_attempted": True, "owned_process_cleaned": False, "cleanup_pending": True})
        process = await asyncio.create_subprocess_exec(sys.executable, "-m", worker_module or __name__, "--request", str(request_path), "--request-sha256", request_hash,
            cwd=Path(__file__).resolve().parents[4], env=environment, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            **({"creationflags": 0x08000000} if os.name == "nt" else {}))
        result.update({"worker_launched": True, "launcher_pid": process.pid, "python_pid": process.pid, "owned_process_cleaned": False, "cleanup_pending": True})
        communication = asyncio.create_task(process.communicate())
        output, _ = await asyncio.wait_for(asyncio.shield(communication), timeout=1800)
        (root / "worker.log").write_bytes(output)
        report_path = root / "worker" / "report.json"
        report_hash = _hash(report_path)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if not _worker_matches_launcher(report, process.pid) or report.get("request_sha256") != request_hash or _hash(report_path) != report_hash:
            raise ValueError("Worker report identity differs from the launched request")
        result.update({**report, "worker_launched": True, "launcher_pid": process.pid, "report_path": str(report_path), "report_sha256": report_hash,
            "cleanup_pending": report.get("owned_process_cleaned") is not True})
        if process.returncode != 0 or report.get("status") != "PASS" or report.get("owned_process_cleaned") is not True:
            raise ValueError("Independent worker did not complete a passing run and owned cleanup")
        if _hash(project) != request["project"]["sha256"] or _files(bundle) != request["bundle"]["source_snapshot"]:
            raise ValueError("Original replay inputs changed")
        if report.get("copied_project_sha256") != request["project"]["sha256"] or report.get("copied_bundle_hashes") != request["bundle"]["files"] or report.get("parent_channel_contract_sha256") != request["channel_contract_sha256"] or report.get("checks_sha256") != request["checks_sha256"]:
            raise ValueError("Replay lineage differs from the frozen request")
        child_hashes = _dependency_hashes(root / "worker" / bundle.name, request["bundle"]["files"])
        result["supervisor_dependency_hashes"] = child_hashes
        if child_hashes != request["bundle"]["files"]:
            raise ValueError("The actual replay compiler dependency copies changed")
        if report.get("acceptance", {}).get("verdict") != "PASS":
            raise ValueError("Independent worker did not satisfy the frozen physical checks")
        if report.get("replay_saved_model_verified") is not True:
            raise ValueError("The independently saved model identity was not verified")
        frozen_identity = _frozen_output_index(root / "worker", report)
        if report.get("output_identity") != frozen_identity or report.get("frozen_output_identity_sha256") != _json_hash(frozen_identity):
            raise ValueError("The replay evidence differs from this child's frozen output index")
        if verification_context is not None:
            supplemental = report.get("supplemental_evidence", {})
            if report.get("verification_context_sha256") != request["verification_context_sha256"] or report.get("supplemental_saved_validation", {}).get("verdict") != "PASS" or supplemental.get("verdict") != "PASS" or supplemental.get("output_identity") != frozen_identity:
                raise ValueError("Supplemental replay checks did not pass on the same frozen child dataset")
        verify_output_dataset(frozen_identity)
        verify_fault_instrumentation(root / "worker" / project.name, report["replay_channel_contract"])
        result.update({"status": "PASS", "project_sha256": request["project"]["sha256"]})
    except BaseException as error:  # noqa: BLE001 - retain worker/cancellation evidence through cleanup
        result["status"] = "FAIL"
        supervisor_error = {"type": type(error).__name__, "message": str(error)}
        if result.get("error") is not None:
            result["supervisor_error"] = supervisor_error
        else:
            result["error"] = supervisor_error
    finally:
        if process is not None and result.get("cleanup_pending"):
            ownership_path = root / "worker" / "ownership.json"
            if ownership_path.is_file():
                try:
                    ownership = json.loads(ownership_path.read_text(encoding="utf-8"))
                    if ownership.get("request_sha256") != request_hash:
                        raise ValueError("Ownership record does not belong to this replay request")
                    result.update(await _terminate_owned_pscad(ownership))
                except BaseException as error:  # noqa: BLE001 - keep unresolved owned cleanup in the final report
                    result["cleanup_error"] = str(error)
        if process is not None:
            await _finalize_python_worker(process, communication, root, result)
        if result.get("cleanup_pending") or result.get("worker_exit_code") not in (None, 0):
            result["status"] = "FAIL"
    return _supervisor_report(root, result)


def _verify_replay_saved_model(original: Path, saved: Path, contract) -> bool:
    before, after = ET.parse(original).getroot(), ET.parse(saved).getroot()
    return _verify_saved_model_roots(before, after, contract)


_VENDOR_STICKY_STYLE = {
    "full_font": "Arial, 12pt", "align": "0", "style": "1",
    "fg_color": "0", "bg_color": "11920639", "opacity": "25",
}


def _is_vendor_sticky_style(style):
    if style.attrib or (style.text or "").strip() or len(style) != len(_VENDOR_STICKY_STYLE):
        return False
    if {param.get("name") for param in style} != set(_VENDOR_STICKY_STYLE):
        return False
    return all(
        param.tag == "param" and not len(param)
        and param.attrib == {"name": param.get("name"), "value": _VENDOR_STICKY_STYLE[param.get("name")]}
        and not (param.text or "").strip() and not (param.tail or "").strip()
        for param in style
    )


def _normalize_new_sticky_styles(before, after):
    if before.tag != after.tag:
        return
    if before.tag == "Sticky" and before.attrib == after.attrib and not len(before) and len(after) == 1:
        style = after.find("paramlist")
        if style is not None and _is_vendor_sticky_style(style) and "".join(before.itertext()).strip() == "".join(after.itertext()).strip():
            # Vendor moves the unchanged visible text into the new style's tail.
            after.remove(style)
            after.text = before.text
    for old, new in zip(before, after):
        _normalize_new_sticky_styles(old, new)


def _normalize_hierarchy_call_order(before, after):
    """Validate vendor ordinal assignment before comparing reordered call indexes."""
    def canonical_hierarchies(root):
        return [ET.canonicalize(ET.tostring(item, encoding='unicode'), strip_text=True)
                for item in root.findall('./hierarchy')]

    if canonical_hierarchies(before) == canonical_hierarchies(after):
        return
    for root in (before, after):
        for hierarchy in root.findall('./hierarchy'):
            counts, indexed = {}, {}
            for call in hierarchy.iter('call'):
                name, ordinal = call.get('name'), call.get('instance')
                present = ordinal is not None
                if name in indexed and indexed[name] != present:
                    raise ValueError('Saved hierarchy instance numbering is incomplete')
                indexed[name] = present
                expected = counts.get(name, 0)
                if present and ordinal != str(expected):
                    raise ValueError('Saved hierarchy instances are not numbered in definition traversal order')
                counts[name] = expected + 1
            for parent in hierarchy.iter():
                calls = [child for child in parent if child.tag == 'call']
                if len(calls) < 2:
                    continue
                links = [child.get('link') for child in calls]
                if any(link is None for link in links) or len(links) != len(set(links)):
                    raise ValueError('Saved hierarchy calls have missing or duplicate instance identities')
                ordered = iter(sorted(calls, key=lambda child: child.get('link')))
                parent[:] = [next(ordered) if child.tag == 'call' else child for child in parent]
            counts = {}
            for call in hierarchy.iter('call'):
                name = call.get('name')
                if indexed[name]:
                    ordinal = counts.get(name, 0)
                    call.set('instance', str(ordinal))
                    counts[name] = ordinal + 1


def _verify_saved_model_roots(before, after, contract) -> bool:
    binding = contract.get("virtual_root_rebinding")
    if binding:
        ids = [re.fullmatch(r"Station\[(\d+)\]", binding.get(key, "")) for key in ("before", "after")]
        old, new = before.find("./hierarchy/call"), after.find("./hierarchy/call")
        if all(ids) and old is not None and new is not None and old.get("link") == ids[0][1] and new.get("link") == ids[1][1]:
            new.set("link", old.get("link"))
            if before.get("id") == ids[0][1] and after.get("id") == ids[1][1]:
                after.set("id", before.get("id"))
    _normalize_new_sticky_styles(before, after)
    _normalize_hierarchy_call_order(before, after)
    for root in (before, after):
        for revisor in root.findall("./paramlist[@name='Settings']/param[@name='revisor']"):
            if "value" in revisor.attrib:
                revisor.set("value", "")
        for definition in root.findall("./definitions/Definition"):
            definition.attrib.pop("crc", None)
    if ET.canonicalize(ET.tostring(before, encoding="unicode"), strip_text=True) != ET.canonicalize(ET.tostring(after, encoding="unicode"), strip_text=True):
        raise ValueError("The replay saved model differs beyond the verified virtual document root and vendor save metadata")
    return True


def _capture_ownership(service, request_hash):
    backend = getattr(service, "_pending_cleanup_backend", None)
    if backend is None:
        backend = getattr(service, "_backend", None)
    if backend is None:
        return None
    details = {"owns_process": backend.owns_process, "session": dict(backend.session_details)}
    require_acceptance_ownership(details)
    pid = details["session"].get("managed_pid")
    if details["owns_process"] is not True or type(pid) is not int or pid <= 0:
        raise RuntimeError("Independent replay has no proven owned PSCAD process")
    process = psutil.Process(pid)
    executable = process.exe()
    if Path(executable).resolve() != Path(details["session"]["managed_executable"]).resolve():
        raise RuntimeError("The managed executable differs from the owned PID")
    return {"pid": pid, "created_at": process.create_time(), "executable": executable, "request_sha256": request_hash}


async def _worker(request_path: Path, expected_hash: str, *, saved_verifier=None, dataset_verifier=None):
    from .blank_service import (
        _bundle_file,
        _copy_frozen,
        _run_native_fault_case,
        _verify_runtime_master,
    )

    if os.getenv("PSCAD_MCP_MMC_ACCEPTANCE") != "1" or os.getenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT") != "1":
        raise RuntimeError("Explicit MMC replay and independent process opt-ins are required")
    if _hash(request_path) != expected_hash:
        raise ValueError("Replay request changed")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    root = request_path.parent / "worker"
    root.mkdir()
    report = {"schema_version": 1, "status": "FAIL", "owned_process_cleaned": False, "history": [], "result": {},
        "python_pid": os.getpid(), "worker_parent_pid": os.getppid(), "request_sha256": expected_hash, "parent_channel_contract_sha256": request["channel_contract_sha256"], "checks_sha256": request["checks_sha256"]}
    report_path = root / "report.json"
    service = _service(root)
    ownership = None
    bundle = None
    quit_task = None

    def verify_dependencies(stage):
        observed = _dependency_hashes(bundle, request["bundle"]["files"])
        report.setdefault("dependency_snapshots", {})[stage] = observed
        report["copied_bundle_hashes"] = observed
        if observed != request["bundle"]["files"]:
            raise ValueError("A frozen replay dependency changed during " + stage)

    def checkpoint(stage):
        verify_dependencies(stage)
        if stage == "saved_and_bound":
            saved_contract = json.loads(Path(report["result"]["channel_contract_path"]).read_text(encoding="utf-8"))
            report["replay_saved_model_verified"] = _verify_replay_saved_model(original, project, saved_contract)
            if context is not None:
                saved_hash = _hash(project)
                hook_context, hook_contract = copy.deepcopy(context), copy.deepcopy(saved_contract)
                report["supplemental_saved_validation"] = copy.deepcopy(saved_verifier(hook_context, project, hook_contract))
                if hook_context != context or hook_contract != saved_contract or _hash(project) != saved_hash:
                    raise ValueError("Supplemental saved-case verification mutated its frozen inputs")
                verify_fault_instrumentation(project, saved_contract)
                if report["supplemental_saved_validation"].get("verdict") != "PASS":
                    raise ValueError("Supplemental saved-case verification did not pass")
        report["history"].append({"stage": stage, "at": time.time()})
        _write(report_path, report)

    try:
        context = request.get("verification_context")
        if context is not None:
            if not isinstance(context, Mapping) or _json_hash(context) != request.get("verification_context_sha256") or not callable(saved_verifier) or not callable(dataset_verifier):
                raise ValueError("A supplemental contract requires matching fixed worker verifiers")
            report["verification_context_sha256"] = request["verification_context_sha256"]
        elif saved_verifier is not None or dataset_verifier is not None:
            raise ValueError("Worker verifiers require a frozen supplemental context")
        if request["checks_contract"] != default_fault_checks() or _json_hash(request["checks_contract"]) != request["checks_sha256"] or _json_hash(request["channel_contract"]) != request["channel_contract_sha256"]:
            raise ValueError("Replay contracts are not the fixed requested contracts")
        original = Path(request["project"]["path"])
        original_bundle = Path(request["bundle"]["path"])
        if _hash(original) != request["project"]["sha256"] or _files(original_bundle) != request["bundle"]["source_snapshot"]:
            raise ValueError("The saved replay inputs changed before copying")
        project = root / original.name
        bundle = root / original_bundle.name
        shutil.copy2(original, project)
        bundle.mkdir()
        for relative, digest in request["bundle"]["files"].items():
            _copy_frozen(_bundle_file(original_bundle, relative), bundle / relative, digest)
        if _hash(project) != request["project"]["sha256"] or _files(bundle) != request["bundle"]["files"]:
            raise ValueError("The copied replay model or dependencies differ")
        report["copied_project_sha256"] = _hash(project)
        verify_dependencies("copied")
        contract = copy.deepcopy(request["channel_contract"])
        verify_fault_instrumentation(project, contract)
        contract["project_path"] = str(project)
        contract["readback"]["project_path"] = str(project)
        contract["vendor_finalized"] = False
        contract.pop("virtual_root_rebinding", None)
        contract["replay_parent_contract_sha256"] = request["channel_contract_sha256"]
        checkpoint("frozen_copy_verified")
        report["attach_started"] = True
        await service.attach_local()
        report["attach_completed"] = True
        ownership = _capture_ownership(service, expected_hash)
        if ownership is None:
            raise RuntimeError("The replay worker has no owned connection")
        _write(root / "ownership.json", ownership)
        report["runtime"] = await service.status()
        report["runtime_master"] = await _verify_runtime_master(service, request["source_identities"]["master"])
        library = bundle / Path(request["source_identities"]["library"]["path"]).name
        contract, samples = await _run_native_fault_case(service, project, library, contract, request["checks_contract"], request["settings"], root / "evidence", report, checkpoint)
        verify_dependencies("after_run")
        frozen_identity = _frozen_output_index(root, report)
        if samples["identity"] != frozen_identity:
            raise ValueError("Native samples differ from this child's frozen output index")
        frozen_contract = copy.deepcopy(contract)
        frozen_project_hash = _hash(project)
        acceptance = evaluate_template_native_dc_fault(samples, channel_contract=frozen_contract, checks_contract=request["checks_contract"], fault_current_limit_ka=request["checks_contract"]["fault_current_limit_ka"])
        report["acceptance"] = copy.deepcopy(acceptance)
        report["output_identity"] = copy.deepcopy(frozen_identity)
        report["frozen_output_identity_sha256"] = _json_hash(frozen_identity)
        report["readback"] = copy.deepcopy(frozen_contract["readback"])
        report["replay_channel_contract"] = copy.deepcopy(frozen_contract)
        if context is not None:
            hook_context = copy.deepcopy(context)
            hook_contract = copy.deepcopy(frozen_contract)
            hook_samples = copy.deepcopy(samples)
            report["supplemental_evidence"] = copy.deepcopy(dataset_verifier(hook_context, project, hook_contract, hook_samples))
            if hook_context != context or hook_contract != frozen_contract or hook_samples != samples or samples["identity"] != frozen_identity:
                raise ValueError("Supplemental verification mutated its frozen inputs")
            if report["supplemental_evidence"].get("verdict") != "PASS" or report["supplemental_evidence"].get("output_identity") != frozen_identity:
                raise ValueError("Supplemental verification did not pass on the same child dataset")
        if _hash(project) != frozen_project_hash or _frozen_output_index(root, report) != frozen_identity:
            raise ValueError("Supplemental verification changed the native model or output index")
        verify_fault_instrumentation(project, frozen_contract)
        verify_output_dataset(frozen_identity)
        report["status"] = "PASS" if acceptance.get("verdict") == "PASS" else "FAIL"
        if _hash(original) != request["project"]["sha256"] or _files(original_bundle) != request["bundle"]["source_snapshot"]:
            raise ValueError("The first tested inputs changed during replay")
    except BaseException as error:  # noqa: BLE001 - preserve failure before owned cleanup
        report["status"] = "FAIL"
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        report["traceback"] = traceback.format_exc()
    finally:
        try:
            ownership = ownership or _capture_ownership(service, expected_hash)
            if ownership is None:
                uncertain = report.get("attach_started") is True
                report.update({"owned_process_cleaned": not uncertain, "cleanup_pending": uncertain,
                               "attach_outcome_uncertain": uncertain, "ownership_status": "launch_identity_unconfirmed" if uncertain else "no_launch_attempted"})
            else:
                _write(root / "ownership.json", ownership)
                report["cleanup_ownership"] = ownership
                try:
                    quit_task = asyncio.create_task(service.quit_pscad(confirm=True))
                    await asyncio.wait_for(quit_task, timeout=30)
                    await asyncio.to_thread(psutil.Process(ownership["pid"]).wait, 10)
                    report.update({"owned_process_cleaned": True, "cleanup_pending": False})
                except psutil.NoSuchProcess:
                    report.update({"owned_process_cleaned": True, "cleanup_pending": False})
                except BaseException as error:  # noqa: BLE001 - escalate only the recorded owned PID
                    report["graceful_cleanup_error"] = str(error)
                    report.update(await _terminate_owned_pscad(ownership))
        except BaseException as error:  # noqa: BLE001 - preserve unknown ownership, never infer a foreign PID
            report.update({"cleanup_error": str(error), "owned_process_cleaned": False, "cleanup_pending": True})
        try:
            report["pending_vendor_calls"] = _pending_owned_calls(service, asyncio.current_task(), quit_task)
            if report["pending_vendor_calls"]:
                report.update({"owned_process_cleaned": False, "cleanup_pending": True})
        except BaseException as error:  # noqa: BLE001 - unreadable settlement state cannot prove cleanup
            report.update({"settlement_error": str(error), "owned_process_cleaned": False, "cleanup_pending": True})
        if bundle is not None and bundle.is_dir():
            try:
                verify_dependencies("after_cleanup")
            except BaseException as error:  # noqa: BLE001 - cleanup does not waive frozen dependency identity
                report.update({"status": "FAIL", "dependency_error": str(error)})
        if not report["owned_process_cleaned"]:
            report["status"] = "FAIL"
        _write(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--request-sha256", required=True)
    args = parser.parse_args()
    report = asyncio.run(_worker(args.request, args.request_sha256))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
