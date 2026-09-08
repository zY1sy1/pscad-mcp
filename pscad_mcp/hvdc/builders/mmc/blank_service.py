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
import re
import shutil
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ....core.backend.base import BackendError
from ....core.path_policy import PathPolicy
from ....core.service import ConfirmationRequired
from ....runtime import PendingCleanupError
from ..lcc.executor import _select_output_dataset
from .blank import BlankMmcRequest
from .fault_channels import default_fault_checks
from .journal import AtomicJournal, WorkspaceBuildLease
from .line_constants import extract_tline_segments, render_tli
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
}
_WINDOWS_DEVICE = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", re.IGNORECASE)


def _default_master_path() -> Path:
    return Path("C:/Program Files (x86)/PSCAD46/master.pslx")


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

    def __init__(self, pscad_service: Any, *, workspace_root: str | Path, audit_loader: Callable[..., Any] = audit_mmc_template) -> None:
        self.pscad_service = pscad_service
        self.workspace_root = _workspace(workspace_root)
        self.path_policy = PathPolicy(workspace_root=str(self.workspace_root))
        self.audit_loader = audit_loader
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
            "request_implementation": {"ratings": {"binding": "descriptive_only", "requested": dict(parsed.ratings)}, "control_profile": "audited_existing_native_controls", "fault_profile": "materialized_native_dc_fault", "native_model_basis": {"dc_pole_to_pole_voltage_kv": 640.0, "controlled_terminal_active_power_mw": -900.0, "rated_converter_mva": 1000.0}},
            "project_name": name,
            "workspace": str(self.workspace_root),
            "target_path": str(target),
            "staging_path": str(self.workspace_root / ".pscad-mcp" / "blank-mmc-builds" / f"{name}-{source_hashes['project'][:12]}.staging"),
            "settings": {"simulation_duration_s": float(duration), "time_step_s": checks["time_step_s"], "output_step_s": checks["output_step_s"], "output_enabled": True},
            "fault": {"kind": "dc_pole_to_pole", "time_s": checks["fault_window_s"][0], "removal_time_s": checks["fault_window_s"][1]},
            "checks_contract": checks,
            "checks_sha256": hashlib.sha256(json_bytes(checks)).hexdigest(),
            "model_recipe": {"schema_version": 1, "name": recipe, "parameters": copy.deepcopy(_MODEL_RECIPES[recipe]), "physical_acceptance_verified": False},
            "source_identities": identities,
            "runtime_requirements": {"backend": "legacy", "pscad_version": "4.6.2", "master_source_must_match": identities["master"], "new_case_namespace": True},
            "compiler_support": support,
            "line_constants": lines,
            "template_native": {"source_paths": {"project": str(template), "library": str(library)}, "source_hashes": source_hashes, "submodule_topology": dict(observed_topology) if isinstance(observed_topology, Mapping) else {}, "controls": dict(audit.get("template_native_controls", {})) if isinstance(audit.get("template_native_controls", {}), Mapping) else {}},
            "capabilities": {**SubmoduleTopology.capabilities(parsed.submodule_topology), "template_submodule_topology": observed_name, "native_schedule": False, "template_native_timing": bool(isinstance(audit.get("template_native_controls"), Mapping) and audit["template_native_controls"].get("available") is True)},
            "operations": ["audit_source", "verify_runtime_master", "stage_frozen_dependencies", "materialize_model_recipe", "materialize_template_fault", "instrument_fault_channels", "save_and_finalize_readback", "compile", "simulate_template_native_fault", "freeze_output_dataset", "validate_production_fault_evidence", "publish_tested_case"],
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
        try:
            record = await _execute_native_mmc_plan(
                plan,
                self.pscad_service,
                self.workspace_root,
                build_id=build_id,
                journal=journal,
            )
        except asyncio.CancelledError:
            record = {
                "build_id": build_id,
                "state": "interrupted",
                "plan_hash": plan["plan_hash"],
                "plan": copy.deepcopy(plan),
                "error": _error(
                    "MMC_BUILD_FAILED",
                    "The blank MMC build was interrupted.",
                    "build_blank_mmc_model",
                ).to_dict(),
                "result": None,
                "history": [{"state": "validated"}, {"state": "interrupted"}],
                "workspace": str(self.workspace_root),
            }
        except BaseException as error:  # noqa: BLE001 - lifecycle records capture vendor failures
            backend_error = (
                error
                if isinstance(error, BackendError)
                else _error(
                    "MMC_BUILD_FAILED",
                    "The blank MMC build failed.",
                    "build_blank_mmc_model",
                    exception=type(error).__name__,
                )
            )
            record = {
                "build_id": build_id,
                "state": "failed",
                "plan_hash": plan["plan_hash"],
                "plan": copy.deepcopy(plan),
                "error": backend_error.to_dict(),
                "result": None,
                "history": [
                    {"state": "validated"},
                    {"state": "failed", "reason": backend_error.code},
                ],
                "workspace": str(self.workspace_root),
            }
        finally:
            self._statuses[build_id] = record
            journal.write(record)
            lease.release(lease.token)
            self._leases.pop(build_id, None)
        return record

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
            "native_template": native_audit,
            "capabilities": SubmoduleTopology.capabilities(
                SubmoduleTopology.FULL_BRIDGE
                if topology_name == "full_bridge"
                else SubmoduleTopology.HALF_BRIDGE
            )
            if topology_name in {"full_bridge", "half_bridge"}
            else {"intrinsic_dc_fault_blocking": False},
        }
        if output_file is None:
            return result
        raw_output = Path(output_file).expanduser()
        if raw_output.is_symlink():
            raise _error(
                "MMC_LAYOUT_INVALID",
                "The MMC output must not be a symbolic link.",
                "validate_blank_mmc_model",
                output_file=str(raw_output),
            )
        output = raw_output.resolve()
        try:
            output.relative_to(self.workspace_root)
        except ValueError as error:
            raise _error("MMC_LAYOUT_INVALID", "The MMC output is outside the workspace.", "validate_blank_mmc_model") from error
        reader = getattr(self.pscad_service, "read_output_file", None)
        if not callable(reader):
            raise _error("MMC_OUTPUT_INCOMPLETE", "The PSCAD service does not expose an output reader.", "validate_blank_mmc_model")
        samples = _run_sync(lambda: _read_async(reader, str(output)))
        if topology_name not in {"full_bridge", "half_bridge"}:
            acceptance = {
                "verdict": "INCOMPLETE_ANALYSIS",
                "reason": "The MMC template topology was not explicitly audited.",
            }
        else:
            topology = SubmoduleTopology(topology_name)
            acceptance = evaluate_template_native_dc_fault(
                samples,
                fault_current_limit_ka=20.0,
                topology=topology,
            )
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
        for build_id, lease in tuple(self._leases.items()):
            record = self._statuses.get(build_id)
            if record is not None:
                AtomicJournal(self.workspace_root, build_id).write(record)
            lease.release(lease.token)
            self._leases.pop(build_id, None)


