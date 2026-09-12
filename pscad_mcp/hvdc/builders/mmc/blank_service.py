"""Explicit template-backed lifecycle for blank MMC requests.

The repository-owned AVM contract is useful for planning, but it is not a
PSCAD-instantiable full converter.  This service therefore plans blank MMC
requests from an audited official PSCAD project/library pair and keeps the
native-template mode explicit.  Dynamic fault execution is intentionally
delegated to the template-native path; no wall-clock event is inferred.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import hmac
import json
import math
import os
import re
import shutil
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ....acceptance.evidence import _is_reparse_point
from ....core.backend.base import BackendError
from ....core.path_policy import PathPolicy
from ....core.service import ConfirmationRequired
from ....runtime import PendingCleanupError
from .blank import BlankMmcRequest
from .fault_channels import (
    default_fault_checks,
    finalize_fault_instrumentation,
    instrument_fault_channels,
    materialize_arm_virtual_resistance,
    materialize_complete_arm_sorting,
    materialize_dc_feedback_filter,
    materialize_terminal_two_carrier,
    materialize_terminal_two_charging,
    materialize_voltage_control_headroom,
    materialize_voltage_control_integral_time,
    read_fault_output_dataset,
    snapshot_output_dataset,
    verify_fault_instrumentation,
    verify_output_dataset,
)
from .journal import AtomicJournal, WorkspaceBuildLease
from .line_constants import (
    extract_tline_segments,
    generate_public_line_constants,
    rebind_template_line_constants,
    render_tli,
)
from .models import SubmoduleTopology
from .template_audit import (
    audit_mmc_template,
    discover_official_mmc_template,
)
from .template_native import (
    evaluate_template_native_dc_fault,
    materialize_template_native_scenario,
)

_TERMINAL_SUCCESS = {"completed", "complete", "finished", "done", "idle", "stopped"}
_TERMINAL_FAILURE = {"failed", "error", "aborted", "cancelled", "canceled"}
_MODEL_RECIPES = {
    "raw": {},
    "headroom_1p1": {"current_limit_pu": 1.1},
    "headroom_1p1_dc_filter_5ms": {"current_limit_pu": 1.1, "dc_feedback_time_constant_s": 0.005},
    "native_full_sort_v1": {"current_limit_pu": 1.1, "dc_feedback_time_constant_s": 0.005, "terminal_two_carrier_ratio": 23.0, "arm_virtual_resistance_ohm": 30.0, "sort_extent": "Dim", "sort_enable": "existing_Enab"},
}
_MODEL_RECIPES["native_full_sort_dc_integral_004_v1"] = {**_MODEL_RECIPES["native_full_sort_v1"], "t1_dc_integral_time_s": 0.04}
_WINDOWS_DEVICE = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", re.IGNORECASE)


def _default_master_path() -> Path:
    return Path("C:/Program Files (x86)/PSCAD46/master.pslx")


def _recipe_contract(name: str) -> dict[str, Any]:
    parameters = copy.deepcopy(_MODEL_RECIPES[name])
    steps = [{"name": "terminal_two_charging", "parameters": {}}]
    if "current_limit_pu" in parameters:
        steps.append({"name": "voltage_control_headroom", "parameters": {"current_limit_pu": parameters["current_limit_pu"]}})
    if "dc_feedback_time_constant_s" in parameters:
        steps.append({"name": "dc_feedback_filter", "parameters": {"time_constant_s": parameters["dc_feedback_time_constant_s"]}})
    if "sort_extent" in parameters:
        steps.extend([
            {"name": "terminal_two_carrier", "parameters": {"ratio": 23.0}},
            {"name": "arm_virtual_resistance", "parameters": {"resistance_per_arm_ohm": 30.0}},
            {"name": "complete_arm_sorting", "parameters": {"sort_extent": "Dim", "enable": "existing_Enab"}},
        ])
    if "t1_dc_integral_time_s" in parameters:
        steps.append({"name": "voltage_control_integral_time", "parameters": {"time_constant_s": parameters["t1_dc_integral_time_s"]}})
    steps.append({"name": "fault_instrumentation", "parameters": {}})
    return {"schema_version": 1, "name": name, "parameters": parameters, "steps": steps,
            "physical_acceptance_verified": False, "fault_recovery_status": "pending",
            "producer_code_hashes": {module: _identity(Path(__file__).with_name(module + ".py")) for module in ("fault_channels", "template_native", "blank_service")}}


def _error(code: str, message: str, operation: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", operation, details)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _status_value(value: Any) -> str:
    if isinstance(value, str):
        return value.casefold()
    if isinstance(value, Mapping):
        for key in ("status", "state", "run_state"):
            item = value.get(key)
            if isinstance(item, str):
                return item.casefold()
    return ""


def _run_sync(factory: Callable[[], Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    result: list[Any] = []
    failure: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(factory()))
        except BaseException as error:  # noqa: BLE001 - preserve reader failure identity
            failure.append(error)

    thread = threading.Thread(target=runner, name="blank-mmc-validation-reader", daemon=True)
    thread.start()
    thread.join()
    if failure:
        raise failure[0]
    return result[0]


def _workspace(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    if root.exists() and not root.is_dir():
        raise _error("MMC_LAYOUT_INVALID", "The blank MMC workspace is not a directory.", "plan_blank_mmc_model")
    return root


def _project_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error("MMC_LAYOUT_INVALID", "project_name must be a non-empty string.", "plan_blank_mmc_model")
    name = Path(value.strip()).name
    if name.casefold().endswith(".pscx"):
        name = name[:-5]
    if not name or name != value.strip() and any(char in value.strip() for char in "/\\"):
        raise _error("MMC_LAYOUT_INVALID", "project_name must be a single PSCAD identity.", "plan_blank_mmc_model")
    if not name[0].isalpha() or len(name) > 128 or any(not (char.isalnum() or char in "_.-") for char in name):
        raise _error("MMC_LAYOUT_INVALID", "project_name contains unsupported characters.", "plan_blank_mmc_model")
    if _WINDOWS_DEVICE.fullmatch(name.split(".", 1)[0]):
        raise _error("MMC_LAYOUT_INVALID", "project_name is a reserved Windows device identity.", "plan_blank_mmc_model")
    return name


def _regular(value: str | Path, suffix: str, operation: str) -> Path:
    raw = Path(value).expanduser()
    if raw.is_symlink():
        raise _error("MMC_TEMPLATE_NOT_FOUND", "The official MMC template pair must contain regular files.", operation, path=str(raw))
    path = raw.resolve()
    if path.suffix.casefold() != suffix or path.is_symlink() or not path.is_file():
        raise _error("MMC_TEMPLATE_NOT_FOUND", "The official MMC template pair must contain regular files.", operation, path=str(path))
    return path


def _identity(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise _error("MMC_PLAN_STALE", "An immutable input must be a regular file.", "plan_blank_mmc_model", path=str(path))
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _support_contract(library: Path, audit: Mapping[str, Any]) -> dict[str, Any]:
    support = copy.deepcopy(dict(audit.get("compiler_support", {})))
    linked = support.get("link_libraries", {})
    if (support.get("required") and not support.get("present")) or (linked.get("required") and not linked.get("present")):
        raise _error("MMC_COMPILER_SUPPORT_MISSING", "Required compiler support is unavailable.", "plan_blank_mmc_model")
    files = support.get("files", [])
    if not isinstance(files, (list, tuple)) or ((support.get("required") or linked.get("required")) and not files):
        raise _error("MMC_COMPILER_SUPPORT_MISSING", "Compiler support requires a complete audited file list.", "plan_blank_mmc_model")
    paths = set()
    for item in files:
        if not isinstance(item, Mapping) or not isinstance(item.get("relative_path"), str):
            raise _error("MMC_PLAN_STALE", "A compiler-support identity is invalid.", "plan_blank_mmc_model")
        relative = Path(item["relative_path"])
        expected = library.parent / relative
        if relative.is_absolute() or ".." in relative.parts or not expected.resolve().is_relative_to(library.parent.resolve()) or str(expected.resolve()) != item.get("path"):
            raise _error("MMC_PLAN_STALE", "Compiler support must stay in its audited source directory.", "plan_blank_mmc_model", file=dict(item))
        identity = _identity(expected)
        if identity["sha256"] != item.get("sha256") or str(expected.resolve()).casefold() in paths:
            raise _error("MMC_PLAN_STALE", "Compiler support changed or is duplicated in its audit.", "plan_blank_mmc_model", file=dict(item))
        paths.add(str(expected.resolve()).casefold())
    support["files"] = sorted((dict(item) for item in files), key=lambda item: item["relative_path"].casefold())
    return support


def _line_contract(source: Path, master: Path, audit: Mapping[str, Any]) -> dict[str, Any]:
    try:
        root = ET.parse(source).getroot()
    except (OSError, ET.ParseError) as error:
        raise _error("MMC_TEMPLATE_INVALID", "The native source XML is invalid.", "plan_blank_mmc_model", path=str(source)) from error
    dependencies = copy.deepcopy(list(audit.get("absolute_paths", [])))
    has_lines = any(item.get("classid", "").casefold() == "tline" for item in root.iter())
    if not has_lines:
        unresolved = [item for item in dependencies if item.get("kind") in {"line_constants", "line_database"}]
        if unresolved:
            raise _error("MMC_ABSOLUTE_PATH_UNRESOLVED", "The source has external line dependencies without a declared DCTL generation contract.", "plan_blank_mmc_model", dependencies=unresolved)
        return {"mode": "none", "inputs": [], "source_dependencies": dependencies}
    executable = master.parent / "bin" / "win" / "tline.exe"
    executable_identity = _identity(executable)
    try:
        segments = extract_tline_segments(source)
        names = [item.name for item in segments]
        if len(names) != len({name.casefold() for name in names}) or any(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) is None or _WINDOWS_DEVICE.fullmatch(name) for name in names):
            raise ValueError("Line names must be unique native identities")
        inputs = [{"name": segment.name, "input_sha256": hashlib.sha256(render_tli(segment).encode("utf-8")).hexdigest()} for segment in segments]
    except (TypeError, ValueError, OverflowError) as error:
        raise _error("MMC_TEMPLATE_INVALID", "The native line-generation inputs are invalid.", "plan_blank_mmc_model", reason=str(error)) from error
    return {"mode": "generate_public_from_source_dctl", "executable": executable_identity, "inputs": inputs, "source_dependencies": dependencies}


class BlankMmcBuilderService:
    """Plan and (when supported) execute an official-template blank MMC case."""

    def __init__(self, pscad_service: Any, *, workspace_root: str | Path, audit_loader: Callable[..., Any] = audit_mmc_template, replay_verifier: Callable[..., Any] | None = None) -> None:
        self.pscad_service = pscad_service
        self.workspace_root = _workspace(workspace_root)
        self.path_policy = PathPolicy(workspace_root=str(self.workspace_root))
        self.audit_loader = audit_loader
        self._replay_verifier = replay_verifier
        self._settlements: dict[str, tuple[Any, ...]] = {}
        self._cleanup_waiters: dict[str, asyncio.Future[Any]] = {}
        self._cleanup_tasks: dict[str, asyncio.Task[Any]] = {}
        self._cleanup_lock = asyncio.Lock()
        self._plans: dict[str, dict[str, Any]] = {}
        self._statuses: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._leases: dict[str, WorkspaceBuildLease] = {}
        self._closing = False

    def _pair(self, template_path: str | Path | None, library_path: str | Path | None) -> tuple[Path, Path]:
        if template_path is None and library_path is None:
            return discover_official_mmc_template()
        if template_path is None or library_path is None:
            raise _error("MMC_TEMPLATE_PAIR_INVALID", "template_path and library_path must be supplied together.", "plan_blank_mmc_model")
        return _regular(template_path, ".pscx", "plan_blank_mmc_model"), _regular(library_path, ".pslx", "plan_blank_mmc_model")

    def plan_model(
        self,
        request: BlankMmcRequest | Mapping[str, Any] | str,
        folder: str | None = None,
        simulation_duration_s: float | None = None,
        blueprint: str = "cigre_b4_p2p_avm_v1",
        *,
        template_path: str | Path | None = None,
        library_path: str | Path | None = None,
    ) -> dict[str, Any]:
        if blueprint != "cigre_b4_p2p_avm_v1":
            raise _error("MMC_BLUEPRINT_NOT_FOUND", "Only the fixed blank MMC profile is supported.", "plan_blank_mmc_model", blueprint=blueprint)
        if simulation_duration_s is None and isinstance(request, Mapping):
            simulation_duration_s = request.get("simulation_duration_s")
        parsed = request if isinstance(request, BlankMmcRequest) else BlankMmcRequest.from_dict(request) if isinstance(request, Mapping) else BlankMmcRequest(project_name=request, folder=folder)
        if dict(parsed.ratings) != {"dc_voltage_kv": 320.0, "power_mw": 1000.0} or parsed.control_profile != "active_reactive_dc_voltage" or parsed.fault_profile != "dc_pole_to_pole_and_recovery":
            raise _error("MMC_BLUEPRINT_INVALID", "The fixed native template does not implement custom ratings or control/fault profiles.", "plan_blank_mmc_model", ratings=dict(parsed.ratings), control_profile=parsed.control_profile, fault_profile=parsed.fault_profile)
        parameters = dict(parsed.parameterization)
        unknown = sorted(set(parameters) - {"model_recipe", "master_path"})
        recipe = parameters.get("model_recipe", "raw")
        if unknown or not isinstance(recipe, str) or recipe not in _MODEL_RECIPES:
            raise _error("MMC_BLUEPRINT_INVALID", "Native MMC model recipe or parameterization is unsupported.", "plan_blank_mmc_model", unknown=unknown, model_recipe=recipe)
        checks = default_fault_checks()
        duration = checks["simulation_duration_s"] if simulation_duration_s is None else simulation_duration_s
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(float(duration)) or duration <= 0:
            raise _error("MMC_BLUEPRINT_INVALID", "simulation_duration_s must be finite and positive.", "plan_blank_mmc_model")
        required_end = max(checks[name][1] for name in ("fault_window_s", "prefault_window_s", "recovery_window_s"))
        if duration < required_end:
            raise _error("MMC_BLUEPRINT_INVALID", "The requested duration cannot cover the production acceptance windows.", "plan_blank_mmc_model", requested_duration_s=duration, required_end_s=required_end)
        name = _project_name(parsed.project_name)
        template_path = template_path or parsed.template_path
        library_path = library_path or parsed.library_path
        template, library = self._pair(template_path, library_path)
        try:
            template.relative_to(self.workspace_root)
            raise _error("MMC_LAYOUT_INVALID", "The read-only MMC template must be outside the build workspace.", "plan_blank_mmc_model")
        except ValueError:
            pass
        audit = self.audit_loader(str(template), str(library))
        if hasattr(audit, "to_dict") and callable(audit.to_dict):
            audit = audit.to_dict()
        if not isinstance(audit, Mapping) or audit.get("compatible") is not True:
            raise _error("MMC_TEMPLATE_INCOMPATIBLE", "The official MMC template failed its audit.", "plan_blank_mmc_model", audit=dict(audit) if isinstance(audit, Mapping) else None)
        observed_topology = audit.get("submodule_topology", {})
        observed_name = observed_topology.get("declared") if isinstance(observed_topology, Mapping) else "unknown"
        requested_topology = parsed.submodule_topology.value
        if observed_name not in {requested_topology, "unknown"}:
            raise _error("MMC_TEMPLATE_TOPOLOGY_MISMATCH", "The official MMC template topology differs from the request.", "plan_blank_mmc_model", requested=requested_topology, observed=observed_name)
        requested_folder = parsed.folder if parsed.folder is not None else folder
        parent = self.workspace_root if requested_folder is None else self.path_policy.resolve(requested_folder)
        raw_target = Path(parent) / f"{name}.pscx"
        if raw_target.is_symlink():
            raise _error(
                "MMC_BUILD_CONFLICT",
                "The blank MMC destination already exists.",
                "plan_blank_mmc_model",
                target_path=str(raw_target),
            )
        target = self.path_policy.resolve_child(str(parent), f"{name}.pscx", suffixes={".pscx"})
        if target.exists() or target.is_symlink():
            raise _error("MMC_BUILD_CONFLICT", "The blank MMC destination already exists.", "plan_blank_mmc_model", target_path=str(target))
        master = _regular(parameters.get("master_path", _default_master_path()), ".pslx", "plan_blank_mmc_model")
        identities = {"project": _identity(template), "library": _identity(library), "master": _identity(master)}
        source_hashes = dict(audit.get("source_hashes", {}))
        if set(source_hashes) != {"project", "library"} or any(source_hashes[key] != identities[key]["sha256"] for key in source_hashes):
            raise _error("MMC_PLAN_STALE", "The audit source identities do not match the immutable files.", "plan_blank_mmc_model")
        support = _support_contract(library, audit)
        lines = _line_contract(template, master, audit)
        payload = {
            "schema_version": 1,
            "kind": "blank_mmc_native",
            "request": parsed.to_dict(),
            "request_implementation": {"ratings": {"binding": "descriptive_only", "requested": dict(parsed.ratings)}, "control_profile": "audited_existing_native_controls", "fault_profile": "materialized_native_dc_fault", "supported_native_contract": {"observed": False, "dc_pole_to_pole_voltage_kv": 640.0, "controlled_terminal_active_power_mw": -900.0, "rated_converter_mva": 1000.0}, "template_ratings_observed": None},
            "project_name": name,
            "workspace": str(self.workspace_root),
            "target_path": str(target),
            "staging_path": str(self.workspace_root / ".pscad-mcp" / "blank-mmc-builds" / f"{name}-{source_hashes['project'][:12]}.staging"),
            "settings": {"simulation_duration_s": float(duration), "time_step_s": checks["time_step_s"], "output_step_s": checks["output_step_s"], "output_enabled": True},
            "fault": {"kind": "dc_pole_to_pole", "time_s": checks["fault_window_s"][0], "removal_time_s": checks["fault_window_s"][1]},
            "checks_contract": checks,
            "checks_sha256": hashlib.sha256(json_bytes(checks)).hexdigest(),
            "model_recipe": _recipe_contract(recipe),
            "model_corrections": [{"name": "terminal_two_charging", "definition": "Main", "owner": "606940312", "parameter": "T", "before": "Tcharging1", "after": "Tcharging2", "classification": "verified_template_binding_defect"}],
            "source_identities": identities,
            "runtime_requirements": {"backend": "legacy", "pscad_version": "4.6.2", "master_source_must_match": identities["master"], "new_case_namespace": True},
            "compiler_support": support,
            "line_constants": lines,
            "template_native": {"source_paths": {"project": str(template), "library": str(library)}, "source_hashes": source_hashes, "submodule_topology": dict(observed_topology) if isinstance(observed_topology, Mapping) else {}, "controls": dict(audit.get("template_native_controls", {})) if isinstance(audit.get("template_native_controls", {}), Mapping) else {}},
            "capabilities": {**SubmoduleTopology.capabilities(parsed.submodule_topology), "template_submodule_topology": observed_name, "native_schedule": False, "template_native_timing": bool(isinstance(audit.get("template_native_controls"), Mapping) and audit["template_native_controls"].get("available") is True)},
            "operations": ["audit_source", "verify_runtime_master", "stage_frozen_dependencies", "materialize_template_fault", "repair_terminal_two_charging", "materialize_model_recipe", "instrument_fault_channels", "save_and_finalize_readback", "compile", "simulate_template_native_fault", "freeze_output_dataset", "validate_production_fault_evidence", "publish_tested_case"],
        }
        plan = {**payload, "plan_hash": hashlib.sha256(json_bytes(payload)).hexdigest(), "status": "planned"}
        self._plans[plan["plan_hash"]] = copy.deepcopy(plan)
        return plan

    async def build_model(
        self,
        request: BlankMmcRequest | Mapping[str, Any] | str,
        expected_plan_hash: str,
        *args: Any,
        confirm: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not confirm:
            raise ConfirmationRequired("build_blank_mmc_model")
        parsed = (
            request
            if isinstance(request, BlankMmcRequest)
            else BlankMmcRequest.from_dict(request)
            if isinstance(request, Mapping)
            else BlankMmcRequest(project_name=request)
        )
        folder = kwargs.get("folder", parsed.folder)
        duration = kwargs.get("simulation_duration_s")
        if duration is None and isinstance(request, Mapping):
            duration = request.get("simulation_duration_s")
        if duration is None and args:
            duration = args[0]
        blueprint = kwargs.get("blueprint", "cigre_b4_p2p_avm_v1")
        template_path = kwargs.get("template_path", parsed.template_path)
        library_path = kwargs.get("library_path", parsed.library_path)
        plan = self.plan_model(
            parsed,
            folder=folder,
            simulation_duration_s=duration,
            blueprint=blueprint,
            template_path=template_path,
            library_path=library_path,
        )
        if not isinstance(expected_plan_hash, str) or not hmac.compare_digest(
            expected_plan_hash, plan["plan_hash"]
        ):
            raise _error(
                "MMC_PLAN_STALE",
                "The supplied blank MMC plan hash is stale.",
                "build_blank_mmc_model",
                expected_plan_hash=expected_plan_hash if isinstance(expected_plan_hash, str) else "",
                observed_plan_hash=plan["plan_hash"],
            )
        target = Path(plan["target_path"])
        staging = Path(plan["staging_path"])
        if target.exists() or target.is_symlink() or staging.exists() or staging.is_symlink():
            raise _error(
                "MMC_BUILD_CONFLICT",
                "A planned blank MMC destination already exists.",
                "build_blank_mmc_model",
                target_path=str(target),
                staging_path=str(staging),
            )
        build_id = uuid.uuid4().hex
        lease = WorkspaceBuildLease.acquire(self.workspace_root, build_id)
        journal = AtomicJournal(self.workspace_root, build_id)
        initial = {
            "build_id": build_id,
            "state": "validated",
            "plan_hash": plan["plan_hash"],
            "target_path": plan["target_path"],
            "staging_path": plan["staging_path"],
            "workspace": str(self.workspace_root),
            "plan": copy.deepcopy(plan),
            "history": [{"state": "validated"}],
            "error": None,
            "result": None,
        }
        self._statuses[build_id] = initial
        self._leases[build_id] = lease
        journal.write(initial)
        task = asyncio.create_task(
            self._run(build_id, plan, journal, lease),
            name=f"blank-mmc-{build_id}",
        )
        self._tasks[build_id] = task
        task.add_done_callback(lambda completed: self._task_done(build_id, completed))
        await asyncio.sleep(0)
        return {
            key: initial[key]
            for key in ("build_id", "state", "plan_hash", "target_path", "staging_path")
        }

    async def _run(
        self,
        build_id: str,
        plan: dict[str, Any],
        journal: AtomicJournal,
        lease: WorkspaceBuildLease,
    ) -> dict[str, Any]:
        record = self._statuses[build_id]
        try:
            record = await _execute_native_mmc_plan(
                plan,
                self.pscad_service,
                self.workspace_root,
                build_id=build_id,
                journal=journal,
                record=record,
                audit_loader=self.audit_loader,
                replay_verifier=self._replay_verifier,
            )
        except asyncio.CancelledError:
            record.update({
                "state": "interrupted", "error": _error(
                    "MMC_BUILD_FAILED",
                    "The blank MMC build was interrupted.",
                    "build_blank_mmc_model",
                ).to_dict(),
            })
            record["history"].append({"state": "interrupted"})
        except BaseException as error:  # noqa: BLE001 - lifecycle records capture vendor failures
            backend_error = (
                error
                if isinstance(error, BackendError)
                else _error(
                    "MMC_BUILD_FAILED",
                    str(error),
                    "build_blank_mmc_model",
                    exception=type(error).__name__,
                )
            )
            record.update({"state": "failed", "error": backend_error.to_dict()})
            record["history"].append({"state": "failed", "reason": backend_error.code})
        finally:
            self._statuses[build_id] = record
            self._settlements[build_id] = _owned_native_settlements(self.pscad_service, asyncio.current_task())
            await self._finish_native_cleanup(build_id)
        return record

    async def _finish_native_cleanup(self, build_id: str, timeout_s: float = 30.0) -> None:
        async with self._cleanup_lock:
            lease = self._leases.get(build_id)
            if lease is None:
                return
            record = self._statuses[build_id]
            pending = await _contain_native_failure(self.pscad_service, record, self._settlements.get(build_id, ()), timeout_s=timeout_s)
            self._settlements[build_id] = pending
            record["pending_vendor_calls"] = len(pending)
            safe = record["containment"]["confirmed"] is True and not pending
            record["lease_retained"] = not safe
            AtomicJournal(self.workspace_root, build_id).write(record)
            if safe:
                lease.release(lease.token)
                self._leases.pop(build_id, None)
                self._settlements.pop(build_id, None)
                waiter = self._cleanup_waiters.pop(build_id, None)
                if waiter is not None and not waiter.done():
                    waiter.set_result(None)
                return
            if build_id not in self._cleanup_waiters:
                self._cleanup_waiters[build_id] = asyncio.get_running_loop().create_future()
            loop = asyncio.get_running_loop()

            def retry_on_loop() -> None:
                if build_id in self._leases and build_id not in self._cleanup_tasks:
                    task = loop.create_task(self._finish_native_cleanup(build_id))
                    self._cleanup_tasks[build_id] = task

                    def finished(done: asyncio.Task[Any]) -> None:
                        self._cleanup_tasks.pop(build_id, None)
                        if not done.cancelled():
                            done.exception()

                    task.add_done_callback(finished)

            def settled(_: Any) -> None:
                if not any(not token.settled for token in pending) and not loop.is_closed():
                    loop.call_soon_threadsafe(retry_on_loop)

            for token in pending:
                token.add_done_callback(settled)

    def _task_done(self, build_id: str, task: asyncio.Task[Any]) -> None:
        try:
            task.result()
        except BaseException:  # noqa: BLE001,S110 - consume terminal task failures
            pass
        self._tasks.pop(build_id, None)

    def get_build_status(self, build_id: str) -> dict[str, Any]:
        if build_id not in self._statuses:
            path = AtomicJournal(self.workspace_root, build_id).path
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise _error(
                    "NOT_FOUND",
                    "The blank MMC build was not found.",
                    "get_blank_mmc_build_status",
                    build_id=build_id,
                ) from error
            if not isinstance(value, dict):
                raise _error(
                    "MMC_JOURNAL_INVALID",
                    "The blank MMC journal is not an object.",
                    "get_blank_mmc_build_status",
                    build_id=build_id,
                )
            self._statuses[build_id] = value
        return copy.deepcopy(self._statuses[build_id])

    def validate_model(
        self,
        project_name: str,
        blueprint: str = "cigre_b4_p2p_avm_v1",
        output_file: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        if blueprint != "cigre_b4_p2p_avm_v1":
            raise _error("MMC_BLUEPRINT_NOT_FOUND", "Only the fixed blank MMC profile is supported.", "validate_blank_mmc_model")
        raw_candidate = Path(project_name).expanduser()
        if not raw_candidate.is_absolute():
            raw_candidate = self.workspace_root / raw_candidate
        if raw_candidate.is_symlink():
            raise _error(
                "MMC_LAYOUT_INVALID",
                "The MMC project must not be a symbolic link.",
                "validate_blank_mmc_model",
                project_name=str(raw_candidate),
            )
        candidate = raw_candidate
        if candidate.suffix.casefold() != ".pscx":
            candidate = candidate.with_suffix(".pscx")
        candidate = candidate.resolve()
        try:
            candidate.relative_to(self.workspace_root)
        except ValueError as error:
            raise _error("MMC_LAYOUT_INVALID", "The MMC project is outside the workspace.", "validate_blank_mmc_model") from error
        if not candidate.is_file() or candidate.is_symlink():
            raise _error("NOT_FOUND", "The blank MMC project was not found.", "validate_blank_mmc_model", project_name=str(candidate))
        template_path = _.get("template_path")
        library_path = _.get("library_path")
        if (template_path is None) != (library_path is None):
            raise _error(
                "MMC_TEMPLATE_PAIR_INVALID",
                "template_path and library_path must be supplied together.",
                "validate_blank_mmc_model",
            )
        topology_name = "unknown"
        native_audit: dict[str, Any] | None = None
        if template_path is not None and library_path is not None:
            audited = self.audit_loader(str(template_path), str(library_path))
            if hasattr(audited, "to_dict") and callable(audited.to_dict):
                audited = audited.to_dict()
            if isinstance(audited, Mapping):
                native_audit = dict(audited)
                topology = audited.get("submodule_topology")
                if isinstance(topology, Mapping) and isinstance(topology.get("declared"), str):
                    topology_name = topology["declared"]
        audit_valid = native_audit is None or native_audit.get("compatible") is True
        result: dict[str, Any] = {
            "project_file": str(candidate),
            "project_sha256": _sha256(candidate),
            "valid": audit_valid,
            "accepted": False,
            "output_file": None,
            "acceptance": {"status": "not_evaluated", "verdict": "not_evaluated"},
            "acceptance_scope": {"intrinsic_dc_fault_blocking": "NOT_APPLICABLE" if topology_name == "half_bridge" else "not_evaluated"},
            "native_template": native_audit,
            "capabilities": SubmoduleTopology.capabilities(
                SubmoduleTopology.FULL_BRIDGE
                if topology_name == "full_bridge"
                else SubmoduleTopology.HALF_BRIDGE
            )
            if topology_name in {"full_bridge", "half_bridge"}
            else {"intrinsic_dc_fault_blocking": False},
        }
        bundle = candidate.with_suffix(".bundle")
        if not (bundle / "manifest.json").exists():
            if output_file is not None:
                result["acceptance"] = {
                    "status": "not_evaluated", "verdict": "INCOMPLETE_ANALYSIS",
                    "reason": "No frozen publication, channel and output contracts accompany this project.",
                }
            return result
        publication, contract, checks, output_identity = _load_publication_evidence(candidate)
        output = Path(output_identity["primary"])
        if output_file is not None:
            requested_output = Path(output_file).expanduser()
            if not requested_output.is_absolute():
                requested_output = self.workspace_root / requested_output
            if requested_output.is_symlink() or requested_output.resolve() != output:
                raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "The requested output is not the tested publication dataset.", "validate_blank_mmc_model")
        reader = getattr(self.pscad_service, "read_output_file", None)
        if not callable(reader):
            raise _error("MMC_OUTPUT_INCOMPLETE", "The PSCAD service does not expose an output reader.", "validate_blank_mmc_model")
        samples = _run_sync(lambda: read_fault_output_dataset(reader, str(output), contract, started_after=output_identity["started_after"]))
        if samples.get("identity") != output_identity:
            raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "Validation read a different output dataset.", "validate_blank_mmc_model")
        topology = SubmoduleTopology(publication["plan"]["request"]["submodule_topology"])
        acceptance = evaluate_template_native_dc_fault(samples, channel_contract=contract, checks_contract=checks,
            fault_current_limit_ka=checks["fault_current_limit_ka"], topology=topology)
        _load_publication_evidence(candidate)
        audit_valid = audit_valid and publication["plan"]["template_native"]["submodule_topology"].get("declared") == topology.value
        result["valid"] = audit_valid
        result["native_template"] = native_audit or publication["plan"]["template_native"]
        result["capabilities"] = SubmoduleTopology.capabilities(topology)
        result["acceptance_scope"] = {"intrinsic_dc_fault_blocking": "NOT_APPLICABLE" if topology == SubmoduleTopology.HALF_BRIDGE else acceptance.get("verdict")}
        result["output_file"] = str(output)
        result["acceptance"] = {**acceptance, "status": "evaluated"}
        result["accepted"] = bool(
            audit_valid and acceptance.get("verdict") == "PASS"
        )
        return result

    async def shutdown(self, timeout_s: float = 5.0) -> None:
        self._closing = True
        tasks = tuple(task for task in self._tasks.values() if not task.done())
        for task in tasks:
            task.cancel()
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=max(0.0, timeout_s))
            if pending:
                raise PendingCleanupError(tuple(pending))
            for task in done:
                try:
                    task.result()
                except BaseException:  # noqa: BLE001,S110 - consume terminal cancellation
                    pass
        for build_id in tuple(self._leases):
            await self._finish_native_cleanup(build_id, timeout_s=max(0.01, timeout_s))
        waiters = tuple(waiter for waiter in self._cleanup_waiters.values() if not waiter.done())
        if waiters:
            _, pending = await asyncio.wait(waiters, timeout=max(0.0, timeout_s))
            if pending:
                raise PendingCleanupError(tuple(pending))


def json_bytes(value: Any) -> bytes:
    import json

    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def _native_name(value: str | Path) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", Path(value).stem).casefold()


def _write_evidence(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value) + b"\n")
    return _sha256(path)


def _checkpoint(record: dict[str, Any], journal: AtomicJournal, state: str, **values: Any) -> None:
    record["state"] = state
    record.update(values)
    record.setdefault("history", []).append({"state": state, "at": time.time()})
    journal.write(record)


def _verify_frozen_plan(plan: Mapping[str, Any]) -> None:
    payload = {key: value for key, value in plan.items() if key not in {"plan_hash", "status"}}
    if hashlib.sha256(json_bytes(payload)).hexdigest() != plan.get("plan_hash"):
        raise _error("MMC_PLAN_STALE", "The immutable build plan changed.", "build_blank_mmc_model")
    if plan.get("checks_contract") != default_fault_checks():
        raise _error("MMC_PLAN_STALE", "The planned physical checks differ from the production contract.", "build_blank_mmc_model")
    if plan.get("checks_sha256") != hashlib.sha256(json_bytes(plan["checks_contract"])).hexdigest():
        raise _error("MMC_PLAN_STALE", "The physical check identity differs from the frozen plan.", "build_blank_mmc_model")


def _verify_plan_inputs(plan: Mapping[str, Any], audit_loader: Callable[..., Any]) -> None:
    _verify_frozen_plan(plan)
    if set(plan["model_recipe"].get("producer_code_hashes", {})) != {"fault_channels", "template_native", "blank_service"}:
        raise _error("MMC_PLAN_STALE", "The plan does not freeze every model-recipe producer.", "build_blank_mmc_model")
    for identity in plan["model_recipe"]["producer_code_hashes"].values():
        if _identity(Path(identity["path"])) != identity:
            raise _error("MMC_PLAN_STALE", "A model-recipe producer changed after planning.", "build_blank_mmc_model", expected=identity)
    for identity in plan["source_identities"].values():
        if _identity(Path(identity["path"])) != identity:
            raise _error("MMC_PLAN_STALE", "An immutable source changed.", "build_blank_mmc_model", expected=identity)
    source = Path(plan["source_identities"]["project"]["path"])
    library = Path(plan["source_identities"]["library"]["path"])
    master = Path(plan["source_identities"]["master"]["path"])
    audit = audit_loader(str(source), str(library))
    if hasattr(audit, "to_dict"):
        audit = audit.to_dict()
    if _support_contract(library, audit).get("files") != plan["compiler_support"].get("files"):
        raise _error("MMC_PLAN_STALE", "The compiler-support source set changed.", "build_blank_mmc_model")
    if _line_contract(source, master, audit) != plan["line_constants"]:
        raise _error("MMC_PLAN_STALE", "The line-generation contract changed.", "build_blank_mmc_model")


async def _verify_runtime_master(service: Any, expected: Mapping[str, str]) -> dict[str, Any]:
    inventory_reader = getattr(service, "get_master_library_identity", None)
    if not callable(inventory_reader):
        raise _error("MMC_BUILD_UNAVAILABLE", "The connected service cannot prove its installed Master identity.", "build_blank_mmc_model")
    observed = await inventory_reader()
    if not isinstance(observed, Mapping) or observed.get("pscad_version") != "4.6.2" or observed.get("master_sha256") != expected["sha256"] or Path(str(observed.get("master_path", ""))).resolve() != Path(expected["path"]).resolve():
        raise _error("MASTER_SOURCE_CHANGED", "The connected PSCAD Master differs from the planned input.", "build_blank_mmc_model", expected=dict(expected), observed=observed)
    return dict(observed)


def _copy_frozen(origin: Path, destination: Path, digest: str) -> dict[str, str]:
    if _identity(origin)["sha256"] != digest or destination.exists() or destination.is_symlink():
        raise _error("MMC_PLAN_STALE", "A dependency changed or its copy destination is occupied.", "build_blank_mmc_model", source=str(origin), destination=str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origin, destination)
    if _sha256(destination) != digest or _sha256(origin) != digest:
        raise _error("MMC_PLAN_STALE", "A dependency changed while copying.", "build_blank_mmc_model", source=str(origin))
    return {"source": str(origin), "path": str(destination), "sha256": digest}


def _verify_copies(copies: list[dict[str, str]]) -> None:
    for item in copies:
        if _identity(Path(item["path"]))["sha256"] != item["sha256"] or _identity(Path(item["source"]))["sha256"] != item["sha256"]:
            raise _error("MMC_PLAN_STALE", "A copied dependency or its frozen source changed.", "build_blank_mmc_model", file=item)


async def _stage_dependencies(plan: Mapping[str, Any], staging: Path, bundle: Path, record: dict[str, Any]) -> tuple[Path, Path]:
    source = Path(plan["source_identities"]["project"]["path"])
    library = Path(plan["source_identities"]["library"]["path"])
    copies = record.setdefault("dependency_copies", [])
    staged_library = bundle / library.name
    copies.append(_copy_frozen(library, staged_library, plan["source_identities"]["library"]["sha256"]))
    for item in plan["compiler_support"]["files"]:
        copies.append(_copy_frozen(Path(item["path"]), bundle / item["relative_path"], item["sha256"]))
    lines = plan["line_constants"]
    if lines["mode"] == "none":
        return source, staged_library
    generation = staging / "line-generation"
    generation.mkdir()
    artifacts = await asyncio.to_thread(generate_public_line_constants, source, generation, executable=lines["executable"]["path"])
    requested = {item["name"]: item["input_sha256"] for item in lines["inputs"]}
    if {item.segment: item.input_sha256 for item in artifacts} != requested:
        raise _error("MMC_PLAN_STALE", "Generated line inputs differ from the frozen plan.", "build_blank_mmc_model")
    record["line_generation"] = [item.to_dict() for item in artifacts]
    rebound = []
    for artifact in artifacts:
        for label in ("input", "constants", "log", "output"):
            path = Path(getattr(artifact, label + "_path"))
            digest = getattr(artifact, label + "_sha256")
            if digest:
                copies.append(_copy_frozen(path, bundle / "lines" / path.name, digest))
        rebound.append(replace(artifact, constants_path=(Path(bundle.name) / "lines" / Path(artifact.constants_path).name).as_posix()))
    target = staging / "line_bound_source.pscx"
    rebind_template_line_constants(source, tuple(rebound), target)
    return target, staged_library


def _required_service_methods(service: Any) -> None:
    required = ("list_projects", "load_projects", "set_project_settings", "get_project_settings", "save_project", "build_project", "run_project", "get_run_status", "discover_output_files", "read_output_file")
    missing = [name for name in required if not callable(getattr(service, name, None))]
    if missing:
        raise _error("MMC_BUILD_UNAVAILABLE", "The service lacks required native fault lifecycle capabilities.", "build_blank_mmc_model", missing=missing)


async def _admit_case(service: Any, project: Path, library: Path) -> str:
    before = await service.list_projects()
    expected = {project.stem: project, library.stem: library}
    if len({_native_name(name) for name in expected}) != len(expected):
        raise _error("MMC_BUILD_CONFLICT", "Project and library runtime names collide.", "build_blank_mmc_model")
    collisions = [item for item in before if _native_name(str(item.get("name", ""))) in {_native_name(name) for name in expected}]
    if collisions:
        raise _error("MMC_BUILD_CONFLICT", "A required runtime namespace is already loaded.", "build_blank_mmc_model", projects=collisions)
    await service.load_projects([str(library), str(project)])
    inventory = await service.list_projects()
    for name, path in expected.items():
        matches = [item for item in inventory if str(item.get("name", "")).casefold() == name.casefold()]
        if len(matches) != 1:
            raise _error("MMC_POSTCONDITION_FAILED", "The loaded namespace is not unique.", "build_blank_mmc_model", name=name, inventory=inventory)
        actual = matches[0].get("filename", matches[0].get("file_path"))
        if actual is not None and Path(str(actual)).resolve() != path.resolve():
            raise _error("MMC_POSTCONDITION_FAILED", "The loaded filename differs from its staged input.", "build_blank_mmc_model", expected=str(path), observed=actual)
    return next(item["name"] for item in inventory if str(item.get("name", "")).casefold() == project.stem.casefold())


async def _run_native_fault_case(service: Any, project: Path, library: Path, contract: dict[str, Any], checks: Mapping[str, Any], settings: Mapping[str, Any], evidence: Path, record: dict[str, Any], checkpoint: Callable[..., None]) -> tuple[dict[str, Any], dict[str, Any]]:
    _required_service_methods(service)
    name = await _admit_case(service, project, library)
    record["runtime_project_name"] = name
    record["runtime_library_path"] = str(library)
    requested = {"time_duration": str(settings["simulation_duration_s"]), "time_step": format(settings["time_step_s"] * 1e6, ".12g"), "sample_step": format(settings["output_step_s"] * 1e6, ".12g"), "PlotType": "1", "output_filename": project.stem + ".out", "StartType": "0", "startup_filename": ""}
    await service.set_project_settings(name, requested)
    observed = await service.get_project_settings(name)
    if not isinstance(observed, Mapping) or any(str(observed.get(key)) != value for key, value in requested.items()):
        raise _error("MMC_POSTCONDITION_FAILED", "Native project settings did not read back exactly.", "build_blank_mmc_model", expected=requested, observed=observed)
    await service.save_project(name, confirm=True)
    contract["required_checks"] = copy.deepcopy(dict(checks))
    contract = finalize_fault_instrumentation(project, contract)
    channel_path = evidence / "channels.json"
    record["result"].update({"channel_contract_path": str(channel_path), "channel_contract_sha256": _write_evidence(channel_path, contract), "tested_project_sha256": _sha256(project)})
    checkpoint("saved_and_bound")
    await service.build_project(name)
    messages_reader = getattr(service, "get_project_output", None)
    if callable(messages_reader):
        messages = await messages_reader(name, structured=True)
        record["messages"] = messages
        failures = [item for item in messages if str(item.get("severity", "")).casefold() in {"error", "fatal"}]
        if failures:
            raise _error("MMC_BUILD_FAILED", "Native fault compilation failed.", "build_blank_mmc_model", messages=failures)
    verify_fault_instrumentation(project, contract)
    checkpoint("compiled")
    started = time.time()
    record["run_started_after"] = started
    record["run_started"] = True
    checkpoint("running")
    await service.run_project(name)
    deadline = time.monotonic() + 900.0
    while True:
        state = await service.get_run_status(name)
        value = _status_value(state)
        if value in _TERMINAL_FAILURE or value == "stopped":
            raise _error("MMC_BUILD_FAILED", "The native fault run failed or was stopped.", "build_blank_mmc_model", project_status=state)
        if value in _TERMINAL_SUCCESS:
            break
        if time.monotonic() >= deadline:
            raise _error("MMC_BUILD_TIMED_OUT", "The native fault run exceeded its deadline.", "build_blank_mmc_model")
        await asyncio.sleep(0.25)
    record["run_completed"] = True
    record["project_status"] = state
    checkpoint("simulated")
    discovered = await service.discover_output_files(str(project), started_after=started, max_files=1000)
    candidates = sorted({str(Path(path).resolve()) for path in discovered}, key=str.casefold)
    primary = [path for path in candidates if Path(path).name.casefold() == (project.stem + "_01.out").casefold()]
    if len(primary) != 1 or any(not Path(path).parent.resolve().is_relative_to(project.parent.resolve()) for path in candidates):
        raise _error("MMC_OUTPUT_INCOMPLETE", "This native case has no unique project-scoped OUT dataset.", "build_blank_mmc_model", discovered=candidates)
    manifest = snapshot_output_dataset(primary[0], started_after=started)
    index_path = evidence / "output-index.json"
    record["result"].update({"output_file": primary[0], "output_index_path": str(index_path), "output_index_sha256": _write_evidence(index_path, manifest)})
    checkpoint("outputs_frozen")
    samples = await read_fault_output_dataset(service.read_output_file, primary[0], contract, started_after=started)
    if samples.get("identity") != manifest:
        raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "The reader dataset differs from the pre-read frozen set.", "build_blank_mmc_model")
    verify_output_dataset(manifest)
    verify_fault_instrumentation(project, contract)
    samples_path = evidence / "samples.json"
    record["result"].update({"samples_path": str(samples_path), "samples_sha256": _write_evidence(samples_path, samples)})
    return contract, samples


def _owned_native_settlements(service: Any, owner: asyncio.Task[Any] | None) -> tuple[Any, ...]:
    pending = getattr(getattr(service, "executor", None), "pending_settlements_for", None)
    return tuple(token for token in pending(owner) if not token.settled) if callable(pending) and owner is not None else ()


async def _contain_native_failure(service: Any, record: dict[str, Any], pending: tuple[Any, ...] = (), *, timeout_s: float = 30.0) -> tuple[Any, ...]:
    pending = tuple(token for token in pending if not token.settled)
    if pending:
        record["containment"] = {"confirmed": False, "required": True, "reason": "Owned vendor calls have not settled"}
        return pending
    if record.get("result", {}).get("reload", {}).get("cleanup_pending"):
        record["containment"] = {"confirmed": False, "required": True, "reason": "Independent replay ownership remains unresolved"}
        return ()
    if not record.get("run_started") or record.get("run_completed"):
        record["containment"] = {"confirmed": True, "required": False}
        return ()
    name = record.get("runtime_project_name")
    stop_task = None
    try:
        stop = getattr(service, "stop_simulation", None)
        if not callable(stop):
            raise _error("MMC_BUILD_UNAVAILABLE", "No project-scoped stop capability is available", "build_blank_mmc_model")
        stop_task = asyncio.create_task(stop(name))
        await asyncio.wait_for(stop_task, timeout=timeout_s)
        state = await service.get_run_status(name)
        record["containment"] = {"confirmed": _status_value(state) in _TERMINAL_SUCCESS | _TERMINAL_FAILURE, "project": name, "project_status": state}
    except BaseException as error:  # noqa: BLE001 - do not replace the primary build failure
        record["containment"] = {"confirmed": False, "project": name, "error": str(error)}
    pending = tuple(dict.fromkeys((*_owned_native_settlements(service, stop_task), *_owned_native_settlements(service, asyncio.current_task()))))
    if pending:
        record["containment"]["confirmed"] = False
    return pending


def _materialize_native_mmc_case(plan: Mapping[str, Any], source: Path, library: Path, staging: Path, project: Path, record: dict[str, Any]) -> dict[str, Any]:
    """Apply the declared recipe identically for public and joint preparation."""
    master = Path(plan["source_identities"]["master"]["path"])
    lineage = record.setdefault("lineage", [])
    fault = staging / "native_fault_source.pscx"
    binding = materialize_template_native_scenario(source, fault, dc_fault_time_s=plan["fault"]["time_s"], fault_duration_s=plan["fault"]["removal_time_s"] - plan["fault"]["time_s"])
    lineage.append({"stage": "native_fault", **binding})
    selected = staging / "charging_source.pscx"
    lineage.append({"stage": "terminal_two_charging", **materialize_terminal_two_charging(fault, selected)})
    recipe = plan["model_recipe"]
    if recipe["name"] != "raw":
        headroom = staging / "headroom_source.pscx"
        lineage.append({"stage": "headroom", **materialize_voltage_control_headroom(selected, headroom, current_limit_pu=recipe["parameters"]["current_limit_pu"])})
        selected = headroom
    if "dc_feedback_time_constant_s" in recipe["parameters"]:
        filtered = staging / "filtered_source.pscx"
        lineage.append({"stage": "dc_feedback_filter", **materialize_dc_feedback_filter(selected, filtered, master=master, time_constant_s=recipe["parameters"]["dc_feedback_time_constant_s"])})
        selected = filtered
    if "sort_extent" in recipe["parameters"]:
        carrier = staging / "carrier_source.pscx"
        lineage.append({"stage": "terminal_two_carrier", **materialize_terminal_two_carrier(selected, carrier)})
        damped = staging / "arm_virtual_resistance_source.pscx"
        lineage.append({"stage": "arm_virtual_resistance", **materialize_arm_virtual_resistance(carrier, damped, master=master)})
        selected = staging / "complete_arm_sorting_source.pscx"
        lineage.append({"stage": "complete_arm_sorting", **materialize_complete_arm_sorting(damped, selected, library=library)})
    if "t1_dc_integral_time_s" in recipe["parameters"]:
        integral = staging / "dc_integral_source.pscx"
        lineage.append({"stage": "voltage_control_integral_time", **materialize_voltage_control_integral_time(selected, integral)})
        selected = integral
    contract = instrument_fault_channels(selected, project, library=library, master=master,
        expected_source_hashes={"project": _sha256(selected), "library": plan["source_identities"]["library"]["sha256"], "master": plan["source_identities"]["master"]["sha256"]})
    return contract


async def _execute_native_mmc_plan(
    plan: Mapping[str, Any], service: Any, workspace: Path, *,
    build_id: str, journal: AtomicJournal, record: dict[str, Any],
    audit_loader: Callable[..., Any], replay_verifier: Callable[..., Any] | None,
) -> dict[str, Any]:
    record["result"] = {}
    checkpoint = lambda state: _checkpoint(record, journal, state)
    _verify_plan_inputs(plan, audit_loader)
    record["runtime_master"] = await _verify_runtime_master(service, plan["source_identities"]["master"])
    staging = Path(plan["staging_path"])
    target = Path(plan["target_path"])
    if _native_name(target) in {_native_name(item["path"]) for item in plan["source_identities"].values()}:
        raise _error("MMC_BUILD_CONFLICT", "The derived case must have a new runtime identity.", "build_blank_mmc_model")
    staging.mkdir(parents=True, exist_ok=False)
    bundle = staging / (target.stem + ".bundle")
    bundle.mkdir()
    checkpoint("staging_created")
    source, library = await _stage_dependencies(plan, staging, bundle, record)
    project = staging / target.name
    contract = _materialize_native_mmc_case(plan, source, library, staging, project, record)
    recipe = plan["model_recipe"]
    evidence = bundle / "evidence"
    _write_evidence(evidence / "plan.json", plan)
    _write_evidence(evidence / "checks.json", plan["checks_contract"])
    record["result"].update({"project_file": str(project), "scenario_source": str(project), "model_recipe": copy.deepcopy(recipe)})
    checkpoint("instrumented")
    contract, samples = await _run_native_fault_case(service, project, library, contract, plan["checks_contract"], plan["settings"], evidence, record, checkpoint)
    acceptance = evaluate_template_native_dc_fault(samples, channel_contract=contract, checks_contract=plan["checks_contract"],
        fault_current_limit_ka=plan["checks_contract"]["fault_current_limit_ka"], topology=SubmoduleTopology(plan["request"]["submodule_topology"]))
    record["result"]["acceptance"] = acceptance
    _write_evidence(evidence / "acceptance.json", acceptance)
    checkpoint("evaluated")
    _verify_plan_inputs(plan, audit_loader)
    _verify_copies(record["dependency_copies"])
    if acceptance.get("verdict") != "PASS":
        code = "MMC_ACCEPTANCE_INCOMPLETE" if acceptance.get("verdict") in {"INCOMPLETE_ANALYSIS", "NOT_APPLICABLE"} else "MMC_ACCEPTANCE_FAILED"
        raise _error(code, "The actual native fault evidence did not satisfy the fixed production checks.", "build_blank_mmc_model", acceptance=acceptance)
    if replay_verifier is None:
        from .native_fault_replay import verify_native_fault_replay
        replay_verifier = verify_native_fault_replay
    record["result"]["reload"] = {"status": "FAIL", "cleanup_pending": True, "owned_process_cleaned": False,
                                   "workspace": str(staging / "reload-verification"), "phase": "verification_requested"}
    checkpoint("verifying_reload")
    replay = await replay_verifier(project=project, bundle=bundle, channel_contract=contract, checks_contract=plan["checks_contract"],
        settings=plan["settings"], source_identities=plan["source_identities"],
        dependency_files={Path(item["path"]).relative_to(bundle).as_posix(): item["sha256"] for item in record["dependency_copies"]},
        workspace=staging / "reload-verification")
    record["result"]["reload"] = replay
    if replay.get("status") != "PASS" or replay.get("project_sha256") != _sha256(project) or replay.get("checks_sha256") != plan["checks_sha256"] or replay.get("owned_process_cleaned") is not True or replay.get("worker_exit_code") != 0 or replay.get("parent_channel_contract_sha256") != hashlib.sha256(json_bytes(contract)).hexdigest() or not replay.get("artifacts"):
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The frozen saved model did not pass independent owned replay.", "build_blank_mmc_model", replay=replay)
    replay_report = _read_hashed_json(_bundle_file(staging / "reload-verification", "worker/report.json"), replay["report_sha256"])
    if replay_report.get("status") != "PASS" or replay_report.get("parent_channel_contract_sha256") != replay["parent_channel_contract_sha256"]:
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The independent replay summary differs from its frozen worker report.", "build_blank_mmc_model")
    _verify_plan_inputs(plan, audit_loader)
    _verify_copies(record["dependency_copies"])
    verify_fault_instrumentation(project, contract)
    record["result"].update(_publish_tested_fault_case(plan, project, bundle, contract, record))
    checkpoint("published")
    return record


def _bundle_file(bundle: Path, relative: str) -> Path:
    child = Path(relative)
    if child.is_absolute() or child.drive or ".." in child.parts or not child.parts:
        raise _error("MMC_LAYOUT_INVALID", "A bundle member must be a relative path inside its bundle.", "validate_blank_mmc_model", path=relative)
    path = bundle / child
    for ancestor in (path, *path.parents):
        if _is_reparse_point(ancestor.lstat()):
            raise _error("MMC_LAYOUT_INVALID", "Bundle members must not traverse links.", "validate_blank_mmc_model", path=str(path))
        if ancestor == bundle:
            break
    if not path.is_file() or not path.resolve().is_relative_to(bundle.resolve()):
        raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "A required bundle file is absent.", "validate_blank_mmc_model", path=str(path))
    return path.resolve()


def _bundle_files(bundle: Path, *, omit_manifest: bool = False) -> dict[str, str]:
    identities = {}
    for path in sorted(bundle.rglob("*")):
        if _is_reparse_point(path.lstat()):
            raise _error("MMC_LAYOUT_INVALID", "Bundle members must not be links.", "validate_blank_mmc_model", path=str(path))
        if path.is_file():
            relative = path.relative_to(bundle).as_posix()
            if not omit_manifest or relative != "manifest.json":
                identities[relative] = _sha256(_bundle_file(bundle, relative))
    return identities


def _read_hashed_json(path: Path, digest: str) -> dict[str, Any]:
    if _sha256(path) != digest:
        raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "Frozen evidence changed before reading.", "validate_blank_mmc_model", path=str(path))
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or _sha256(path) != digest:
        raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "Frozen evidence changed while reading.", "validate_blank_mmc_model", path=str(path))
    return value


def _load_publication_evidence(project: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    bundle = project.with_suffix(".bundle")
    try:
        manifest_path = _bundle_file(bundle, "manifest.json")
        publication = _read_hashed_json(manifest_path, _sha256(manifest_path))
        plan = publication["plan"]
        _verify_frozen_plan(plan)
        if publication["project_sha256"] != _sha256(project) or _bundle_files(bundle, omit_manifest=True) != publication["bundle_files"]:
            raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "The tested project or published bundle changed.", "validate_blank_mmc_model")
        contract = _read_hashed_json(_bundle_file(bundle, publication["channel_contract_relative_path"]), publication["channel_contract_sha256"])
        checks = _read_hashed_json(_bundle_file(bundle, publication["checks_relative_path"]), publication["checks_file_sha256"])
        if checks != plan["checks_contract"] or publication["checks_sha256"] != plan["checks_sha256"] or contract.get("required_checks") != checks or contract.get("vendor_finalized") is not True:
            raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "Published channel and check contracts disagree.", "validate_blank_mmc_model")
        replay = publication["reload"]
        parent = _read_hashed_json(_bundle_file(bundle, "evidence/channels.json"), contract["publication_parent_contract_sha256"])
        if replay.get("status") != "PASS" or replay.get("project_sha256") != publication["project_sha256"] or replay.get("checks_sha256") != publication["checks_sha256"] or replay.get("owned_process_cleaned") is not True or replay.get("worker_exit_code") != 0 or replay.get("parent_channel_contract_sha256") != hashlib.sha256(json_bytes(parent)).hexdigest():
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The publication has no completed independent replay.", "validate_blank_mmc_model")
        replay_report = _read_hashed_json(_bundle_file(bundle, "reload/worker/report.json"), replay["report_sha256"])
        if replay_report.get("status") != "PASS" or replay_report.get("parent_channel_contract_sha256") != replay["parent_channel_contract_sha256"]:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The copied replay report disagrees with its summary.", "validate_blank_mmc_model")
        for relative, identity in replay["artifacts"].items():
            if _sha256(_bundle_file(bundle / "reload", relative)) != identity["sha256"]:
                raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "An independent replay artifact changed.", "validate_blank_mmc_model")
        contract["project_path"] = str(project)
        contract["readback"]["project_path"] = str(project)
        parent["project_path"] = str(project)
        parent["readback"]["project_path"] = str(project)
        if {key: value for key, value in contract.items() if key != "publication_parent_contract_sha256"} != parent:
            raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "The published channel contract differs from its tested parent.", "validate_blank_mmc_model")
        verify_fault_instrumentation(project, contract)
        identity = _read_hashed_json(_bundle_file(bundle, publication["output_index_relative_path"]), publication["output_index_sha256"])
        identity["primary"] = str(_bundle_file(bundle, identity["primary"]))
        for name, item in identity["files"].items():
            item["path"] = str(_bundle_file(bundle, item["path"]))
            if Path(item["path"]).name != name:
                raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "Output filename and index key disagree.", "validate_blank_mmc_model")
        verify_output_dataset(identity)
        if identity["primary"] != str(_bundle_file(bundle, publication["output_file_relative_path"])):
            raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "The published primary output differs from its index.", "validate_blank_mmc_model")
        return publication, contract, checks, identity
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "The publication evidence is missing or malformed.", "validate_blank_mmc_model", reason=str(error)) from error


def _publish_tested_fault_case(plan: Mapping[str, Any], project: Path, bundle: Path, contract: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any]:
    target = Path(plan["target_path"])
    final_bundle = target.parent / bundle.name
    if target.exists() or target.is_symlink() or final_bundle.exists() or final_bundle.is_symlink():
        raise _error("MMC_BUILD_CONFLICT", "A publication destination already exists.", "build_blank_mmc_model")
    tested_bundle = bundle
    tested_bundle_files = _bundle_files(tested_bundle)
    candidate = project.parent / "publication-candidate"
    candidate.mkdir()
    candidate_bundle = candidate / bundle.name
    candidate_project = candidate / project.name
    shutil.copytree(tested_bundle, candidate_bundle)
    if _bundle_files(candidate_bundle) != tested_bundle_files:
        raise _error("MMC_POSTCONDITION_FAILED", "The copied publication dependencies differ from the tested bundle.", "build_blank_mmc_model")
    bundle = candidate_bundle
    tested_hash = _sha256(project)
    result = record["result"]
    manifest = _read_hashed_json(Path(result["output_index_path"]), result["output_index_sha256"])
    frozen_contract = _read_hashed_json(Path(result["channel_contract_path"]), result["channel_contract_sha256"])
    if frozen_contract != contract:
        raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "The evaluated channel contract differs from its frozen file.", "build_blank_mmc_model")
    verify_output_dataset(manifest)
    replay_root = project.parent / "reload-verification"
    for relative, item in result["reload"]["artifacts"].items():
        origin = _bundle_file(replay_root, relative)
        if origin != Path(item["path"]).resolve():
            raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "Replay artifact path differs from its owned directory.", "build_blank_mmc_model")
        _copy_frozen(origin, bundle / "reload" / relative, item["sha256"])
    output_copy = bundle / "outputs"
    output_copy.mkdir()
    for item in manifest["files"].values():
        _copy_frozen(Path(item["path"]), output_copy / Path(item["path"]).name, item["sha256"])
    published_identity = copy.deepcopy(manifest)
    published_identity["primary"] = "outputs/" + Path(manifest["primary"]).name
    for item in published_identity["files"].values():
        item["path"] = "outputs/" + Path(item["path"]).name
    output_index_sha256 = _write_evidence(bundle / "evidence" / "published-output-index.json", published_identity)
    published_contract = copy.deepcopy(dict(contract))
    published_contract["project_path"] = str(target)
    published_contract["readback"]["project_path"] = str(target)
    published_contract["publication_parent_contract_sha256"] = record["result"]["channel_contract_sha256"]
    _write_evidence(bundle / "evidence" / "published-channels.json", published_contract)
    publication = {"schema_version": 1, "plan": copy.deepcopy(dict(plan)), "project_sha256": tested_hash,
        "channel_contract_relative_path": "evidence/published-channels.json",
        "channel_contract_sha256": _sha256(bundle / "evidence" / "published-channels.json"),
        "checks_relative_path": "evidence/checks.json", "checks_sha256": plan["checks_sha256"],
        "checks_file_sha256": _sha256(bundle / "evidence" / "checks.json"),
        "output_index_relative_path": "evidence/published-output-index.json", "output_index_sha256": output_index_sha256,
        "output_file_relative_path": published_identity["primary"],
        "output_started_after": record["run_started_after"], "acceptance": record["result"]["acceptance"],
        "runtime_master": record["runtime_master"], "lineage": record["lineage"],
        "reload": record["result"]["reload"], "bundle_files": _bundle_files(bundle)}
    _write_evidence(bundle / "manifest.json", publication)
    bundle_files = _bundle_files(bundle)
    verify_output_dataset(manifest)
    _copy_frozen(project, candidate_project, tested_hash)
    if _bundle_files(candidate_bundle) != bundle_files or _bundle_files(tested_bundle) != tested_bundle_files:
        raise _error("MMC_POSTCONDITION_FAILED", "The publication candidate differs from its tested inputs.", "build_blank_mmc_model")
    _load_publication_evidence(candidate_project)
    target.parent.mkdir(parents=True, exist_ok=True)
    candidate_bundle.rename(final_bundle)
    exposed = False
    try:
        # An exclusive hard link exposes only the already verified complete bytes.
        os.link(candidate_project, target)
        exposed = True
        candidate_project.unlink()
    except BaseException:
        if exposed:
            target.unlink()
        final_bundle.rename(candidate_bundle)
        raise
    return {"final_project_sha256": tested_hash, "tested_project_sha256": tested_hash, "scenario_source": str(target),
        "final_library_path": str(final_bundle / Path(plan["source_identities"]["library"]["path"]).name),
        "bundle_path": str(final_bundle), "publication_manifest": str(final_bundle / "manifest.json"),
        "published_output_file": str(final_bundle / publication["output_file_relative_path"])}


__all__ = ["BlankMmcBuilderService"]