def json_bytes(value: Any) -> bytes:
    import json

    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


async def _read_async(reader: Any, output_file: str) -> Any:
    try:
        return await reader(output_file, max_samples=1_000_000, summary_only=False)
    except TypeError:
        return await reader(output_file)


async def _execute_native_mmc_plan(
    plan: Mapping[str, Any],
    service: Any,
    workspace: Path,
    *,
    build_id: str,
    journal: AtomicJournal,
) -> dict[str, Any]:
    """Run one audited official MMC template and retain incomplete evidence."""

    source_paths = plan["template_native"]["source_paths"]
    source_hashes = plan["template_native"]["source_hashes"]
    source_project = Path(str(source_paths["project"])).expanduser().resolve()
    source_library = Path(str(source_paths["library"])).expanduser().resolve()
    for key, path in (("project", source_project), ("library", source_library)):
        if not path.is_file() or path.is_symlink() or _sha256(path) != str(source_hashes[key]):
            raise _error("MMC_PLAN_STALE", "An official MMC source changed after planning.", "build_blank_mmc_model", source=key, path=str(path))
    staging = Path(str(plan["staging_path"])).expanduser().resolve()
    project_name = str(plan["project_name"])
    staging.mkdir(parents=True, exist_ok=False)
    staged_library = staging / source_library.name
    staged_project = staging / f"{project_name}.pscx"
    shutil.copy2(source_library, staged_library)
    support = source_library.parent / "Obj_Files_2016_03_25"
    if support.is_dir():
        shutil.copytree(support, staging / support.name)
    from ....core.backend import legacy_support

    legacy_support.rewrite_template_identity(
        source_project,
        staged_project,
        project_name,
    )
    loader = getattr(service, "load_projects", None)
    writer = getattr(service, "set_project_settings", None)
    settings_reader = getattr(service, "get_project_settings", None)
    saver = getattr(service, "save_project", None)
    builder = getattr(service, "build_project", None)
    runner = getattr(service, "run_project", None)
    status_reader = getattr(service, "get_run_status", None)
    discover = getattr(service, "discover_output_files", None)
    reader = getattr(service, "read_output_file", None)
    required = {
        "load_projects": loader,
        "set_project_settings": writer,
        "get_project_settings": settings_reader,
        "save_project": saver,
        "build_project": builder,
        "run_project": runner,
        "get_run_status": status_reader,
        "discover_output_files": discover,
        "read_output_file": reader,
    }
    missing = sorted(name for name, method in required.items() if not callable(method))
    if missing:
        raise _error("MMC_BUILD_UNAVAILABLE", "The PSCAD service lacks native blank MMC lifecycle capabilities.", "build_blank_mmc_model", missing=missing)
    await loader([str(staged_library), str(staged_project)])
    requested = {
        "time_duration": str(plan["settings"]["simulation_duration_s"]),
        "time_step": "50",
        "sample_step": "250",
        "PlotType": "1",
        "output_filename": f"{project_name}.out",
    }
    await writer(project_name, requested)
    observed = await settings_reader(project_name)
    if not isinstance(observed, Mapping) or any(str(observed.get(key)) != value for key, value in requested.items()):
        raise _error("MMC_POSTCONDITION_FAILED", "Native MMC project settings did not read back exactly.", "build_blank_mmc_model", expected=requested, observed=observed)
    await saver(project_name, confirm=True)
    await builder(project_name)
    scenario = staging / f"{project_name}_scenario_source.pscx"
    materialize_template_native_scenario(
        staged_project,
        scenario,
        dc_fault_time_s=float(plan["fault"]["time_s"]),
        fault_duration_s=float(plan["fault"]["removal_time_s"] - plan["fault"]["time_s"]),
    )
    await loader([str(staged_library), str(scenario)])
    await writer(scenario.stem, {**requested, "output_filename": f"{scenario.stem}.out"})
    await saver(scenario.stem, confirm=True)
    await builder(scenario.stem)
    started_after = time.time()
    await runner(scenario.stem)
    deadline = time.monotonic() + 900.0
    while True:
        state = await status_reader(scenario.stem)
        value = _status_value(state)
        if value in _TERMINAL_FAILURE:
            raise _error("MMC_BUILD_FAILED", "The native MMC simulation failed.", "build_blank_mmc_model", status=state)
        if value in _TERMINAL_SUCCESS:
            break
        if time.monotonic() >= deadline:
            raise _error("MMC_BUILD_TIMED_OUT", "The native MMC simulation did not finish in time.", "build_blank_mmc_model")
        await asyncio.sleep(0.25)
    paths = await discover(str(scenario), started_after=started_after, max_files=32)
    candidates = sorted({str(Path(path).expanduser().resolve()) for path in paths if isinstance(path, str) and path}, key=str.casefold)
    for path in candidates:
        candidate = Path(path)
        if candidate.is_symlink() or not candidate.is_file():
            raise _error("MMC_OUTPUT_INCOMPLETE", "A native MMC output is not a regular file.", "build_blank_mmc_model", path=path)
        try:
            candidate.relative_to(staging)
        except ValueError as error:
            raise _error("MMC_OUTPUT_INCOMPLETE", "A native MMC output escaped staging.", "build_blank_mmc_model", path=path) from error
    if not candidates:
        raise _error("MMC_OUTPUT_INCOMPLETE", "The native MMC simulation produced no output.", "build_blank_mmc_model")
    output_file, output_parts = _select_output_dataset(candidates)
    samples = await reader(output_file, max_samples=1_000_000, summary_only=False)
    topology = SubmoduleTopology(plan["request"]["submodule_topology"])
    acceptance = evaluate_template_native_dc_fault(samples, fault_current_limit_ka=20.0, topology=topology)
    target = Path(str(plan["target_path"])).expanduser().resolve()
    archive = target.with_name(f"{target.stem}.outputs")
    if archive.exists() or archive.is_symlink():
        raise _error("MMC_BUILD_CONFLICT", "The native MMC output evidence directory already exists.", "build_blank_mmc_model", path=str(archive))
    archive.mkdir(parents=True, exist_ok=False)
    archived_parts: list[str] = []
    for path in output_parts:
        destination = archive / Path(path).name
        shutil.copy2(path, destination)
        archived_parts.append(str(destination.resolve()))
    base = re.sub(r"_\d{2}$", "", Path(output_file).stem)
    for suffix in (".inf", ".infx"):
        metadata = Path(output_file).with_name(base + suffix)
        if metadata.is_file() and not metadata.is_symlink():
            shutil.copy2(metadata, archive / metadata.name)
    persisted_output = str(archive / Path(output_file).name)
    if acceptance.get("verdict") != "PASS":
        code = "MMC_ACCEPTANCE_INCOMPLETE" if acceptance.get("verdict") == "INCOMPLETE_ANALYSIS" else "MMC_ACCEPTANCE_FAILED"
        return {
            "build_id": build_id,
            "state": "failed",
            "plan_hash": plan["plan_hash"],
            "target_path": str(target),
            "staging_path": str(staging),
            "workspace": str(workspace),
            "history": [{"state": "validated"}, {"state": "staging_created"}, {"state": "compiled"}, {"state": "simulated", "output_file": persisted_output}, {"state": "acceptance_incomplete", "verdict": acceptance.get("verdict")}],
            "error": _error(code, "The native MMC fault evidence is not sufficient for the requested topology.", "build_blank_mmc_model", acceptance=acceptance).to_dict(),
            "result": {"output_file": persisted_output, "output_parts": archived_parts, "acceptance": acceptance, "scenario_source": str(scenario), "template_native": dict(plan["template_native"])},
        }
    save_as = getattr(service, "save_project_as", None)
    if not callable(save_as):
        raise _error("MMC_BUILD_UNAVAILABLE", "The PSCAD service cannot publish the native MMC project.", "build_blank_mmc_model")
    target.parent.mkdir(parents=True, exist_ok=True)
    await save_as(staged_project.stem, target.name, str(target.parent), confirm=False)
    final_library = target.parent / source_library.name
    if final_library.exists() or final_library.is_symlink():
        raise _error("MMC_BUILD_CONFLICT", "The native MMC companion publication target already exists.", "build_blank_mmc_model", path=str(final_library))
    shutil.copy2(staged_library, final_library)
    scenario_target = target.with_name(f"{target.stem}_scenario_source.pscx")
    shutil.copy2(target, scenario_target)
    await loader([str(final_library), str(target)])
    await builder(target.stem)
    return {
        "build_id": build_id,
        "state": "published",
        "plan_hash": plan["plan_hash"],
        "target_path": str(target),
        "staging_path": str(staging),
        "workspace": str(workspace),
        "history": [{"state": "validated"}, {"state": "published"}],
        "error": None,
        "result": {"output_file": persisted_output, "output_parts": archived_parts, "acceptance": acceptance, "final_library_path": str(final_library), "scenario_source": str(scenario_target), "final_project_sha256": _sha256(target)},
    }


__all__ = ["BlankMmcBuilderService"]
